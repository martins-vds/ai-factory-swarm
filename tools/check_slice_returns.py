#!/usr/bin/env python3
"""A slice epic closes only when every ticket under it is closed and left its return file (ADR-0024).

The return-contract check (check_return_contract.py) runs on agent pull requests, so work done without a PR
(an agent run locally, a ticket finished by hand) is never checked. The slice epic is where all of a
slice's tickets meet, so this check runs when the epic closes:

  * every sub-issue of the epic is closed (an open ticket means the slice isn't done);
  * every sub-issue closed as completed has a return file, `.migration/returns/<ticket>.<role>.yaml` with
    `issue: <owner>/<repo>#<n>`. A ticket closed as "not planned" needs none.

Tickets closed before this tool was first committed to the repo are exempt (the rule didn't exist yet);
the date comes from git history, so no list can be edited by hand.

  check_slice_returns.py --repo owner/repo --epic 9 [--reopen]   (the AFS map fog workflow runs this)

With --reopen, a failing epic is reopened with a comment that lists what is missing. Exit 1 on failure,
0 otherwise (also when the issue is not a slice epic). Uses `gh api` and git; needs PyYAML.
"""
import argparse
import pathlib
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True       # installed harness files are drift-checked (check_installed.py)
sys.path.insert(0, str(HERE))
import fog_rewalk  # noqa: E402

SELF = ".migration/harness/tools/check_slice_returns.py"


def returned_issues(returns_dir=".migration/returns"):
    """`owner/repo#n` of every committed return file."""
    out = set()
    for p in sorted(pathlib.Path(returns_dir).glob("*.y*ml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and doc.get("issue"):
            out.add(str(doc["issue"]).strip())
    return out


def rule_since(path=SELF):
    """ISO time the rule entered the repo: the commit that first added this tool (None outside git)."""
    r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%cI", "--", path], capture_output=True, text=True)
    dates = r.stdout.split() if r.returncode == 0 else []
    return dates[-1] if dates else None


def utc(iso):
    import datetime
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)


def problems(repo, subs, returned, since):
    """What blocks closing the epic: open tickets, and completed tickets without a return file."""
    out = []
    for s in sorted(subs, key=lambda x: x["number"]):
        ref = f"#{s['number']} {s['title']}"
        if s["state"] != "closed":
            out.append(f"{ref}: still open")
        elif s.get("state_reason") == "completed" and f"{repo}#{s['number']}" not in returned:
            if since and s.get("closed_at") and utc(s["closed_at"]) < utc(since):
                continue
            out.append(f"{ref}: closed as completed, but no `.migration/returns/*.yaml` has "
                       f"`issue: {repo}#{s['number']}`")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--epic", type=int, required=True)
    ap.add_argument("--reopen", action="store_true", help="reopen a failing epic with a comment")
    a = ap.parse_args(argv)
    R = f"repos/{a.repo}"
    epic = fog_rewalk.gh(f"{R}/issues/{a.epic}")
    if not fog_rewalk.is_slice_epic(a.epic, [lbl["name"] for lbl in epic.get("labels", [])]):
        print(f"#{a.epic} is not a slice epic; nothing to check.")
        return 0
    subs, page = [], 1
    while True:
        batch = fog_rewalk.gh(f"{R}/issues/{a.epic}/sub_issues?per_page=100&page={page}") or []
        subs += batch
        if len(batch) < 100:
            break
        page += 1
    since = rule_since()
    found = problems(a.repo, subs, returned_issues(), since)
    print(f"slice epic #{a.epic}: {len(subs)} ticket(s); rule since {since or 'unknown'}")
    for p in found:
        print(f"::error::{p}")
    print(f"AFS-RESULT gate=slice-returns epic={a.epic} verdict={'fail' if found else 'pass'} "
          f"tickets={len(subs)} failures={len(found)}")
    if found and a.reopen and epic.get("state") == "closed":
        body = ("**Reopened by the harness (ADR-0024):** a slice epic closes only when every ticket under it is "
                "closed and left its return file.\n\n" + "\n".join(f"- {p}" for p in found) +
                "\n\nFinish or close the open tickets; for each completed ticket, commit its return file "
                "(`afs-migration-contract` → Durable outputs). Then close this epic again.")
        fog_rewalk.gh(f"{R}/issues/{a.epic}/comments", "-X", "POST", data={"body": body})
        fog_rewalk.gh(f"{R}/issues/{a.epic}", "-X", "PATCH", data={"state": "open"})
        print(f"reopened #{a.epic}")
    return 1 if found else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
