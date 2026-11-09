#!/usr/bin/env python3
"""Migrator work merges into the default branch only after its Verifier passes it (ADR-0040).

  python .migration/harness/tools/check_verified_merge.py --base origin/<default branch>

For every `.migration/returns/<T>.afs-migrator.yaml` or `<T>.afs-specialist-migrator.yaml` that this PR
adds or changes against --base, `.migration/returns/<T>.afs-verifier.yaml` must, at HEAD:
  - be a valid Verifier return for ticket T with verdict `pass`;
  - have been committed after the migrator return's latest change, by a different commit: the latest
    commit that changed the Verifier return descends from the latest commit that changed the migrator
    return. A migrator re-run after verification needs a fresh verification.

PRs into any other branch (a Verifier's PR into the migrator's branch, a stacked PR) are out of scope:
the rule applies where work reaches the default branch. Exit 0 pass or out of scope, 1 fail, 2 usage.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIGRATOR = re.compile(r"^\.migration/returns/(?P<ticket>[^/]+)\.(?P<role>afs-migrator|afs-specialist-migrator)\.yaml$")


def git(*args, root="."):
    return subprocess.run(["git", "-C", root, "--no-replace-objects", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def changed_migrator_returns(base, root="."):
    names = git("diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD", "--", ".migration/returns/", root=root)
    return [(m["ticket"], m.group(0)) for m in map(MIGRATOR.match, names.splitlines()) if m]


def last_change(path, root="."):
    return git("log", "-1", "--format=%H", "HEAD", "--", path, root=root)


def problems_for(ticket, migrator_path, root="."):
    from ticket_guard import _role_outcome_problem, _valid_return
    verifier_path = f".migration/returns/{ticket}.afs-verifier.yaml"
    shown = subprocess.run(["git", "-C", root, "--no-replace-objects", "show", f"HEAD:{verifier_path}"],
                           capture_output=True, text=True)
    if shown.returncode != 0:
        return [f"{ticket}: no Verifier return {verifier_path}; verify this work before it merges"]
    doc = _valid_return(shown.stdout, verifier_path)
    if doc is None:
        return [f"{ticket}: {verifier_path} is not a valid return"]
    problems = []
    if doc.get("role") != "afs-verifier" or str(doc.get("ticket")) != ticket:
        problems.append(f"{ticket}: {verifier_path} must be the afs-verifier return for ticket {ticket}")
    outcome = _role_outcome_problem(doc)
    if outcome:
        problems.append(f"{ticket}: Verifier hasn't passed it: {outcome}")
    migrated, verified = last_change(migrator_path, root), last_change(verifier_path, root)
    ancestor = subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", migrated, verified],
                              capture_output=True).returncode == 0
    if verified == migrated or not ancestor:
        problems.append(f"{ticket}: {migrator_path} changed at {migrated[:7]}, after (or with) the Verifier "
                        f"return's latest change {verified[:7]}; re-verify the current work")
    return problems


def check(base, root="."):
    tickets = changed_migrator_returns(base, root)
    problems = [p for ticket, path in tickets for p in problems_for(ticket, path, root)]
    return tickets, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="the default branch, e.g. origin/main")
    ap.add_argument("--pr-base", help="this PR's base branch; out of scope unless it is the default branch")
    ap.add_argument("--default-branch", help="the repository's default branch")
    a = ap.parse_args(argv)
    if a.pr_base and a.default_branch and a.pr_base != a.default_branch:
        print(f"PR targets {a.pr_base}, not {a.default_branch}: out of scope (ADR-0040)")
        print("AFS-RESULT gate=verified-merge verdict=pass tickets=0 failures=0")
        return 0
    try:
        tickets, problems = check(a.base)
    except subprocess.CalledProcessError as exc:
        print(f"::error title=Verified merge::git failed: {exc.stderr.strip() or exc}; fetch full history and retry")
        return 2
    for problem in problems:
        print(f"::error title=Migrator work is not verified::{problem}")
    for ticket, _ in tickets:
        if not any(p.startswith(f"{ticket}:") for p in problems):
            print(f"{ticket}: verified by its passing Verifier return")
    print(f"AFS-RESULT gate=verified-merge verdict={'fail' if problems else 'pass'} "
          f"tickets={len(tickets)} failures={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
