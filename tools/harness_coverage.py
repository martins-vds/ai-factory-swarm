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

**Kept evidence.** Workflow runs age out of GitHub's recent-runs window, and with them the failing run that
proved a gate catches something. `--keep` merges what this run saw into `.migration/evidence/coverage.json`
(a link to the first run, journal or session that showed each side) and every run reads that file back, so
a path once exercised stays exercised, with its proof. Commit the file like any evidence.

A tool or workflow is exercised on both paths when it has been seen passing **and** failing; a gate that
has only ever passed has never been shown to catch anything. One that reports and never blocks declares
it (`afs_trace.run(main, verdict=False)`, or `# afs-coverage: no-verdict` in a workflow): seeing it run is
enough. `afs-drill` makes the failing runs on purpose. Step-level evidence never makes a tool ✅.

  harness_coverage.py --repo owner/repo [--runs 60] [--out .migration/coverage.md]
  harness_coverage.py --repo o/r --keep              also record what it saw in .migration/evidence/coverage.json
  harness_coverage.py --offline                      git evidence only (no GitHub calls)
  harness_coverage.py --repo o/r --json pilot.json      also write each path's status by key
  harness_coverage.py --union pilot.json synthetic.json  the union across targets (ADR-0037)
Prints the Markdown report and `AFS-RESULT gate=coverage …`. Exit 0 (a report, not a gate). Needs git, PyYAML.
"""
import argparse
import collections
import json
import pathlib
import re
import subprocess
import time
import sys

import yaml

HARNESS = pathlib.Path(".migration/harness")


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


TRANSIENT = re.compile(r"HTTP 5\d\d|timed out|connection reset", re.I)


def gh(path, raw=False, tries=4, wait=2.0):
    """`gh api`, retried on a transient GitHub error (5xx, timeout): one bad response must not end a report
    that reads hundreds of runs (pilot: HTTP 502 on one jobs list)."""
    for attempt in range(tries):
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
        if not r.returncode or not TRANSIENT.search(r.stderr) or attempt == tries - 1:
            break
        time.sleep(wait * 2 ** attempt)
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


def _is_tool(text):
    """A tool calls afs_trace.run after its `__main__` guard; a library that only mentions the call is not one."""
    _, sep, entry = text.rpartition("__main__")
    return bool(sep) and "afs_trace.run(" in entry


def _no_verdict(text):
    """A tool that reports and never blocks declares it: `afs_trace.run(main, verdict=False)`."""
    return "verdict=False" in text.rpartition("__main__")[2]


NO_VERDICT_WF = "# afs-coverage: no-verdict"


def universe():
    ret = json.loads((HARNESS / "schemas/return.schema.json").read_text(encoding="utf-8"))
    led = json.loads((HARNESS / "schemas/ledger-entry.schema.json").read_text(encoding="utf-8"))
    roles = next(v for p, v in enums(ret) if p and p[-1] == "role")
    ledger = {k: [x for x in v["enum"] if x is not None] for k, v in led.get("properties", {}).items()
              if isinstance(v, dict) and "enum" in v}
    # A tool is a file whose entry point is afs_trace.run (tests/test_trace.py enforces it); libraries are not.
    tools = sorted(p.name for p in (HARNESS / "tools").iterdir() if p.is_file() and not p.name.startswith(".")
                   and _is_tool(p.read_text(encoding="utf-8", errors="ignore")))
    no_verdict = {p.name for p in (HARNESS / "tools").iterdir() if p.name in tools
                  and _no_verdict(p.read_text(encoding="utf-8", errors="ignore"))}
    wf = {}
    for p in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
        text = p.read_text(encoding="utf-8")
        if "AI Factory Swarm bootstrap" in text.split("\n", 1)[0]:
            wf[p.name] = yaml.safe_load(text) or {}
            if NO_VERDICT_WF in text:
                no_verdict.add(p.name)
    return {"roles": roles, "role_fields": role_fields(ret), "ledger": ledger, "tools": tools, "workflows": wf,
            "no_verdict": no_verdict}


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


RANK = {True: 2, None: 1, False: 0}
KEPT = pathlib.Path(".migration/evidence/coverage.json")
SIDES = {"tool": ("pass", "fail"), "workflow": ("success", "failure")}


def workflow_runs(repo, name, limit):
    """The latest `limit` runs of a workflow. GitHub pages at 100, so more than 100 takes several requests."""
    size = min(100, limit)             # one page size throughout: GitHub's pages are offsets of per_page
    runs, page = [], 1
    while len(runs) < limit:
        batch = (gh(f"repos/{repo}/actions/workflows/{name}/runs?per_page={size}&page={page}") or {}).get("workflow_runs", [])
        runs += batch
        if len(batch) < size:
            break
        page += 1
    return runs[:limit]


def load_kept(path=KEPT):
    """Evidence earlier runs kept: {path key: {side: reference}}."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in (doc.get("paths") or {}).items() if isinstance(v, dict)}


def save_kept(kept, path=KEPT):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "afs-coverage-evidence/1",
           "note": "Written by harness_coverage.py --keep: the first evidence seen for each side of each tool and "
                   "workflow, kept so it outlives GitHub's recent-runs window (ADR-0027).",
           "paths": {k: dict(sorted(v.items())) for k, v in sorted(kept.items()) if v}}
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def union(files, out_path=None):
    """ADR-0037: a path counts once any target exercised it; each line names the target(s) that did."""
    reports = [json.loads(pathlib.Path(f).read_text(encoding="utf-8")) for f in files]
    keys = sorted({k for r in reports for k in r["paths"]})
    lines, done = ["# Harness coverage across targets\n", "Union of: " + ", ".join(f"`{r.get('repo')}`" for r in reports) + "\n"], 0
    for k in keys:
        entries = [(r.get("repo"), r["paths"][k]) for r in reports if k in r["paths"]]
        best = max((e["ok"] for _, e in entries), key=lambda v: RANK[v])
        by = [repo for repo, e in entries if e["ok"] is True]
        done += best is True
        mark = {True: "✅", None: "⚠️", False: "❌"}[best]
        lines.append(f"- {mark} `{k}`" + (f" (by {', '.join(by)})" if by else ""))
    lines.append(f"\n**{done} of {len(keys)} paths exercised across {len(reports)} target(s); {len(keys) - done} to go.**")
    text = "\n".join(lines) + "\n"
    if out_path:
        pathlib.Path(out_path).write_text(text, encoding="utf-8")
    print(text)
    print(f"AFS-RESULT gate=coverage-union targets={len(reports)} paths={len(keys)} exercised={done} gaps={len(keys) - done}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="owner/repo, for workflow runs and labels")
    ap.add_argument("--runs", type=int, default=60, help="recent runs per workflow to inspect")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--json", help="also write every path's status, by key, for --union")
    ap.add_argument("--union", nargs="+", metavar="JSON", help="combine --json reports of several targets (ADR-0037)")
    ap.add_argument("--keep", action="store_true", help=f"record this run's evidence in {KEPT} (merged, never dropped)")
    a = ap.parse_args(argv)
    if a.union:
        return union(a.union, a.out)
    u = universe()
    out, gaps, total = ["# Harness coverage\n",
                        "Derived from the installed harness; evidence from git history and GitHub (ADR-0027).\n"], [], 0

    paths = {}

    def line(ok, text, key):
        nonlocal total
        total += 1
        mark = {True: "✅", None: "⚠️", False: "❌"}[ok]
        if ok is not True:
            gaps.append(text)
        out.append(f"- {mark} {text}")
        paths[key] = {"ok": ok, "text": text}

    returns = history(".migration/returns")
    ledger = history(".migration/ledger")
    out.append("## Agent roles (a committed return file)\n")
    seen_roles = collections.Counter(r.get("role") for r in returns)
    for role in u["roles"]:
        line(seen_roles[role] > 0, f"`{role}`: {seen_roles[role]} return file version(s)", f"role:{role}")
    out.append("\n## Role-specific values in return files\n")
    for role, fields in sorted(u["role_fields"].items()):
        mine = [r for r in returns if r.get("role") == role]
        for field, values in sorted(fields.items()):
            seen = set().union(*[value_at(r, field) for r in mine]) if mine else set()
            for v in values:
                line(v in seen, f"`{role}` `{field}: {v}`", f"value:{role}:{field}:{v}")
    out.append("\n## Ledger values (any version of any entry)\n")
    for field, values in sorted(u["ledger"].items()):
        seen = set().union(*[value_at(e, field) for e in ledger]) if ledger else set()
        for v in values:
            line(v in seen, f"`{field}: {v}`", f"ledger:{field}:{v}")

    # Tools: pass/fail from journals and workflow steps
    passed, failed, where = collections.defaultdict(int), collections.defaultdict(int), collections.defaultdict(set)
    unconfirmed = collections.defaultdict(int)
    kept = load_kept()
    seen = collections.defaultdict(dict)              # key -> {side: first reference this run saw}

    def saw(key, side, ref):
        seen[key].setdefault(side, ref)

    for gate, code, cmd in journal_rows():
        for t in u["tools"]:
            if re.search(rf"harness/tools/{re.escape(t)}\b", cmd):
                (passed if code == 0 else failed)[t] += 1
                where[t].add("journal")
                saw(f"tool:{t}", "pass" if code == 0 else "fail", f"journal: {gate} (.migration/evidence/runs)")
    latest = {}                                       # one session, one record: the latest snapshot of its log
    for rec in history(".migration/costs"):
        key = rec.get("log") or rec.get("session_id")
        if key not in latest or str(rec.get("recorded_at") or "") >= str(latest[key].get("recorded_at") or ""):
            latest[key] = rec
    for rec in latest.values():                       # agent sessions: the session hook's record (ADR-0027)
        for r in rec.get("harness_tools") or []:
            if r.get("tool") in u["tools"]:
                (passed if r.get("exit") == 0 else failed)[r["tool"]] += r.get("count", 1)
                where[r["tool"]].add("agent session")
                saw(f"tool:{r['tool']}", "pass" if r.get("exit") == 0 else "fail",
                    f"agent session: {rec.get('session_id') or rec.get('log')}")
    steps = step_tools(u["workflows"], u["tools"])
    wf_conclusions = {}
    if not a.offline and a.repo:
        for name in u["workflows"]:
            try:
                runs = workflow_runs(a.repo, name, a.runs)
            except RuntimeError as e:
                if "HTTP 404" not in str(e):
                    raise
                runs = []          # not on the default branch yet (a target mid-setup): no runs, not an error
            wf_conclusions[name] = collections.Counter(r.get("conclusion") for r in runs)
            for run in runs:
                if run.get("conclusion") in ("success", "failure"):
                    saw(f"workflow:{name}", run["conclusion"], run.get("html_url") or f"run {run.get('id')}")
                for job in (gh(f"repos/{a.repo}/actions/runs/{run['id']}/jobs") or {}).get("jobs", []):
                    marks = MARK.findall(gh(f"repos/{a.repo}/actions/jobs/{job['id']}/logs", raw=True))
                    for t, code in marks:          # exact: the tool said it ran, and how it ended
                        if t in u["tools"]:
                            (passed if code == "0" else failed)[t] += 1
                            where[t].add(name)
                            saw(f"tool:{t}", "pass" if code == "0" else "fail",
                                run.get("html_url") or f"{name} run {run.get('id')}")
                    if marks:
                        continue
                    for st in job.get("steps") or []:   # older runs, before AFS-TOOL: the step ran, unconfirmed
                        if st.get("conclusion") in ("success", "failure"):
                            for t in steps.get((name, st.get("name")), []):
                                unconfirmed[t] += 1
                                where[t].add(f"{name}, step only")
    out.append("\n## Harness tools (seen passing and failing)\n")
    def merged(key):
        both = dict(kept.get(key) or {})
        for side, ref in seen[key].items():
            both.setdefault(side, ref)
        return both

    def kept_note(key, sides):
        old = [s for s in sides if s in (kept.get(key) or {}) and s not in seen[key]]
        return "".join(f"; {s} kept: {kept[key][s]}" for s in old)

    for t in u["tools"]:
        p, f = passed[t], failed[t]
        ev = merged(f"tool:{t}")
        hp, hf = bool(p or "pass" in ev), bool(f or "fail" in ev)
        if t in u["no_verdict"]:      # reports, never blocks: seen running is the whole path
            ok = True if hp or hf else (None if unconfirmed[t] else False)
        else:
            ok = True if hp and hf else (None if hp or hf or unconfirmed[t] else False)
        extra = f", step-level only {unconfirmed[t]}" if unconfirmed[t] else ""
        extra += kept_note(f"tool:{t}", SIDES["tool"])
        extra += " · no verdict: seen running is enough" if t in u["no_verdict"] else ""
        line(ok, f"`{t}`: passed {p}, failed {f}{extra}" + (f" ({'; '.join(sorted(where[t]))})" if where[t] else ""),
             f"tool:{t}")
    if wf_conclusions:
        out.append("\n## Generated workflows (recent runs)\n")
        for name, c in sorted(wf_conclusions.items()):
            ev = merged(f"workflow:{name}")
            hs, hf = bool(c.get("success") or "success" in ev), bool(c.get("failure") or "failure" in ev)
            if name in u["no_verdict"]:
                ok = hs or hf
            else:
                ok = True if hs and hf else (None if hs else False)
            line(ok, f"`{name}`: " + (", ".join(f"{k}={v}" for k, v in sorted(c.items(), key=str)) or "never ran")
                 + kept_note(f"workflow:{name}", SIDES["workflow"]), f"workflow:{name}")
        labels = [lb["name"] for lb in gh(f"repos/{a.repo}/labels?per_page=100") or []
                  if lb["name"].startswith(("afs:", "wayfinder:"))]
        out.append("\n## Labels (issues ever labelled)\n")
        for lb in sorted(labels):
            n = len(gh(f"repos/{a.repo}/issues?state=all&labels={lb}&per_page=100") or [])
            line(n > 0, f"`{lb}`: {n} issue(s)", f"label:{lb}")
    if a.keep:
        save_kept({k: merged(k) for k in set(kept) | set(seen)})
    covered = total - len(gaps)
    out.append(f"\n**{covered} of {total} paths exercised; {len(gaps)} to go.**")
    report = "\n".join(out) + "\n"
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({"repo": a.repo, "paths": paths}, indent=1) + "\n", encoding="utf-8")
    if a.out:
        pathlib.Path(a.out).write_text(report, encoding="utf-8")
    print(report)
    print(f"AFS-RESULT gate=coverage paths={total} exercised={covered} gaps={len(gaps)}")
    return 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main, verdict=False)
