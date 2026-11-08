#!/usr/bin/env python3
"""A slice's human sign-off is an approving PR review by a named approver (ADR-0031, ADR-0036).

A Slice Coordinator records the human side-by-side check as `human_check: passed` in its return file.
An agent can write that line, so the line alone proves nothing. The sign-off is the approver's own
action: an **approving review**, by a login listed in the profile's `signoff.approvers`, on the exact
head commit of the PR that sets `passed`. A later push makes the approval stale, so the human signs
off on exactly what lands.

  check_signoff.py --repo owner/repo --base origin/main --pr 214      # pull_request / review events
  check_signoff.py --repo owner/repo --range <before>..<after>         # push to the default branch

A return file counts as a new sign-off when it is a Slice Coordinator's, says `human_check: passed`,
and didn't say so before the change. Pull-request mode checks this PR. Push mode finds, for each new
sign-off, the PRs that contain the commit that set it (`commits/{sha}/pulls`), so a merge made with
plain git still needs the approval. With no new sign-off the check passes. Older returns are not
re-judged.

A deferral (`human_check: deferred`, ADR-0036) is a sign-off decision too: it needs the same approval, plus
`human_check_issue` and a `human_check_due` at most 30 days ahead. Every run lists deferrals; one past due
warns, and one more than 30 days past due fails. `--deferrals --comment` (daily schedule) reminds on the issue.

  check_signoff.py --repo owner/repo --deferrals [--comment]

Residual risk (ADR-0031): a session holding the approver's own GitHub login could submit the review.
Agents must never do that; the review is the approver's act alone.
Uses git, PyYAML and `gh api`.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys

import yaml

PROFILE = pathlib.Path(".migration/profile.yaml")
RETURNS = ".migration/returns/"
DECISIVE = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"gh api {path}: {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def approvers(profile_text):
    doc = yaml.safe_load(profile_text or "") or {}
    return [a for a in ((doc.get("signoff") or {}).get("approvers") or []) if a]


SIGNED = ("passed", "deferred")       # a deferral is a sign-off decision too (ADR-0036)
MAX_DEFER_DAYS, FAIL_AFTER_DAYS = 30, 30


def coordinator(text):
    try:
        doc = yaml.safe_load(text or "") or {}
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) and doc.get("role") == "afs-slice-coordinator" else {}


def state(text):
    return coordinator(text).get("human_check")


def passed(text):
    return state(text) == "passed"


def new_signoffs(old_ref, new_ref):
    """Return files whose `human_check` became `passed` or `deferred` (or a deferral changed) in this change."""
    names = (git("diff", "--name-only", "--diff-filter=AM", old_ref, new_ref, "--", RETURNS) or "").split()
    out = []
    for n in names:
        if not n.endswith((".yaml", ".yml")):
            continue
        new, old = coordinator(git("show", f"{new_ref}:{n}")), coordinator(git("show", f"{old_ref}:{n}"))
        if new.get("human_check") not in SIGNED:
            continue
        keys = ("human_check", "human_check_issue", "human_check_due")
        if [new.get(k) for k in keys] != [old.get(k) for k in keys]:
            out.append(n)
    return out


def deferral_problems(doc, today):
    """A deferral names its tracking issue and a due date at most 30 days ahead (ADR-0036)."""
    out = []
    if not str(doc.get("human_check_issue") or "").strip():
        out.append("human_check: deferred needs human_check_issue: the open issue, assigned to an approver, "
                   "that lists what to compare")
    due = parse_date(doc.get("human_check_due"))
    if due is None:
        out.append("human_check: deferred needs human_check_due: YYYY-MM-DD")
    elif (due - today).days > MAX_DEFER_DAYS:
        out.append(f"human_check_due {due} is more than {MAX_DEFER_DAYS} days away")
    return out


def parse_date(value):
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def deferrals(today, returns=RETURNS):
    """(file, doc, days past due) for every deferred human check in the working tree."""
    out = []
    for p in sorted(pathlib.Path(returns).glob("*.y*ml")):
        doc = coordinator(p.read_text(encoding="utf-8"))
        if doc.get("human_check") == "deferred":
            due = parse_date(doc.get("human_check_due"))
            out.append((p.as_posix(), doc, (today - due).days if due else None))
    return out


def report_deferrals(repo, today, comment=False):
    """Warn about every deferral past due; fail one more than 30 days past due; optionally comment daily."""
    failures = 0
    for f, doc, late in deferrals(today):
        issue, due = doc.get("human_check_issue"), doc.get("human_check_due")
        if late is None or late <= 0:
            print(f"{f}: human check deferred until {due} ({issue})")
            continue
        msg = (f"the human side-by-side check for this slice was deferred until {due} and is {late} day(s) "
               f"overdue ({issue}); do it, or renew the deferral on an approved PR (ADR-0036)")
        if late > FAIL_AFTER_DAYS:
            failures += 1
            print(f"::error file={f}::{msg}; more than {FAIL_AFTER_DAYS} days overdue fails this check")
        else:
            print(f"::warning file={f}::{msg}")
        num = str(issue).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if comment and num.isdigit():
            subprocess.run(["gh", "api", f"repos/{repo}/issues/{num}/comments", "-f",
                            f"body=Reminder (harness, ADR-0036): {msg}."], capture_output=True)
    return failures


def approved_by(reviews, logins, head):
    """The approvers whose latest decisive review approves exactly `head`."""
    latest = {}
    for r in reviews:                       # GitHub lists reviews oldest first
        who = (r.get("user") or {}).get("login")
        if who in logins and r.get("state") in DECISIVE:
            latest[who] = r
    return sorted(w for w, r in latest.items() if r["state"] == "APPROVED" and r.get("commit_id") == head)


def check_pr(repo, number, logins):
    pr = gh(f"repos/{repo}/pulls/{number}")
    head = pr["head"]["sha"]
    who = approved_by(gh(f"repos/{repo}/pulls/{number}/reviews?per_page=100") or [], logins, head)
    return who, head


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pr", type=int)
    mode.add_argument("--range", help="<before>..<after> of a push")
    mode.add_argument("--deferrals", action="store_true", help="report deferred human checks (scheduled run)")
    ap.add_argument("--base", help="base ref of the PR (pull-request mode)")
    ap.add_argument("--comment", action="store_true", help="with --deferrals: remind on each overdue issue")
    a = ap.parse_args(argv)
    today = datetime.datetime.now(datetime.timezone.utc).date()
    if a.deferrals:
        return 1 if report_deferrals(a.repo, today, a.comment) else 0
    overdue = report_deferrals(a.repo, today)

    if a.pr:
        if not a.base:
            ap.error("--pr needs --base")
        old, new = git("merge-base", a.base, "HEAD").strip(), "HEAD"
    else:
        old, new = a.range.split("..", 1)
        if set(old) == {"0"}:               # a new branch: nothing before it to compare with
            old = git("rev-list", "--max-parents=0", new).split()[0]
    files = new_signoffs(old, new)
    if not files:
        print("no new human sign-off in this change")
        return 1 if overdue else 0
    logins = approvers(PROFILE.read_text(encoding="utf-8") if PROFILE.exists() else "")
    if not logins:
        print(f"::error::{', '.join(files)} records a human sign-off, but the profile's signoff.approvers lists "
              "nobody. Name who may sign off slices (ADR-0031).")
        return 1
    failures = overdue
    for f in files:
        doc = coordinator(git("show", f"{new}:{f}"))
        if doc.get("human_check") == "deferred":
            for prob in deferral_problems(doc, today):
                failures += 1
                print(f"::error file={f}::{prob} (ADR-0036)")
        if a.pr:
            prs = [a.pr]
        else:
            sha = git("log", "-1", "--format=%H", f"{old}..{new}", "--", f).strip()
            prs = [p["number"] for p in gh(f"repos/{a.repo}/commits/{sha}/pulls") or []]
        ok = []
        for n in prs:
            who, head = check_pr(a.repo, n, logins)
            if who:
                ok.append(f"#{n} by {', '.join(who)} at {head[:7]}")
        if ok:
            print(f"{f}: signed off ({'; '.join(ok)})")
        else:
            failures += 1
            where = f"PR #{prs[0]}" if prs else "a PR (this change was pushed without one)"
            print(f"::error file={f}::human_check: {doc.get('human_check')} needs an approving review on {where} by one of "
                  f"{', '.join(logins)}, on the PR's current head commit. Approving the PR is the sign-off; "
                  "a push after the approval makes it stale (ADR-0031).")
    return 1 if failures else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
