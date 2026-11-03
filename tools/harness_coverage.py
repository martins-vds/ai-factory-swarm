#!/usr/bin/env python3
"""Which harness paths has this target repo exercised? Computed, never hand-listed (ADR-0027).

The universe is derived from what the harness installed, so a new role, status, tool or workflow is
counted the moment it ships:
  * agent roles, and every enum a role's return file can carry   ← .migration/harness/schemas/return.schema.json
  * every ledger enum (kind, status, verification, tier)          ← .migration/harness/schemas/ledger-entry.schema.json
  * every harness tool                                            ← .migration/harness/tools/
  * every generated workflow                                      ← .github/workflows/ (harness-generated files)
  * every afs:/wayfinder: label                                   ← the repo's labels (GitHub)

The evidence is what the repo kept:
  * every version of every return file and ledger entry in git history (a status passed through counts);
  * run journals (`.migration/evidence/runs/*.md`, all versions): a row whose command runs a harness tool,
    with its exit code;
  * agent sessions: the session hook's committed record (`.migration/costs/*.json`) lists the `AFS-TOOL`
    lines the session's tools printed, the hook itself included;
  * workflow runs (GitHub): the `AFS-TOOL <tool> exit=<code>` lines every tool prints when it ends
    (afs_trace.py) in the job logs. For older runs without them, only the steps whose `run:` calls a
    tool, counted as unconfirmed: a step may call a tool on a branch that didn't run;
  * issues per label (GitHub).

A tool or workflow is exercised on both paths when it has been seen passing **and** failing; a gate that
has only ever passed has never been shown to catch anything. Step-level evidence never makes a tool ✅.

  harness_coverage.py --repo owner/repo [--runs 60] [--out .migration/coverage.md]
  harness_coverage.py --offline                      git evidence only (no GitHub calls)
Prints the Markdown report and `AFS-RESULT gate=coverage …`. Exit 0 (a report, not a gate). Needs git, PyYAML.
"""
import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys

import yaml

HARNESS = pathlib.Path(".migration/harness")


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def gh(path, raw=False):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if r.returncode:
        if raw:
            return ""                  # logs expire; a missing log is no evidence, not an error
        raise RuntimeError(f"gh api {path}: {r.stderr.strip()}")
    return r.stdout if raw else json.loads(r.stdout or "null")


MARK = re.compile(r"AFS-TOOL (\S+) exit=(-?\d+)")


# ------------------------------------------------------------------------------------------ the universe

def enums(schema, where=()):
    """(path of property names, values) for every enum in a JSON schema."""
    out = []
    if isinstance(schema, dict):
        if "enum" in schema:
            out.append((where, [v for v in schema["enum"] if v is not None]))
        for k, v in schema.items():
            out += enums(v, where + ((k,) if k not in ("properties", "items", "allOf", "then", "if", "anyOf",
                                                       "oneOf", "else") else ()))
    elif isinstance(schema, list):
        for v in schema:
            out += enums(v, where)
    return out


def role_fields(schema):
    """{role: {field: values}}: the enums allowed only in one role's return file (if role == X then …)."""
    out = collections.defaultdict(dict)
    for branch in schema.get("allOf", []):
        role = (((branch.get("if") or {}).get("properties") or {}).get("role") or {}).get("const")
        if not role:
            continue
        for field_path, values in enums(branch.get("then") or {}):
            if values:
                out[role][".".join(field_path)] = values
    return out


def universe():
    ret = json.loads((HARNESS / "schemas/return.schema.json").read_text(encoding="utf-8"))
    led = json.loads((HARNESS / "schemas/ledger-entry.schema.json").read_text(encoding="utf-8"))
    roles = next(v for p, v in enums(ret) if p and p[-1] == "role")
    ledger = {k: [x for x in v["enum"] if x is not None] for k, v in led.get("properties", {}).items()
              if isinstance(v, dict) and "enum" in v}
    # A tool is a file whose entry point is afs_trace.run (tests/test_trace.py enforces it); libraries are not.
    tools = sorted(p.name for p in (HARNESS / "tools").iterdir() if p.is_file() and not p.name.startswith(".")
                   and "afs_trace.run(" in p.read_text(encoding="utf-8", errors="ignore").rsplit("__main__", 1)[-1])
    wf = {}
    for p in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
        text = p.read_text(encoding="utf-8")
        if "AI Factory Swarm bootstrap" in text.split("\n", 1)[0]:
            wf[p.name] = yaml.safe_load(text) or {}
    return {"roles": roles, "role_fields": role_fields(ret), "ledger": ledger, "tools": tools, "workflows": wf}


def step_tools(workflows, tools):
    """{(workflow file, step name): [harness tools its run: calls]}"""
    out = {}
    for name, doc in workflows.items():
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                run = str(step.get("run") or "")
                used = [t for t in tools if re.search(rf"harness/tools/{re.escape(t)}\b", run)]
                if used and step.get("name"):
                    out[(name, step["name"])] = used
    return out


# ------------------------------------------------------------------------------------------ the evidence

def history(folder):
    """Every version of every YAML file under a folder, across all of git history."""
    docs = []
    for line in git("log", "--all", "--format=%H", "--name-only", "--diff-filter=AM", "--", folder).splitlines():
        if re.fullmatch(r"[0-9a-f]{40}", line):
            commit = line
        elif line.endswith((".yaml", ".yml", ".json")):
            try:
                doc = yaml.safe_load(git("show", f"{commit}:{line}"))
            except yaml.YAMLError:
                continue
            if isinstance(doc, dict):
                docs.append(doc)
    return docs


def journal_rows():
    """(gate label, exit code, command) for every row of every version of every run journal."""
    rows = set()
    for line in git("log", "--all", "-p", "--format=", "--", ".migration/evidence/runs/").splitlines():
        cells = [c.strip() for c in line[1:].split("|")] if line.startswith("+|") else []
        if len(cells) >= 6 and re.fullmatch(r"-?\d+", cells[3] or ""):
            rows.add((cells[2], int(cells[3]), cells[5].strip("`")))
    return rows


def value_at(doc, dotted):
    cur = [doc]
    for part in dotted.split("."):
        nxt = []
        for c in cur:
            v = c.get(part) if isinstance(c, dict) else None
            nxt += v if isinstance(v, list) else ([v] if v is not None else [])
        cur = nxt
    return {str(v) for v in cur if not isinstance(v, (dict, list))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="owner/repo, for workflow runs and labels")
    ap.add_argument("--runs", type=int, default=60, help="recent runs per workflow to inspect")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    u = universe()
    out, gaps, total = ["# Harness coverage\n",
                        "Derived from the installed harness; evidence from git history and GitHub (ADR-0027).\n"], [], 0

    def line(ok, text):
        nonlocal total
        total += 1
        mark = {True: "✅", None: "⚠️", False: "❌"}[ok]
        if ok is not True:
            gaps.append(text)
        out.append(f"- {mark} {text}")

    returns = history(".migration/returns")
    ledger = history(".migration/ledger")
    out.append("## Agent roles (a committed return file)\n")
    seen_roles = collections.Counter(r.get("role") for r in returns)
    for role in u["roles"]:
        line(seen_roles[role] > 0, f"`{role}`: {seen_roles[role]} return file version(s)")
    out.append("\n## Role-specific values in return files\n")
    for role, fields in sorted(u["role_fields"].items()):
        mine = [r for r in returns if r.get("role") == role]
        for field, values in sorted(fields.items()):
            seen = set().union(*[value_at(r, field) for r in mine]) if mine else set()
            for v in values:
                line(v in seen, f"`{role}` `{field}: {v}`")
    out.append("\n## Ledger values (any version of any entry)\n")
    for field, values in sorted(u["ledger"].items()):
        seen = set().union(*[value_at(e, field) for e in ledger]) if ledger else set()
        for v in values:
            line(v in seen, f"`{field}: {v}`")

    # Tools: pass/fail from journals and workflow steps
    passed, failed, where = collections.defaultdict(int), collections.defaultdict(int), collections.defaultdict(set)
    unconfirmed = collections.defaultdict(int)
    for gate, code, cmd in journal_rows():
        for t in u["tools"]:
            if re.search(rf"harness/tools/{re.escape(t)}\b", cmd):
                (passed if code == 0 else failed)[t] += 1
                where[t].add("journal")
    for rec in history(".migration/costs"):        # agent sessions: the session hook's record (ADR-0027)
        for r in rec.get("harness_tools") or []:
            if r.get("tool") in u["tools"]:
                (passed if r.get("exit") == 0 else failed)[r["tool"]] += r.get("count", 1)
                where[r["tool"]].add("agent session")
    steps = step_tools(u["workflows"], u["tools"])
    wf_conclusions = {}
    if not a.offline and a.repo:
        for name in u["workflows"]:
            runs = (gh(f"repos/{a.repo}/actions/workflows/{name}/runs?per_page={a.runs}") or {}).get("workflow_runs", [])
            wf_conclusions[name] = collections.Counter(r.get("conclusion") for r in runs)
            for run in runs:
                for job in (gh(f"repos/{a.repo}/actions/runs/{run['id']}/jobs") or {}).get("jobs", []):
                    marks = MARK.findall(gh(f"repos/{a.repo}/actions/jobs/{job['id']}/logs", raw=True))
                    for t, code in marks:          # exact: the tool said it ran, and how it ended
                        if t in u["tools"]:
                            (passed if code == "0" else failed)[t] += 1
                            where[t].add(name)
                    if marks:
                        continue
                    for st in job.get("steps") or []:   # older runs, before AFS-TOOL: the step ran, unconfirmed
                        if st.get("conclusion") in ("success", "failure"):
                            for t in steps.get((name, st.get("name")), []):
                                unconfirmed[t] += 1
                                where[t].add(f"{name}, step only")
    out.append("\n## Harness tools (seen passing and failing)\n")
    for t in u["tools"]:
        p, f = passed[t], failed[t]
        ok = True if p and f else (None if p or f or unconfirmed[t] else False)
        extra = f", step-level only {unconfirmed[t]}" if unconfirmed[t] else ""
        line(ok, f"`{t}`: passed {p}, failed {f}{extra}" + (f" ({'; '.join(sorted(where[t]))})" if where[t] else ""))
    if wf_conclusions:
        out.append("\n## Generated workflows (recent runs)\n")
        for name, c in sorted(wf_conclusions.items()):
            ok = True if c.get("success") and c.get("failure") else (None if c.get("success") else False)
            line(ok, f"`{name}`: " + (", ".join(f"{k}={v}" for k, v in sorted(c.items(), key=str)) or "never ran"))
        labels = [lb["name"] for lb in gh(f"repos/{a.repo}/labels?per_page=100") or []
                  if lb["name"].startswith(("afs:", "wayfinder:"))]
        out.append("\n## Labels (issues ever labelled)\n")
        for lb in sorted(labels):
            n = len(gh(f"repos/{a.repo}/issues?state=all&labels={lb}&per_page=100") or [])
            line(n > 0, f"`{lb}`: {n} issue(s)")
    covered = total - len(gaps)
    out.append(f"\n**{covered} of {total} paths exercised; {len(gaps)} to go.**")
    report = "\n".join(out) + "\n"
    if a.out:
        pathlib.Path(a.out).write_text(report, encoding="utf-8")
    print(report)
    print(f"AFS-RESULT gate=coverage paths={total} exercised={covered} gaps={len(gaps)}")
    return 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
