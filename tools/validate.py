#!/usr/bin/env python3
"""Validate a migration state folder against the harness schemas.

Usage: validate.py <folder> [--schemas <dir>]

<folder> is a target repo's `.migration/` (or the harness's `templates/migration/`). Checks, when present:
  profile.yaml       → schemas/profile.schema.json
  capabilities.yaml  → schemas/capabilities.schema.json
  slices/*.yaml      → schemas/slice.schema.json (unknown keys are errors)
  ledger/*.yaml      → schemas/ledger-entry.schema.json, plus: file name == `<id>.yaml`, ids unique, and
                       (ADR-0018) every evidence item exists, is committed (never .migration/runs/),
                       and a test id's symbol is still defined; a migrated entry's target components exist
  returns/*.yaml     → schemas/return.schema.json, plus: file name == `<ticket>.<role>.yaml`; and (ADR-0017)
                       a finished return has no null gates, each score equals the last mutation
                       gate run's AFS-RESULT, and PR-bearing roles have a meaningful PR reference
                       (legacy returns and unchanged null-PR history from before this rule are exempt)
  handoffs/*.md      → every `## Handoff — <role> · <UTC>` section has its required subsections
  quirks/*.md        → quirk drafts have Question, Evidence, Impact and Options sections
  plan/*.md          → each has `<slice>.tickets.yaml` (schemas/plan-tickets.schema.json), checked by
                       check_plan.py: new ids, files named, no shared file without a blocking edge,
                       cross_slice listed, test-name clashes, capability ledger entries (harness #98)
Exits 1 if anything is invalid. Requires: jsonschema, pyyaml.
"""
import argparse
import ast
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

import check_plan
import yaml
from jsonschema import Draft202012Validator, FormatChecker

HERE = pathlib.Path(__file__).resolve().parent
PR_ATTRIBUTION_RULE_V1 = "PR_ATTRIBUTION_RULE_V1"  # Stable history marker for rollout compatibility.
VERIFIER_VERDICT_RULE_V1 = "VERIFIER_VERDICT_RULE_V1"  # Phase 3e: returns committed before this rule are exempt.
VERIFIER_RULES_RULE_V1 = "VERIFIER_RULES_RULE_V1"  # Phase 3e (rules checked): earlier returns are exempt.
LEDGER_RULES_RULE_V1 = "LEDGER_RULES_RULE_V1"  # Phase 3e (rules in the ledger): earlier returns are exempt.
MIGRATOR_SELF_VERIFY_RULE_V1 = "MIGRATOR_SELF_VERIFY_RULE_V1"
PLAN_ANCHORS_RULE_V1 = "PLAN_ANCHORS_RULE_V1"  # ADR-0048 (builds: for target anchors): earlier plans are exempt.  # ADR-0045: earlier Migrator returns are exempt.


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
    return predates_rule(path, folder, PR_ATTRIBUTION_RULE_V1)


def predates_rule(path, folder, marker):
    """An unchanged return whose last commit came before the commit that added `marker` to this validator."""
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
    rule_commit = git_from_top("log", "-1", "--format=%H", "-S", marker, "--", str(tool_path))
    return_commit = git_from_top("log", "-1", "--format=%H", "--", str(return_path))
    if not rule_commit or not return_commit or return_commit == rule_commit:
        return False
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", return_commit, rule_commit],
        cwd=top, capture_output=True,
    ).returncode == 0


VERIFIER_GATES = ("setup", "build", "behavior", "idiom", "crap", "mutation_changed", "regression")


def check_verifier_return(folder, path, doc, errors):
    """Phase 3e: a Verifier's verdict follows its findings, and a serious finding carries evidence.

    - `pass`: no blocker or major finding.
    - `changes-required`: at least one blocker or major finding.
    - `blocked`: only when a gate couldn't run or finish; `blocked_reason` is `<gate>: <why>`.
    - A blocker or major finding has `evidence`: a test id from `tests_added` (a test that shows the defect), or
      `run: <name>`, a failing run of that name in the ticket's journal. Without evidence, it is `minor`.
    - `inherited` (defects from earlier tickets this work depends on, operator ruling 2026-11-17) is reported
      apart: each entry has `where`, `what` and `origin`, and none counts toward the verdict.
    Eval b3c: verdicts contradicted findings (LL-04 r1), and unproven serious findings failed clean work."""
    if doc.get("role") != "afs-verifier" or doc.get("handoff") not in (None, "", "none"):
        return
    verdict = doc.get("verdict")
    findings = [f for f in doc.get("findings") or [] if isinstance(f, dict)]
    serious = [f for f in findings if f.get("severity") in ("blocker", "major")]
    if verdict == "pass" and serious:
        errors.append(f"{path}: verdict pass with {len(serious)} blocker/major finding(s); a pass has none. Use "
                      "changes-required, or downgrade a finding you can't back with evidence to minor")
    if verdict == "changes-required" and not serious:
        errors.append(f"{path}: verdict changes-required with no blocker or major finding; name the defect as a "
                      "major finding with evidence, or the verdict is pass")
    if verdict == "blocked":
        reason = str(doc.get("blocked_reason") or "")
        gate = reason.split(":", 1)[0].strip()
        if gate not in VERIFIER_GATES or not reason.partition(":")[2].strip():
            errors.append(f"{path}: verdict blocked needs `blocked_reason: '<gate>: <why>'` naming the gate that "
                          f"couldn't run or finish ({', '.join(VERIFIER_GATES)}). A defect you found is a "
                          "finding with verdict changes-required, not blocked")
    inherited = doc.get("inherited")
    if inherited is not None and (not isinstance(inherited, list) or not all(
            isinstance(i, dict) and i.get("where") and i.get("what") and i.get("origin") for i in inherited)):
        errors.append(f"{path}: `inherited` lists defects from earlier tickets, each with `where`, `what` and "
                      "`origin` (the ticket that wrote it, or 'unknown')")
    if serious:
        tests = {str(t) for t in doc.get("tests_added") or []}
        journal = folder / "evidence" / "runs" / f"{doc.get('ticket')}.md"
        failed = {r["gate"] for r in journal_as_of(path, journal) if r["exit"] not in ("0", "")}
        for f in serious:
            ev = str(f.get("evidence") or "").strip()
            name = ev[len("run:"):].strip() if ev.startswith("run:") else None
            if not ev:
                problem = "has no `evidence`"
            elif name is not None:
                problem = None if name in failed else f"cites run '{name}', which the journal has no failing run of"
            else:
                problem = None if ev in tests or any(t.startswith(ev) or ev.startswith(t) for t in tests) else \
                    f"cites test '{ev}', which isn't in tests_added"
            if problem:
                errors.append(f"{path}: {f.get('severity')} finding at {f.get('where')} {problem}. Back it with a "
                              "test you added that shows the defect (list it in tests_added and cite its id), or "
                              "`run: <name>` of a failing afs-run in the journal; otherwise it is minor")


def ticket_capabilities(folder, ticket):
    """The capabilities the plan gives a ticket, or None when no plan lists it."""
    for plan in sorted((folder / "plan").glob("*.tickets.yaml")):
        try:
            data = load_yaml(plan) or {}
        except Exception:  # noqa: BLE001 (a broken plan is check_plan's error to report)
            continue
        for t in data.get("tickets") or []:
            if isinstance(t, dict) and t.get("id") == ticket:
                return list(t.get("capabilities") or [])
    return None


def test_exists(repo, test_id):
    """`path::name` (parameters and classes allowed) names a test function in a file of the repository."""
    file, _, rest = str(test_id).partition("::")
    name = rest.split("::")[-1].split("[")[0]
    path = repo / file
    if not file or not name or not path.is_file():
        return False
    return re.search(rf"^\s*(async\s+)?def\s+{re.escape(name)}\s*\(", path.read_text(encoding="utf-8"),
                     re.M) is not None


def check_verifier_rules(folder, path, doc, errors):
    """Phase 3e: the Verifier proves where each business rule is enforced (eval v3h: BK-05F's eligibility rule
    sat in the view, and no run wrote the use-case test that shows it). ADR-0045: the Migrator, which now
    verifies its own work, proves it the same way, and a rule its use case doesn't enforce is its to fix.

    - `rules` lists, for each capability the plan gives the ticket, the business rules it carries: `capability`,
      `rule`, `use_case` (what the test calls), `test` (a test that calls the use case directly, with no view or
      request, using input the rule must refuse) and `enforced` (true when the use case refuses it).
    - A capability with no business rule (a static page) goes in `no_rules: {<capability>: <why>}`.
    - `enforced: false` is a defect in the rule's layer: a blocker or major finding cites that test as evidence.
    - Each test must exist in the repository."""
    if doc.get("role") not in ("afs-verifier", "afs-migrator") or doc.get("handoff") not in (None, "", "none") \
            or doc.get("verdict") == "blocked":
        return
    migrator = doc["role"] == "afs-migrator"
    caps = ticket_capabilities(folder, doc.get("ticket"))
    if caps is None:
        return
    rules = doc.get("rules")
    no_rules = doc.get("no_rules") or {}
    if not isinstance(rules, list) or not isinstance(no_rules, dict):
        errors.append(f"{path}: list `rules` (each business rule the ticket's capabilities carry, with the use-case "
                      "test that shows where it's enforced) and `no_rules: {<capability>: <why>}` for a capability "
                      "with none")
        return
    repo = folder.resolve().parent
    covered = set(no_rules)
    serious_evidence = {str(f.get("evidence") or "").strip() for f in doc.get("findings") or []
                        if isinstance(f, dict) and f.get("severity") in ("blocker", "major")}
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or not all(r.get(k) for k in ("capability", "rule", "use_case", "test")) \
                or not isinstance(r.get("enforced"), bool):
            errors.append(f"{path}: rules[{i}] needs `capability`, `rule`, `use_case`, `test` and `enforced` "
                          "(true or false)")
            continue
        covered.add(r["capability"])
        if not test_exists(repo, r["test"]):
            errors.append(f"{path}: rules[{i}] cites test '{r['test']}', which isn't in the repository; write the "
                          "test that calls the use case directly")
        if r["enforced"] is False and migrator:
            errors.append(f"{path}: rules[{i}] ('{r['rule']}') isn't enforced by {r['use_case']}: move the rule into "
                          "the use case or domain (ADR-0045: no Verifier follows you), keep the test, and set "
                          "`enforced: true`")
        elif r["enforced"] is False and str(r["test"]) not in serious_evidence:
            errors.append(f"{path}: rules[{i}] ('{r['rule']}') isn't enforced by {r['use_case']}: report it as a "
                          f"blocker or major finding with `evidence: {r['test']}`")
    for cap in caps:
        listed = {str(r.get("ledger_rule")) for r in rules if isinstance(r, dict) and r.get("capability") == cap}
        for lr in ledger_rules(folder, cap):
            if lr["id"] not in listed:
                errors.append(f"{path}: the ledger lists rule '{lr['id']}' for {cap} ({lr['rule']}); add it to `rules` "
                              f"with `ledger_rule: {lr['id']}` and a use-case test, enforced or not")
    missing = [c for c in caps if c not in covered]
    if missing:
        errors.append(f"{path}: no rule checked for capability {', '.join(missing)}: add its business rules to "
                      "`rules`, each with a use-case test, or say why it has none under `no_rules`")


def ledger_rules(folder, capability):
    """The `rules` a capability's ledger entry records ([] when none, or when the entry is missing)."""
    entry = folder / "ledger" / f"{capability}.yaml"
    try:
        data = (load_yaml(entry) or {}) if entry.is_file() else {}
    except Exception:  # noqa: BLE001 (a broken entry is the schema check's error to report)
        return []
    return [r for r in data.get("rules") or [] if isinstance(r, dict) and r.get("id")]


def check_migrator_ledger_rules(folder, path, doc, errors):
    """Phase 3e: the Migrator records each capability's business rules in its ledger entry, so the Verifier's
    rule check has a list to cover that it didn't choose itself (eval v3i: BK-05F's Verifiers listed only rules
    the use case enforced; the misplaced one was in no plan or ledger).

    Every capability the plan gives a finished Migrator ticket has a ledger entry with `rules` (each `id` and
    `rule`) or `no_rules: <why>`."""
    if doc.get("role") != "afs-migrator" or doc.get("handoff") not in (None, "", "none"):
        return
    caps = ticket_capabilities(folder, doc.get("ticket"))
    for cap in caps or []:
        entry = folder / "ledger" / f"{cap}.yaml"
        try:
            data = (load_yaml(entry) or {}) if entry.is_file() else None
        except Exception:  # noqa: BLE001
            continue
        if data is None:
            continue                                  # a missing entry is check_return_evidence's to report
        if not data.get("rules") and not data.get("no_rules"):
            errors.append(f"{path}: ledger entry {cap} records no business rules: list each rule the capability "
                          "carries under `rules` (`id`, `rule`, `source`), wherever your code enforces it, or say "
                          "why it has none under `no_rules`")


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


CHANGED_SINCE = re.compile(r"\s--changed-since[ =]\S+")


def gate_commands(profile):
    """Journal Command cells that count as a real gate run: each profile gate command, as run or via bash -c.
    An afs-mutation run counts with or without `--changed-since <ref>`: the base it diffed against was the
    profile's choice then, and dropping the flag (harness #211) mustn't untrust the journals before it."""
    trusted = set()
    for cmds in (profile.get("gates") or {}).values():
        for cmd in cmds or []:
            forms = {cmd}
            if "afs-mutation" in cmd:
                bare = CHANGED_SINCE.sub("", cmd)
                forms |= {bare, bare.replace("afs-mutation", "afs-mutation --changed-since origin/main", 1)}
            for form in forms:
                trusted.add(cell(form))
                trusted.add(cell(shlex.join(["bash", "-c", form])))
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
    # A ticket's journal is shared by its sessions (migrator, Verifier, fixes, re-verification); each session's
    # afs-setup-check writes a `setup-probe` row first. A return's score is the last mutation run of one
    # session. When a squash merge lands a migrator's return and a later Verifier session's rows in one
    # commit (synthetic LL-03, #88), the file's last run is the Verifier's, not the migrator's.
    finals, session_last = [], None
    for r in rows:
        if r["gate"] == "setup-probe" and session_last is not None:
            finals.append(session_last)
            session_last = None
        if r in runs:
            session_last = r
    if session_last is not None:
        finals.append(session_last)
    for key, value in scores_in(doc):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not runs:
            errors.append(f"{path}: {key}={value} but {journal} has no mutation gate run with a result; run the "
                          f"profile's mutation gate through afs-run")
            continue

        def same(run):
            try:
                return abs(float(run["result"].get("score", "")) - float(value)) < 0.0005
            except ValueError:
                return False
        if not any(same(run) for run in finals):
            last = runs[-1]["result"].get("score", "")
            errors.append(f"{path}: {key}={value} does not match the last mutation gate run of any session in "
                          f"{journal} when this return was last committed (latest score={last}); report the score "
                          f"afs-mutation printed")


TIER_B_ATTEMPT = re.compile(r"^(ran|no code): \S")


def check_tier_attempt(path, doc, errors):
    """ADR-0005: tier C only after the tier-B recipe was tried. A build that fails on a private dependency is
    exactly the case tier B exists for, so `tier_b_attempt` must show the compile-only run and its result,
    or say there is no code to compile. ADR-0046: the proof lives in `capabilities.yaml`'s
    `characterization`; a retired Bootstrapper's return carrying it is still checked."""
    if pathlib.Path(path).name == "capabilities.yaml":
        doc = {"role": "afs-bootstrapper", "characterization_tier": (doc.get("characterization") or {}).get("tier"),
               "tier_b_attempt": (doc.get("characterization") or {}).get("tier_b_attempt")}
    if doc.get("role") != "afs-bootstrapper" or doc.get("characterization_tier") != "C":
        return
    attempt = doc.get("tier_b_attempt")
    if not isinstance(attempt, str) or not TIER_B_ATTEMPT.match(attempt.strip()):
        errors.append(f"{path}: characterization tier C needs `tier_b_attempt: \"ran: <compile-only command> -> "
                      f"<result>\"` (the tier-B recipe: compile only what the source's tests reach) or "
                      f"`\"no code: <what the source contains>\"`. A failed full build is not enough "
                      f"(afs-migration-contract -> references/characterization.md)")


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


def resolve_component(root, ref):
    """None when a ledger `target.components` entry names something that exists, else why it doesn't.

    Forms: a repo path (`templates/booking/wizard/`, a file or folder); a dotted Python name, with or
    without the `src.` source folder (`src.loans.services.LoanApplication.lend`); a dotted template name
    (`templates.tracking.result` for `templates/tracking/result.html`)."""
    if any(c.isspace() for c in ref.strip()):
        return None                                               # prose (a library, a service), not a reference
    if "/" in ref:
        file, _, symbol = re.split(r"::?", ref, maxsplit=1)[0], None, (re.split(r"::?", ref, maxsplit=1)[1:] or [""])[0]
        target = root / file
        if not target.exists():
            return f"{file} does not exist"
        if symbol and target.is_file() and not re.search(
                rf"\b{re.escape(symbol)}\s*\(|\b(class|def|function)\s+{re.escape(symbol)}\b",
                target.read_text(encoding="utf-8", errors="ignore")):
            return f"no '{symbol}' defined in {file}"
        return None
    parts = ref.split(".")
    for base in ("", "src/"):
        for k in range(len(parts), 0, -1):
            stem = root / (base + "/".join(parts[:k]))
            rest = parts[k:]
            module = next((f for f in (stem.with_suffix(".py"), stem / "__init__.py") if f.is_file()), None)
            if module is None and rest and stem.is_file():               # a file's target: `Makefile.run`
                text = stem.read_text(encoding="utf-8", errors="ignore")
                return None if re.search(rf"^{re.escape(rest[-1])}\s*:", text, re.M) or \
                    re.search(rf"\b{re.escape(rest[-1])}\b", text) else f"no '{rest[-1]}' in {stem.relative_to(root)}"
            if module is None and not rest and stem.parent.is_dir():
                if stem.is_dir() or any(f.stem == stem.name for f in stem.parent.iterdir() if f.is_file()):
                    return None                                   # a package folder, or a template by stem
            if module is None:
                continue
            body = ast.parse(module.read_text(encoding="utf-8", errors="ignore")).body
            for name in rest:
                found = next((n for n in body if getattr(n, "name", None) == name or any(
                    getattr(t, "id", None) == name for t in getattr(n, "targets", [getattr(n, "target", None)]))),
                    None)
                if found is None:
                    return f"no '{name}' in {module.relative_to(root)}"
                body = getattr(found, "body", [])
            return None
    return f"no module, package or file for '{ref}'"


def check_components(root, path, doc, errors):
    """ADR-0018 amendment: a migrated entry's `target.components` name code that exists. A refactor that
    moves code (synthetic LL-02 put its use cases behind ports) fails here, on its own PR, instead of at the
    slice audit (LC-AUDIT found two stale references)."""
    if doc.get("status") != "migrated":
        return
    for ref in (doc.get("target") or {}).get("components") or []:
        problem = resolve_component(root, ref)
        if problem:
            errors.append(f"{path}: target component '{ref}': {problem} (stale reference)")


def check_thresholds(path, profile, errors):
    """One source of truth per threshold: a gate command that carries its own limit must match the profile's.
    (Pilot drill: thresholds.crap_max_per_method was 0, but the CRAP gate kept its own `--max 30` and passed.)"""
    limit = (profile.get("thresholds") or {}).get("crap_max_per_method")
    for cmd in (profile.get("gates") or {}).get("crap") or []:
        for value in re.findall(r"crap\.py\b.*?--max[ =]+([0-9.]+)", str(cmd)):
            if limit is None or float(value) != float(limit):
                errors.append(f"{path}: gates.crap runs crap.py --max {value}, but thresholds.crap_max_per_method "
                              f"is {limit}; make them equal (the threshold is the source of truth)")


def check_mutation_base(path, profile, errors):
    """gates.mutation_changed lets afs-mutation take its base from $AFS_BASE, which CI sets to the PR's base. A
    hardcoded `--changed-since origin/main` mutates a stacked PR's parent too, and on the eval repo (whose
    `main` is unrelated history) the whole codebase: eval 4f's pilot Gates ran 76 minutes or hit the timeout."""
    for cmd in (profile.get("gates") or {}).get("mutation_changed") or []:
        if re.search(r"afs-mutation\b.*--changed-since", str(cmd)):
            errors.append(f"{path}: gates.mutation_changed passes --changed-since; drop it so afs-mutation diffs "
                          f"against $AFS_BASE (CI sets it to the PR's base), falling back to origin/main")


def check_layering_gate(path, profile, errors):
    """A profile with layer contracts or UI checks runs them: without the tool in gates.idiom, they check nothing."""
    idiom = (profile.get("gates") or {}).get("idiom") or []
    for key, tool in (("layering", "check_layers.py"), ("ui_checks", "check_ui.py")):
        if profile.get(key) and not any(tool in str(cmd) for cmd in idiom):
            errors.append(f"{path}: `{key}` is set but gates.idiom doesn't run it; add "
                          f"`python .migration/harness/tools/{tool}`")


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
                check_layering_gate(folder / name, load_yaml(folder / name) or {}, errors)
                check_mutation_base(folder / name, load_yaml(folder / name) or {}, errors)
            else:
                check_tier_attempt(folder / name, load_yaml(folder / name) or {}, errors)
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
                check_components(folder.resolve().parent, path, doc, errors)

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
                check_tier_attempt(path, doc, errors)
                if not predates_rule(path, folder, VERIFIER_VERDICT_RULE_V1):
                    check_verifier_return(folder, path, doc, errors)
                marker = MIGRATOR_SELF_VERIFY_RULE_V1 if doc.get("role") == "afs-migrator" else VERIFIER_RULES_RULE_V1
                if not predates_rule(path, folder, marker):
                    check_verifier_rules(folder, path, doc, errors)
                if not predates_rule(path, folder, LEDGER_RULES_RULE_V1):
                    check_migrator_ledger_rules(folder, path, doc, errors)
            if isinstance(doc, dict) and "ticket" in doc and "role" in doc:
                want = f"{doc['ticket']}.{doc['role']}"
                if path.stem != want:
                    errors.append(f"{path}: file name must be '{want}.yaml'")

    checked += check_markdown(folder, errors)
    before = len(errors)
    checked += check_plan.check(folder, schemas, errors, a.sample)
    # check_plan runs inside validate.py, so announce its own verdict for harness coverage (ADR-0027)
    print(f"AFS-TOOL check_plan.py exit={1 if len(errors) > before else 0}", file=sys.stderr)

    if checked == 0:
        errors.append(f"{folder}: nothing to validate (no profile.yaml, capabilities.yaml or ledger/)")
    for e in errors:
        print(e, file=sys.stderr)
    print(f"{checked} file(s) checked, {len(errors)} error(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
