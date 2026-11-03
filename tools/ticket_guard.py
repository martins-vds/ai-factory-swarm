#!/usr/bin/env python3
"""Reopen a ticket that closed before its work reached the default branch (ADR-0029).

GitHub closes an issue when a PR that says "Fixes #N" merges, and it also closes the issues of a whole
stack when a PR merges into another PR's branch (pilot HR-04C: merging a Verifier PR into the work branch
closed the work ticket while the work PR was still open). A closed ticket is read as done: its blockers
lift, and the slice-epic check counts it. So when a ticket closes as completed while an **open PR into the
default branch** still says it fixes, closes or resolves that ticket, the ticket is reopened, with a
comment naming the PR. Closing as "not planned", or with no such PR, is left alone.

  ticket_guard.py --repo owner/repo --issue 129        (the AFS ticket guard workflow runs this)

Uses `gh api`. Exit 0 (reopened or not); 1 only if the API fails.
"""
import argparse
import json
import re
import subprocess
import sys

CLOSES = r"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#{n}\b"


def gh(*args, data=None):
    cmd = ["gh", "api", *args] + (["--input", "-"] if data is not None else [])
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"gh api {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def open_fixers(pulls, number):
    """Open PRs whose description says they fix, close or resolve issue #number."""
    pat = re.compile(CLOSES.format(n=number))
    return [p for p in pulls if p.get("state") == "open" and pat.search(p.get("body") or "")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--issue", type=int, required=True)
    a = ap.parse_args(argv)
    R = f"repos/{a.repo}"
    issue = gh(f"{R}/issues/{a.issue}")
    if issue.get("pull_request") or issue.get("state") != "closed" or issue.get("state_reason") != "completed":
        print(f"#{a.issue}: not a ticket closed as completed; nothing to do")
        return 0
    default = gh(R)["default_branch"]
    pulls, page = [], 1
    while True:
        batch = gh(f"{R}/pulls?state=open&base={default}&per_page=100&page={page}") or []
        pulls += batch
        if len(batch) < 100:
            break
        page += 1
    fixers = open_fixers(pulls, a.issue)
    if not fixers:
        print(f"#{a.issue}: no open PR into {default} fixes it; closed stays closed")
        return 0
    links = ", ".join(f"#{p['number']}" for p in fixers)
    gh(f"{R}/issues/{a.issue}", "-X", "PATCH", data={"state": "open"})
    gh(f"{R}/issues/{a.issue}/comments", "-X", "POST", data={"body": (
        f"**Reopened by the harness (ADR-0029):** this ticket closed while {links} (into `{default}`), which "
        f"fixes it, is still open. A ticket is done when its work reaches `{default}`; it will close when "
        f"{links} merges.")})
    print(f"#{a.issue}: reopened; open fixing PR(s) into {default}: {links}")
    return 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
