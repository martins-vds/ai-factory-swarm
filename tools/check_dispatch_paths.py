#!/usr/bin/env python3
"""Parallel-dispatch path check (ADR-0047): no two pieces of concurrent work own the same file, and no new
module shares a dotted name with an existing one.

  check_dispatch_paths.py --tickets LL-07,LL-08 [--root .] [--open-prs PRS.json | --repo OWNER/NAME]
  check_dispatch_paths.py --pr N --repo OWNER/NAME [--root .]          (CI: this PR against the other open PRs)

Work is a ticket (its plan `files`, `.migration/plan/*.tickets.yaml`) or an open PR (the files it changes).
It fails when:
  * **a file is owned twice**: two tickets dispatched together, or a ticket and an open PR, or (CI) this PR
    and another open PR, both list or change the same path. Each session's own records (`.migration/returns/`,
    `runs/`, `evidence/`, `handoffs/`, `costs/`) don't count: they are per ticket by name.
  * **a dotted name is shadowed**: a path one piece of work creates makes a package `x/` where a module
    `x.py` exists (on the base tree or in other work), or the other way round. Python imports one of them and
    silently drops the other (pilot, 2026-11: a package shadowed a module of the same name).

Exit 0 clean, 1 conflicts (each named), 2 usage or API error. Standard library plus PyYAML and gh.
"""
import argparse
import json
import pathlib
import subprocess
import sys

import yaml

OWN_RECORDS = (".migration/returns/", ".migration/runs/", ".migration/evidence/", ".migration/handoffs/",
               ".migration/costs/")


def plan_files(root):
    """{ticket: [files]} from every plan file."""
    out = {}
    for f in sorted((pathlib.Path(root) / ".migration" / "plan").glob("*.tickets.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for t in doc.get("tickets") or []:
            out[t["id"]] = list(t.get("files") or [])
    return out


def gh(path):
    r = subprocess.run(["gh", "api", "--paginate", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {path}: {r.stderr.strip()}")
    return json.loads(r.stdout.replace("][", ",")) if r.stdout.strip() else []


def open_pr_files(repo, prs=None, skip=None):
    """{"#N": [changed files]} for the open PRs (or the given PR list), except `skip`."""
    prs = prs if prs is not None else gh(f"repos/{repo}/pulls?state=open&per_page=100")
    out = {}
    for p in prs:
        if p["number"] == skip:
            continue
        files = p.get("files")
        if files is None:
            files = [f["filename"] for f in gh(f"repos/{repo}/pulls/{p['number']}/files?per_page=100")]
        out[f"#{p['number']}"] = files
    return out


def stack_of(repo, number, prs=None):
    """{"#N"} for the PRs in the same stack as `number` (below or above it): a stacked PR shares its base
    PR's files by design, so they aren't concurrent work."""
    prs = prs if prs is not None else gh(f"repos/{repo}/pulls?state=open&per_page=100")
    by_number = {p["number"]: p for p in prs}
    if number not in by_number:
        by_number[number] = gh(f"repos/{repo}/pulls/{number}")
    linked, frontier = {number}, [number]
    while frontier:
        p = by_number[frontier.pop()]
        for q in by_number.values():
            if q["number"] not in linked and (q["head"]["ref"] == p["base"]["ref"] or q["base"]["ref"] == p["head"]["ref"]):
                linked.add(q["number"])
                frontier.append(q["number"])
    return {f"#{n}" for n in linked}


def counted(path):
    return not path.startswith(OWN_RECORDS)


def dotted(path):
    """The dotted names a .py path defines: `a/b.py` → module a.b; `a/b/__init__.py` (or any file under a/b/)
    → package a.b (and its parents)."""
    p = pathlib.PurePosixPath(path)
    if p.suffix != ".py":
        return set(), set()                            # only Python files make packages and modules
    modules = set() if p.name == "__init__.py" else {".".join(p.with_suffix("").parts)}
    return modules, {".".join(p.parts[:i]) for i in range(1, len(p.parts))}


def conflicts(work, base_files=(), focus=None):
    """[message] for a path owned twice, or a module and package sharing a dotted name. With `focus`, only
    the conflicts that involve that piece of work (CI checks one PR, not the others among themselves)."""
    out, owners = [], {}
    for who, files in work.items():
        for f in filter(counted, files):
            owners.setdefault(f, [])
            if who not in owners[f]:
                owners[f].append(who)
    for f, who in owners.items():
        if len(who) > 1 and (focus is None or focus in who):
            out.append(f"`{f}` is owned by both {who[0]} and {who[1]}" if focus is None or who[0] == focus
                       else f"`{f}` is owned by both {focus} and {next(w for w in who if w != focus)}")
    modules, packages = {}, {}
    for who, files in [("main", list(base_files))] + list(work.items()):
        for f in files:
            m, p = dotted(f)
            for name in m:
                modules.setdefault(name, (who, f))
            for name in p:
                packages.setdefault(name, (who, f))
    for name in sorted(set(modules) & set(packages)):
        (mw, mf), (pw, pf) = modules[name], packages[name]
        if mw == "main" and pw == "main":
            continue                                   # already on main: not this dispatch's doing
        if focus is not None and focus not in (mw, pw):
            continue
        out.append(f"`{name}` is both a module (`{mf}`, {mw}) and a package (under `{pf}`, {pw}): one shadows "
                   f"the other on import; rename one")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tickets", help="comma-separated ticket ids to dispatch together")
    ap.add_argument("--pr", type=int, help="CI: check this PR against the other open PRs")
    ap.add_argument("--repo")
    ap.add_argument("--open-prs", help="open PRs as JSON, each with `number` and optional `files`")
    ap.add_argument("--root", default=".")
    a = ap.parse_args(argv)
    if bool(a.tickets) == bool(a.pr) or (a.pr and not a.repo):
        ap.error("give --tickets, or --pr with --repo")
    try:
        prs = json.loads(pathlib.Path(a.open_prs).read_text()) if a.open_prs else None
        others = open_pr_files(a.repo, prs) if (a.repo or prs is not None) else {}
        if a.tickets:
            plan = plan_files(a.root)
            missing = [t for t in a.tickets.split(",") if t not in plan]
            if missing:
                ap.error(f"no plan lists {', '.join(missing)}")
            work = {t: plan[t] for t in a.tickets.split(",")}
        else:
            same_stack = stack_of(a.repo, a.pr, prs)
            others = {k: v for k, v in others.items() if k not in same_stack}
            work = {f"#{a.pr}": [f["filename"] for f in gh(f"repos/{a.repo}/pulls/{a.pr}/files?per_page=100")]}
        work.update(others)
        base = subprocess.run(["git", "-C", a.root, "ls-files"], capture_output=True, text=True).stdout.split()
    except (RuntimeError, OSError, ValueError) as e:
        print(f"::error title=Dispatch path check failed::{e}")
        return 2
    found = conflicts(work, base, focus=f"#{a.pr}" if a.pr else None)
    for msg in found:
        print(f"::error title=Dispatch paths::{msg}")
    print(f"AFS-RESULT gate=dispatch-paths work={len(work)} conflicts={len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import afs_trace
    afs_trace.run(main)
