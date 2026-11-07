#!/usr/bin/env python3
"""Validate a migration state folder against the harness schemas.

Usage: validate.py <folder> [--schemas <dir>]

<folder> is a target repo's `.migration/` (or the harness's `templates/migration/`). Checks, when present:
  profile.yaml       → schemas/profile.schema.json
  capabilities.yaml  → schemas/capabilities.schema.json
  slices/*.yaml      → schemas/slice.schema.json (unknown keys are errors)
  ledger/*.yaml      → schemas/ledger-entry.schema.json, plus: file name == `<id>.yaml`, ids unique, and
                       (ADR-0018) every evidence item exists, is committed (never .migration/runs/),
                       and a test id's symbol is still defined
  returns/*.yaml     → schemas/return.schema.json, plus: file name == `<ticket>.<role>.yaml`; and (ADR-0017)
                       a finished return has no null gates, each score equals the last mutation
                       gate run's AFS-RESULT, and PR-bearing roles have a meaningful PR reference
                       (legacy returns and unchanged null-PR history from before this rule are exempt)
  handoffs/*.md      → every `## Handoff — <role> · <UTC>` section has its required subsections
  quirks/*.md        → quirk drafts have Question, Evidence, Impact and Options sections
Exits 1 if anything is invalid. Requires: jsonschema, pyyaml.
"""
import argparse
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

import yaml
from jsonschema import Draft202012Validator, FormatChecker

HERE = pathlib.Path(__file__).resolve().parent
PR_ATTRIBUTION_RULE_V1 = "PR_ATTRIBUTION_RULE_V1"  # Stable history marker for rollout compatibility.


def load_schema(schemas, name):
    schema = json.loads((schemas / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        # YAML 1.1 turns bare dates into datetimes; validate them as the strings they are on disk.
        return json.loads(json.dumps(yaml.safe_load(fh), default=str))


def check(validator, path, errors):
    try:
        doc = load_yaml(path)
    except yaml.YAMLError as exc:
        errors.append(f"{path}: invalid YAML: {exc}")
        return None
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {where}: {err.message}")
    return doc


HANDOFF_PARTS = ["**State:**", "### Done", "### Remaining", "### Blockers / questions", "### Next step for the next session"]
QUIRK_PARTS = ["## Question", "## Evidence", "## Impact", "## Options"]


def check_markdown(folder, errors):
    """Structure checks for agent-written Markdown outputs (afs-handoff, afs-quirk-ticket)."""
    checked = 0
    for path in sorted((folder / "handoffs").glob("*.md")) if (folder / "handoffs").is_dir() else []:
        checked += 1
        text = path.read_text(encoding="utf-8")
        sections = re.split(r"(?m)^## Handoff\b", text)[1:]
        if not sections:
            errors.append(f"{path}: no '## Handoff — <role> · <UTC timestamp>' section")
        for i, sec in enumerate(sections, 1):
            for part in HANDOFF_PARTS:
                if part not in sec:
                    errors.append(f"{path}: handoff section {i} is missing '{part}'")
    for path in sorted((folder / "quirks").glob("*.md")) if (folder / "quirks").is_dir() else []:
        checked += 1
        text = path.read_text(encoding="utf-8")
        for part in QUIRK_PARTS:
            if not re.search(r"(?m)^" + re.escape(part) + r"\s*$", text):
                errors.append(f"{path}: quirk draft is missing '{part}'")
    return checked


SCORE_KEYS = {"mutation_changed", "mutation_full", "mutation_score"}
NOT_RUN = re.compile(r"^n/a: \S")
PR_REFERENCE = re.compile(
    r"^(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*|"
    r"https?://[^/\s?#]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*/?)$")


def roles_with_pr(validator):
    """Roles whose generated return contract contains a PR field."""
    return {
        clause["if"]["properties"]["role"]["const"]
        for clause in validator.schema.get("allOf", [])
        if "pr" in clause.get("then", {}).get("required", [])
    }


def meaningful_pr_reference(value):
    return isinstance(value, str) and PR_REFERENCE.fullmatch(value) is not None


def shallow_history(folder):
    """True when the repository holding `folder` is a shallow clone (history-based checks can't run)."""
    r = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=folder, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def pre_rule_null_pr(path, folder):
    """Keep an unchanged null-PR return that predates this validator rule as historical output."""
    def git(*args):
        result = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    top = git("rev-parse", "--show-toplevel")
    if not top:
        return False
    top = pathlib.Path(top)
    tool_path = pathlib.Path(os.path.relpath(HERE / "validate.py", top))
    return_path = pathlib.Path(os.path.relpath(path.resolve(), top))

    def git_from_top(*args):
        result = subprocess.run(["git", *args], cwd=top, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    if git_from_top("status", "--porcelain", "--", str(return_path)):
        return False
    rule_commit = git_from_top("log", "-1", "--format=%H", "-S", PR_ATTRIBUTION_RULE_V1, "--", str(tool_path))
    return_commit = git_from_top("log", "-1", "--format=%H", "--", str(return_path))
    if not rule_commit or not return_commit or return_commit == rule_commit:
        return False
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", return_commit, rule_commit],
        cwd=top, capture_output=True,
    ).returncode == 0


def cell(text, limit=400):
    """Same escaping afs-run uses for the journal's Command cell."""
    return text.replace("|", "\\|").replace("`", "'").strip()[:limit]


def read_journal(path):
    """Rows of an afs-run journal as dicts, and whether it has the ADR-0017 Result column."""
    rows, has_result = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| UTC |"):
            has_result = line.rstrip().endswith("| Result |")
            continue
        if not line.startswith("| 2"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if len(cells) < 8:
            continue
        rows.append({"gate": cells[1], "exit": cells[2], "command": cells[4].strip("`"),
                     "result": dict(kv.split("=", 1) for kv in cells[7].split() if "=" in kv)})
    return rows, has_result


def gate_commands(profile):
    """Journal Command cells that count as a real gate run: each profile gate command, as run or via bash -c."""
    trusted = set()
    for cmds in (profile.get("gates") or {}).values():
        for cmd in cmds or []:
            trusted.add(cell(cmd))
            trusted.add(cell(shlex.join(["bash", "-c", cmd])))
    return trusted


def scores_in(node, where=""):
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{where}.{k}" if where else k
            if k in SCORE_KEYS and not isinstance(v, (dict, list)):
                yield path, v
            else:
                yield from scores_in(v, path)


def journal_as_of(ret, journal):
    """The journal's rows as they were when the return file was last committed (ADR-0017, amended).

    A ticket's journal is shared: a Verifier's later runs append to the Migrator's. Checked against the
    journal's latest row, a Verifier's failing run invalidated the Migrator's return, and the Verifier then
    edited that return (pilot HR-04C). A return's score must equal the last mutation run *when it was
    written*: the journal at the commit that last changed the return, or now if the return has uncommitted
    changes or there is no git history."""
    def git(*a):
        r = subprocess.run(["git", *a], capture_output=True, text=True, cwd=ret.parent)
        return r.stdout if r.returncode == 0 else None
    top = git("rev-parse", "--show-toplevel")
    if top and not git("status", "--porcelain", "--", ret.name):
        commit = (git("log", "-1", "--format=%H", "--", ret.name) or "").strip()
        if commit:
            rel = os.path.relpath(journal.resolve(), top.strip())
            text = git("show", f"{commit}:{rel}")
            if text is None:
                return []
            tmp = pathlib.Path(tempfile.mkstemp(suffix=".md")[1])
            try:
                tmp.write_text(text, encoding="utf-8")
                return read_journal(tmp)[0]
            finally:
                tmp.unlink()
    return read_journal(journal)[0] if journal.is_file() else []


def check_return_evidence(folder, path, doc, profile, pr_roles, errors):
    """ADR-0017: a finished return reports every gate, and every score matches a gate run's AFS-RESULT."""
    ticket = doc.get("ticket")
    journal = folder / "evidence" / "runs" / f"{ticket}.md"
    rows = journal_as_of(path, journal)
    finished = doc.get("handoff") in (None, "", "none")
    if finished:
        if (doc.get("role") in pr_roles and not meaningful_pr_reference(doc.get("pr")) and
                not (doc.get("pr") is None and pre_rule_null_pr(path, folder))):
            if doc.get("pr") is None and shallow_history(folder):
                errors.append(f"{path}: can't check this return's pre-rule exemption: the clone's history is "
                              "shallow. Run `git fetch --unshallow origin` (afs-setup-check step 2) and re-run; "
                              "don't edit the return")
            else:
                errors.append(f"{path}: finished return requires a meaningful PR reference; fill `pr:` before "
                              "finishing (or record a handoff while work is incomplete)")
        for key, value in (doc.get("gates") or {}).items():
            if value is None:
                errors.append(f"{path}: gates.{key} is null in a finished return; give the value, or "
                              f"'n/a: <reason>' if the gate does not apply (null only with a handoff)")
    trusted = gate_commands(profile or {})
    runs = [r for r in rows if r["command"] in trusted and r["result"].get("gate") == "mutation"]
    for key, value in scores_in(doc):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not runs:
            errors.append(f"{path}: {key}={value} but {journal} has no mutation gate run with a result; run the "
                          f"profile's mutation gate through afs-run")
            continue
        last = runs[-1]["result"].get("score", "")
        try:
            ok = abs(float(last) - float(value)) < 0.0005
        except ValueError:
            ok = False
        if not ok:
            errors.append(f"{path}: {key}={value} does not match the last mutation gate run in {journal} "
                          f"when this return was last committed (score={last}); report the score afs-mutation printed")


UNCOMMITTED = (".migration/runs/",)   # gitignored: raw logs vanish with the session (ADR-0018)
PREFIXED = re.compile(r"^(?P<kind>[a-z][a-z-]*): (?P<ref>.+)$")


def check_evidence(root, path, doc, errors):
    """ADR-0018: every ledger evidence item points at something committed that still exists.

    Forms: `file`, `file::symbol` (a test id; `[params]` ignored), `legacy-test: .source/file::symbol`.
    Paths are relative to the repo root; `.source/` items are checked only when the source checkout
    is present (it is in agent sessions, not in the CI harness job)."""
    for item in doc.get("evidence") or []:
        m = PREFIXED.match(item)
        if m and m.group("kind") != "legacy-test":
            errors.append(f"{path}: evidence '{item}': unknown prefix '{m.group('kind')}:' (only 'legacy-test:')")
            continue
        ref = m.group("ref") if m else item
        file, _, symbol = ref.partition("::")
        if file.startswith(UNCOMMITTED):
            errors.append(f"{path}: evidence '{item}' is a raw log under .migration/runs/, which is never "
                          f"committed; cite the run journal .migration/evidence/runs/<ticket>.md instead")
            continue
        target = root / file
        if file.startswith(".source/") and not (root / ".source").is_dir():
            continue
        if not target.is_file():
            errors.append(f"{path}: evidence '{item}': {file} does not exist")
            continue
        if symbol:
            name = re.sub(r"\[.*\]$", "", symbol.split("::")[-1])
            text = target.read_text(encoding="utf-8", errors="ignore")
            # Language-neutral: `name(` (def/method), or `class/def/function name`.
            if not re.search(rf"\b{re.escape(name)}\s*\(|\b(class|def|function)\s+{re.escape(name)}\b", text):
                errors.append(f"{path}: evidence '{item}': no '{name}' defined in {file} (stale symbol)")


def check_thresholds(path, profile, errors):
    """One source of truth per threshold: a gate command that carries its own limit must match the profile's.
    (Pilot drill: thresholds.crap_max_per_method was 0, but the CRAP gate kept its own `--max 30` and passed.)"""
    limit = (profile.get("thresholds") or {}).get("crap_max_per_method")
    for cmd in (profile.get("gates") or {}).get("crap") or []:
        for value in re.findall(r"crap\.py\b.*?--max[ =]+([0-9.]+)", str(cmd)):
            if limit is None or float(value) != float(limit):
                errors.append(f"{path}: gates.crap runs crap.py --max {value}, but thresholds.crap_max_per_method "
                              f"is {limit}; make them equal (the threshold is the source of truth)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--schemas", default=str(HERE.parent / "schemas"))
    ap.add_argument("--sample", action="store_true",
                    help="harness samples/fixtures: skip checks that need the target repo's files on disk")
    a = ap.parse_args()
    folder, schemas = pathlib.Path(a.folder), pathlib.Path(a.schemas)
    errors, checked = [], 0

    for name, schema in (("profile.yaml", "profile.schema.json"), ("capabilities.yaml", "capabilities.schema.json")):
        if (folder / name).exists():
            check(load_schema(schemas, schema), folder / name, errors)
            if name == "profile.yaml":
                check_thresholds(folder / name, load_yaml(folder / name) or {}, errors)
            checked += 1

    slices = folder / "slices"
    if slices.is_dir():
        validator = load_schema(schemas, "slice.schema.json")
        for path in sorted(slices.glob("*.y*ml")):
            check(validator, path, errors)
            checked += 1

    ledger = folder / "ledger"
    if ledger.is_dir():
        validator = load_schema(schemas, "ledger-entry.schema.json")
        seen = {}
        for path in sorted(ledger.glob("*.y*ml")):
            doc = check(validator, path, errors)
            checked += 1
            if isinstance(doc, dict) and "id" in doc:
                if path.stem != doc["id"]:
                    errors.append(f"{path}: file name must be '{doc['id']}.yaml'")
                if doc["id"] in seen:
                    errors.append(f"{path}: duplicate id '{doc['id']}' (also in {seen[doc['id']]})")
                seen[doc["id"]] = path.name
            if isinstance(doc, dict) and not a.sample:
                check_evidence(folder.resolve().parent, path, doc, errors)

    returns = folder / "returns"
    if returns.is_dir():
        validator = load_schema(schemas, "return.schema.json")
        pr_roles = roles_with_pr(validator)
        profile = load_yaml(folder / "profile.yaml") if (folder / "profile.yaml").exists() else {}
        # Returns committed before ADR-0017, listed once by bootstrap; CI keeps the list unchanged.
        legacy_file = folder / "harness" / "legacy-returns.json"
        legacy = set(json.loads(legacy_file.read_text(encoding="utf-8"))["returns"]) if legacy_file.exists() else set()
        for path in sorted(returns.glob("*.y*ml")):
            doc = check(validator, path, errors)
            checked += 1
            if isinstance(doc, dict) and doc.get("ticket") and path.name not in legacy:
                check_return_evidence(folder, path, doc, profile, pr_roles, errors)
            if isinstance(doc, dict) and "ticket" in doc and "role" in doc:
                want = f"{doc['ticket']}.{doc['role']}"
                if path.stem != want:
                    errors.append(f"{path}: file name must be '{want}.yaml'")

    checked += check_markdown(folder, errors)

    if checked == 0:
        errors.append(f"{folder}: nothing to validate (no profile.yaml, capabilities.yaml or ledger/)")
    for e in errors:
        print(e, file=sys.stderr)
    print(f"{checked} file(s) checked, {len(errors)} error(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
