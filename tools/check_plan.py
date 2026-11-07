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
  * every capability a ticket proves has its `.migration/ledger/<id>.yaml` in the ticket's files.

The file list is the ticket's whole scope: the finish check (ADR-0034) holds sessions to it.

Usage: check_plan.py <.migration folder> [--schemas <dir>] [--sample]
Run by validate.py; exits 1 on any error.
"""
import argparse
import json
import pathlib
import sys

import yaml
from jsonschema import Draft202012Validator

HERE = pathlib.Path(__file__).resolve().parent
IMPLEMENTATION = {"afs-migrator", "afs-specialist-migrator", "afs-characterizer"}
# Roles that work on another role's ticket and keep that ticket's id.
SHARED_ID_ROLES = {"afs-verifier", "afs-slice-coordinator", "afs-auditor"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", ".source", ".migration", "__pycache__"}


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
        others = returned.get(t["id"], set()) - {t["role"]} - SHARED_ID_ROLES
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
    return len(plans)


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
    a = ap.parse_args()
    errors = []
    n = check(a.folder, a.schemas, errors, a.sample)
    for e in errors:
        print(e, file=sys.stderr)
    print(f"check_plan: {n} plan(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
