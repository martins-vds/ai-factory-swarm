#!/usr/bin/env python3
"""Check a target's slice plans before their tickets are dispatched (harness #98, ADR-0034).

Each `.migration/plan/<slice>.md` has a machine-readable ticket list, `.migration/plan/<slice>.tickets.yaml`
(schemas/plan-tickets.schema.json). Checks, across every plan:

  * every plan has its tickets file, and every tickets file names its plan's slice;
  * ticket ids are unique, and an id isn't already used by another role's return file (a reused id makes
    two roles write one journal and one handoff);
  * every `blocked_by` names a planned ticket.

Over the tickets that are still **open** (no return file for the ticket's own role yet, ADR-0029; a
backfilled ticket that finished before return files existed is marked `done_before_returns`):
  * an implementation ticket (Migrator, Specialist Migrator, Characterizer) names at least one file;
  * two tickets with no blocking path between them don't share a file (the parallel-path rule);
  * a file planned in two slices is listed under `cross_slice` in both plans;
  * a planned test file whose name is also used by another test file in a different folder has that
    folder's `__init__.py` existing or in the ticket's files (pytest can't collect both otherwise);
  * every capability a ticket proves has its `.migration/ledger/<id>.yaml` in the ticket's files;
  * (ADR-0048) a template or static file a ticket plans is under the profile's `graph.target_paths`, so the
    target graph sees the page (synthetic #76);
  * (ADR-0048) a module a ticket `removes` has its importing tests in the ticket's files, or owned by a
    ticket it is blocked by;
  * (ADR-0062) only a Characterizer ticket plans files under `.migration/spec/`: the customer spec is
    written by a role other than the one that builds the code;
  * (ADR-0062) with the profile's `spec.required`, a Migrator ticket that proves a capability is blocked
    by a Characterizer ticket that plans the slice's spec, unless a spec file for the capability exists.

Over each slice whose tickets are all still open (a new plan), ADR-0048:
  * every target anchor in `.migration/slices/<slice>.yaml` (`data_paths.target`, `entry_points.target`) is
    in some ticket's `builds`, so the spec names routes the plan builds (synthetic #77, #89, #99).

With `--issues ISSUES.json` (or `--repo OWNER/NAME`), ADR-0048: the file list of each open ticket's
dispatched issue matches its plan entry; the plan file is the scope, and drift fails (LL-01 #71, LL-04 #107).

The file list is the ticket's whole scope: the finish check (ADR-0034) holds sessions to it.

Usage: check_plan.py <.migration folder> [--schemas <dir>] [--sample] [--issues ISSUES.json | --repo OWNER/NAME]
Run by validate.py; exits 1 on any error.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

import yaml
from jsonschema import Draft202012Validator

HERE = pathlib.Path(__file__).resolve().parent
IMPLEMENTATION = {"afs-migrator", "afs-specialist-migrator", "afs-characterizer"}
# Retired roles stay valid on finished tickets (history is never rewritten); an open ticket can't use one.
RETIRED_ROLES = {"afs-specialist-migrator": "use `role: afs-migrator` and keep `specialty:` (ADR-0042)",
                 "afs-bootstrapper": "the Program Orchestrator prepares the target with the `afs-bootstrap` skill (ADR-0046)",
                 "afs-slice-coordinator": "use `role: afs-program-orchestrator`: it runs the ticket loop and the "
                                          "`afs-slice-acceptance` skill (ADR-0050)"}
# A retired role and the role it folded into are one role for ticket ids: rework of a ticket the retired role
# finished is done by its successor, under the same id (eval fold-r1..r3: BK-05F and BK-05G rework).
FOLDED_INTO = {"afs-specialist-migrator": "afs-migrator", "afs-bootstrapper": "afs-program-orchestrator",
               "afs-slice-coordinator": "afs-program-orchestrator"}
# Roles that work on another role's ticket and keep that ticket's id. The retired Slice Coordinator stays a
# legacy one: its committed returns on other roles' tickets stay valid (ADR-0050).
SHARED_ID_ROLES = {"afs-verifier", "afs-auditor"}
LEGACY_SHARED_ID_ROLES = {"afs-slice-coordinator"}
SPEC_DIR = ".migration/spec/"
SPEC_AUTHOR = "afs-characterizer"
BUILDERS = {"afs-migrator", "afs-specialist-migrator"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", ".source", ".migration", "__pycache__"}


def same_role(role):
    """`role`, plus the retired role it absorbed or the role it folded into (ADR-0042)."""
    return {role, FOLDED_INTO.get(role)} | {old for old, new in FOLDED_INTO.items() if new == role}


def load_plans(folder, schemas, errors):
    """{slice: (path, doc)} for every tickets file that parses and matches the schema."""
    plan_dir = folder / "plan"
    if not plan_dir.is_dir():
        return {}
    validator = Draft202012Validator(json.loads((schemas / "plan-tickets.schema.json").read_text(encoding="utf-8")))
    plans = {}
    for md in sorted(plan_dir.glob("*.md")):
        if not (plan_dir / f"{md.stem}.tickets.yaml").exists():
            errors.append(f"{md}: no {md.stem}.tickets.yaml: list the plan's tickets there "
                          "(schemas/plan-tickets.schema.json)")
    for path in sorted(plan_dir.glob("*.tickets.yaml")):
        slice_name = path.name[: -len(".tickets.yaml")]
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{path}: invalid YAML: {exc}")
            continue
        bad = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
        for err in bad:
            errors.append(f"{path}: {'/'.join(map(str, err.absolute_path)) or '(root)'}: {err.message}")
        if bad:
            continue
        if doc["slice"] != slice_name:
            errors.append(f"{path}: slice must be '{slice_name}' (the file name), not '{doc['slice']}'")
        if not (plan_dir / f"{slice_name}.md").exists():
            errors.append(f"{path}: no plan {slice_name}.md next to it")
        plans[slice_name] = (path, doc)
    return plans


def returns_by_ticket(folder):
    """{ticket: {role}} from the return files' names (`<ticket>.<role>.yaml`)."""
    out = {}
    for path in (folder / "returns").glob("*.y*ml") if (folder / "returns").is_dir() else []:
        ticket, _, role = path.stem.rpartition(".")
        if ticket and role.startswith("afs-"):
            out.setdefault(ticket, set()).add(role)
    return out


def overlaps(a, b):
    """True when two planned paths touch the same file (a path ending in / is a folder)."""
    if a == b:
        return True
    return (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b))


def reachable(tickets):
    """{id: set of ids it depends on, transitively}."""
    edges = {t["id"]: set(t["blocked_by"]) for t in tickets}
    memo = {}

    def walk(tid, seen=()):
        if tid in memo:
            return memo[tid]
        out = set()
        for dep in edges.get(tid, ()):
            if dep in seen:
                continue
            out |= {dep} | walk(dep, seen + (tid,))
        memo[tid] = out
        return out

    return {tid: walk(tid) for tid in edges}


def existing_tests(root):
    """{basename: {folder}} for test files already in the repo."""
    out = {}
    tests = root / "tests"
    if not tests.is_dir():
        return out
    for path in tests.rglob("test_*.py"):
        if SKIP_DIRS.intersection(path.relative_to(root).parts):
            continue
        out.setdefault(path.name, set()).add(path.parent.relative_to(root).as_posix())
    return out


def check(folder, schemas, errors, sample=False):
    """Append every plan error to `errors`; return the number of tickets files checked."""
    folder = pathlib.Path(folder)
    plans = load_plans(folder, pathlib.Path(schemas), errors)
    if not plans:
        return 0
    root = folder.resolve().parent
    tickets, slice_of, where = [], {}, {}
    for name, (path, doc) in plans.items():
        for t in doc["tickets"]:
            if t["id"] in slice_of:
                errors.append(f"{path}: ticket {t['id']} is also planned in {where[t['id']]}")
                continue
            tickets.append(t)
            slice_of[t["id"]], where[t["id"]] = name, path

    returned = returns_by_ticket(folder)
    for t in tickets:
        path = where[t["id"]]
        others = returned.get(t["id"], set()) - same_role(t["role"]) - SHARED_ID_ROLES - LEGACY_SHARED_ID_ROLES
        if others:
            errors.append(f"{path}: ticket id {t['id']} is already used by {', '.join(sorted(others))} "
                          f"(.migration/returns/): pick a new id")
        for dep in t["blocked_by"]:
            if dep not in slice_of:
                errors.append(f"{path}: {t['id']} is blocked by {dep}, which no plan lists")

    for t in tickets:
        if t.get("done_before_returns") and t["role"] in returned.get(t["id"], set()):
            errors.append(f"{where[t['id']]}: {t['id']} has a return file, so drop done_before_returns")
    open_tickets = [t for t in tickets
                    if t["role"] not in returned.get(t["id"], set()) and not t.get("done_before_returns")]
    for t in open_tickets:
        if t["role"] in RETIRED_ROLES:
            errors.append(f"{where[t['id']]}: {t['id']} uses the retired role {t['role']}: "
                          f"{RETIRED_ROLES[t['role']]}")
        if t["role"] in IMPLEMENTATION and not t["files"]:
            errors.append(f"{where[t['id']]}: {t['id']} ({t['role']}) names no files")
    deps = reachable(tickets)

    for i, a in enumerate(open_tickets):
        for b in open_tickets[i + 1:]:
            if b["id"] in deps[a["id"]] or a["id"] in deps[b["id"]]:
                continue
            shared = sorted({max(fa, fb, key=len) for fa in a["files"] for fb in b["files"] if overlaps(fa, fb)})
            if shared:
                errors.append(f"{where[a['id']]}: {a['id']} and {b['id']} both change {', '.join(shared)} "
                              "with no blocking edge between them: add one, or split the file")

    planned_in = {}
    for t in open_tickets:
        for f in t["files"]:
            planned_in.setdefault(f, set()).add(slice_of[t["id"]])
    for f, slices in sorted(planned_in.items()):
        if len(slices) < 2:
            continue
        for name in sorted(slices):
            path, doc = plans[name]
            listed = {s for c in doc.get("cross_slice", []) if c["file"] == f for s in c["slices"]}
            if not slices <= listed:
                errors.append(f"{path}: {f} is planned in slices {', '.join(sorted(slices))}: "
                              "list it under cross_slice with every slice that changes it")

    if not sample:
        tests = existing_tests(root)
        for t in open_tickets:
            for f in t["files"]:
                p = pathlib.PurePosixPath(f)
                if not (p.parts and p.parts[0] == "tests" and p.name.startswith("test_") and p.suffix == ".py"):
                    continue
                folders = set(tests.get(p.name, set()))
                folders |= {pathlib.PurePosixPath(g).parent.as_posix() for o in tickets for g in o["files"]
                            if pathlib.PurePosixPath(g).name == p.name}
                if len(folders - {p.parent.as_posix()}) == 0:
                    continue
                init = f"{p.parent.as_posix()}/__init__.py"
                if not (root / init).exists() and init not in t["files"]:
                    clash = ", ".join(sorted(folders - {p.parent.as_posix()}))
                    errors.append(f"{where[t['id']]}: {t['id']} plans {f}, but {p.name} also exists in {clash}: "
                                  f"add {init} to its files so pytest can collect both")

    for t in open_tickets:
        for cap in t.get("capabilities", []):
            entry = f".migration/ledger/{cap}.yaml"
            if entry not in t["files"]:
                errors.append(f"{where[t['id']]}: {t['id']} proves {cap}: add {entry} to its files")

    check_spec_owner(folder, tickets, open_tickets, slice_of, where, deps, errors)
    check_anchors(folder, plans, returned, errors)
    if not sample:
        check_target_paths(folder, open_tickets, where, errors)
        check_removals(root, tickets, open_tickets, where, deps, errors)
    return len(plans)


def spec_required(folder):
    prof = load_yaml(pathlib.Path(folder) / "profile.yaml") or {}
    return bool((prof.get("spec") or {}).get("required"))


def specced_capabilities(folder):
    """Capabilities with a spec file already committed under `.migration/spec/`."""
    out = set()
    for path in sorted((pathlib.Path(folder) / "spec").glob("*/*.yaml")):
        doc = load_yaml(path)
        if isinstance(doc, dict) and doc.get("capability"):
            out.add(doc["capability"])
    return out


def check_spec_owner(folder, tickets, open_tickets, slice_of, where, deps, errors):
    """ADR-0062: the Characterizer writes the spec, before the Migrator builds what it describes."""
    for t in open_tickets:
        spec_files = [f for f in t["files"] if f.startswith(SPEC_DIR) or SPEC_DIR.startswith(f)]
        if spec_files and t["role"] != SPEC_AUTHOR:
            errors.append(f"{where[t['id']]}: {t['id']} ({t['role']}) plans {', '.join(spec_files)}: only an "
                          f"{SPEC_AUTHOR} ticket writes the customer spec (ADR-0062). Plan a Characterizer "
                          "ticket for it and block this one on it")
    if not spec_required(folder):
        return
    have = specced_capabilities(folder)
    by_id = {t["id"]: t for t in tickets}
    for t in open_tickets:
        if t["role"] not in BUILDERS:
            continue
        missing = [c for c in t.get("capabilities", []) if c not in have]
        if not missing:
            continue
        spec_dir = f"{SPEC_DIR}{slice_of[t['id']]}/"
        writers = [d for d in deps[t["id"]] if by_id.get(d, {}).get("role") == SPEC_AUTHOR
                   and any(overlaps(f, spec_dir) for f in by_id[d]["files"])]
        if not writers:
            errors.append(f"{where[t['id']]}: {t['id']} builds {', '.join(missing)}, which has no spec yet: block "
                          f"it on an {SPEC_AUTHOR} ticket that plans {spec_dir} (profile spec.required, ADR-0062)")


def load_yaml(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def plan_predates_anchors(path, folder):
    """A plan committed before the anchors rule reached this target is exempt (eval cases replay such plans)."""
    try:
        import validate
    except ImportError:
        return False
    return validate.predates_rule(pathlib.Path(path), pathlib.Path(folder), validate.PLAN_ANCHORS_RULE_V1)


def check_anchors(folder, plans, returned, errors):
    """ADR-0048: a new slice's every target anchor is built by one of its tickets (synthetic #77, #89, #99: a
    spec named routes the code never had, and the graph gate failed after the work merged)."""
    for name, (path, doc) in plans.items():
        started = [t for t in doc["tickets"] if t["role"] in returned.get(t["id"], set()) or t.get("done_before_returns")]
        if started or plan_predates_anchors(path, folder):
            continue
        spec = load_yaml(folder / "slices" / f"{name}.yaml")
        anchors = list((spec.get("data_paths") or {}).get("target") or []) + \
            list((spec.get("entry_points") or {}).get("target") or [])
        built = {a for t in doc["tickets"] for a in t.get("builds") or []}
        missing = [a for a in anchors if a not in built]
        if missing:
            errors.append(f"{path}: no ticket builds the slice's target anchor(s) {', '.join(missing)}: list each "
                          f"under the ticket that builds it (`builds:`), exactly as the slice spec writes it")


def check_target_paths(folder, open_tickets, where, errors):
    """ADR-0048: a page a ticket plans is in a folder the target graph analyses (synthetic #76)."""
    graph = (load_yaml(folder / "profile.yaml").get("graph") or {})
    roots = [str(p).rstrip("/") + "/" for p in graph.get("target_paths") or []]
    excluded = [str(p).rstrip("/") + "/" for p in graph.get("target_exclude") or []]
    if not roots:
        return
    for t in open_tickets:
        for f in t["files"]:
            parts = pathlib.PurePosixPath(f).parts
            if not ({"templates", "static"} & set(parts[:-1] if not f.endswith("/") else parts)):
                continue
            if f.startswith((".migration/", "tests/")) or any(f.startswith(x) for x in excluded):
                continue
            if not any(f.startswith(r) for r in roots):
                errors.append(f"{where[t['id']]}: {t['id']} plans {f}, outside the profile's graph.target_paths "
                              f"({', '.join(r.rstrip('/') for r in roots)}): add its folder there (or to "
                              f"graph.target_exclude if it holds no pages), so the target graph sees it")


def check_removals(root, tickets, open_tickets, where, deps, errors):
    """ADR-0048: removing a module breaks the tests that import it unless the ticket (or one it waits for)
    owns them."""
    owner = {f: t["id"] for t in tickets for f in t["files"]}
    for t in open_tickets:
        for f in t.get("removes") or []:
            if f not in t["files"]:
                errors.append(f"{where[t['id']]}: {t['id']} removes {f}: list it in files too")
            p = pathlib.PurePosixPath(f)
            if p.suffix != ".py":
                continue
            names = {".".join(p.with_suffix("").parts)}
            if p.parts and p.parts[0] == "src":
                names.add(".".join(p.with_suffix("").parts[1:]))
            alt = "|".join(map(re.escape, sorted(names)))
            pattern = re.compile(rf"^\s*(?:from\s+(?:{alt})\b|import\s+(?:{alt})\b)", re.M)
            for test in sorted((root / "tests").rglob("*.py")) if (root / "tests").is_dir() else []:
                rel = test.relative_to(root).as_posix()
                if rel in t["files"] or not pattern.search(test.read_text(encoding="utf-8", errors="ignore")):
                    continue
                other = owner.get(rel)
                if other and other in deps[t["id"]]:
                    continue
                errors.append(f"{where[t['id']]}: {t['id']} removes {f}, which {rel} imports: add the test to its "
                              f"files, or block it on the ticket that owns that test")


SCOPE_LINE = re.compile(r"^\s*AFS-SCOPE:\s*`?([^`\s]+)`?\s*$", re.M)
FILES_HEAD = re.compile(r"^\s*[-*]\s*\*\*Files\*\*", re.M)


def issue_files(body):
    """The paths an issue's **Files** list names (backticked, one per bullet under it)."""
    m = FILES_HEAD.search(body or "")
    if not m:
        return None
    out = []
    for line in body[m.end():].splitlines()[1:]:
        if not re.match(r"^\s+[-*]\s", line):
            if line.strip():
                break
            continue
        out += re.findall(r"`([^`\s]+)`", line)
    return out


def check_issue_drift(plans, returned, issues, errors):
    """ADR-0048: the plan file is a ticket's scope; its dispatched issue lists the same files (LL-01 #71,
    LL-04 #107: an issue's list drifted from the plan, and the session followed the issue)."""
    by_ticket = {}
    for i in issues:
        m = re.match(r"^\s*([A-Z][A-Z0-9]*-[0-9A-Z-]+)\s*·", i.get("title") or "")
        if m:
            by_ticket.setdefault(m.group(1), i)
    for name, (path, doc) in plans.items():
        for t in doc["tickets"]:
            if t["role"] in returned.get(t["id"], set()) or t.get("done_before_returns") or t["id"] not in by_ticket:
                continue
            issue = by_ticket[t["id"]]
            listed = issue_files(issue.get("body"))
            if listed is None:
                continue
            extended = set(SCOPE_LINE.findall(issue.get("body") or ""))
            planned = set(t["files"])
            extra = sorted(set(listed) - planned - extended)
            missing = sorted(f for f in planned - set(listed)
                             if not f.startswith((".migration/returns/", ".migration/evidence/")))
            if extra or missing:
                errors.append(f"{path}: {t['id']}'s issue #{issue['number']} lists files that drift from the plan"
                              + (f"; not planned: {', '.join(extra)}" if extra else "")
                              + (f"; planned but not listed: {', '.join(missing)}" if missing else "")
                              + ". The plan is the scope: fix the issue, or the plan through a plan PR")


def unbuilt(folder, schemas=None):
    """{slice: [open implementation ticket ids]} for every slice whose code isn't all merged yet.

    A ticket is done once its own role's return file is on the branch (or `done_before_returns`). The graph
    gate (ADR-0020) holds a slice's target data paths only once its implementation tickets are done."""
    folder = pathlib.Path(folder)
    plans = load_plans(folder, pathlib.Path(schemas) if schemas else _schemas(folder), [])
    returned = returns_by_ticket(folder)
    out = {}
    for name, (_, doc) in plans.items():
        left = [t["id"] for t in doc["tickets"] if t["role"] in IMPLEMENTATION
                and t["role"] not in returned.get(t["id"], set()) and not t.get("done_before_returns")]
        if left:
            out[name] = left
    return out


def _schemas(folder):
    for d in (pathlib.Path(folder) / "harness" / "schemas", HERE.parent / "schemas"):
        if d.is_dir():
            return d
    return HERE.parent / "schemas"


def ticket_files(folder, ticket):
    """The planned file list of one ticket, or None when no plan lists it (used by the finish check)."""
    errors = []
    for _, (_, doc) in load_plans(pathlib.Path(folder), HERE.parent / "schemas", errors).items():
        for t in doc["tickets"]:
            if t["id"] == ticket:
                return list(t["files"])
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--schemas", default=str(HERE.parent / "schemas"))
    ap.add_argument("--sample", action="store_true", help="skip checks that need the target repo's files")
    ap.add_argument("--issues", help="the target's open issues as JSON (title, number, body): check plan drift")
    ap.add_argument("--repo", help="read the open issues from GitHub instead of --issues")
    a = ap.parse_args()
    errors = []
    n = check(a.folder, a.schemas, errors, a.sample)
    if a.issues or a.repo:
        if a.issues:
            issues = json.loads(pathlib.Path(a.issues).read_text(encoding="utf-8"))
        else:
            out = subprocess.run(["gh", "api", "--paginate", f"repos/{a.repo}/issues?state=open&per_page=100"],
                                 capture_output=True, text=True, check=True).stdout
            issues = [i for i in json.loads(out.replace("][", ",")) if "pull_request" not in i]
        check_issue_drift(load_plans(pathlib.Path(a.folder), pathlib.Path(a.schemas), []),
                          returns_by_ticket(pathlib.Path(a.folder)), issues, errors)
    for e in errors:
        print(e, file=sys.stderr)
    print(f"check_plan: {n} plan(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
