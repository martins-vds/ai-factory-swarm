#!/usr/bin/env python3
"""Write a slice epic's ticket-reconciliation file from the evidence the check computes (ADR-0049, amends
ADR-0030).

  reconcile_epic.py --repo OWNER/NAME --epic N [--out PATH] [--dry-run]

Run in a clone of the target on its default branch, with full history. For every work issue under the epic
(`ticket_guard.descendants`), it writes one disposition to `.migration/evidence/ticket-reconciliation/<N>.yaml`:

* **completed:** an issue closed as completed. Each merged PR the issue's timeline cross-references is paired
  with each `.migration/returns/` file it changed, and `ticket_guard.completed_evidence_problems` (the function
  the reconciliation check runs) decides which pairs are this issue's evidence. So the writer and the check
  can't disagree.
* **superseded:** an issue closed as not planned. The replacement and the failed PR can't be proven from the
  timeline alone, so the entry is written with `needs_review`.
* **retained-open:** an open issue. Its outstanding work and blocker are a person's call, so the entry is
  written with `needs_review`.

An entry the writer couldn't prove carries `needs_review: <why>`, and its missing fields are left empty, so
`ticket_guard.py --reconcile-epic` fails until a person reviews and fills them in. Nothing is guessed. Review
the file, then commit it. Exit 0 when every entry is proven, 1 when any needs review, 2 on a usage or API error.
"""
import argparse
import pathlib
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ticket_guard as tg  # noqa: E402


def landing_prs(repo, number, gh=None):
    """Merged PRs that the issue's timeline cross-references."""
    gh = gh or tg.gh
    out = []
    for n in tg._issue_pull_references(repo, number):
        pull = gh(f"repos/{repo}/pulls/{n}")
        if isinstance(pull, dict) and pull.get("merged_at"):
            out.append(n)
    return out


def changed_returns(repo, prs, gh=None):
    gh = gh or tg.gh
    found = []
    for n in prs:
        page = 1
        while True:
            files = gh(f"repos/{repo}/pulls/{n}/files?per_page=100&page={page}") or []
            found += [f["filename"] for f in files if f.get("filename", "").startswith(".migration/returns/")
                      and f.get("status") != "removed"]
            if len(files) < 100:
                break
            page += 1
    return sorted(set(found))


def disposition(repo, number, issue, prove=None):
    """One reconciliation entry for an issue, and whether a person must review it."""
    prove = prove or tg.completed_evidence_problems
    state, reason = issue.get("state"), issue.get("state_reason")
    if state == "open":
        return {"number": number, "disposition": "retained-open", "outstanding": "", "blocker": "",
                "needs_review": "open issue: write the work still outstanding and what blocks it"}, True
    if reason == "not_planned":
        return {"number": number, "disposition": "superseded", "replacement": None,
                "failure": {"pull_request": None},
                "needs_review": "closed as not planned: name the replacement issue and the failed PR, "
                                "with its return, handoff or killed session run"}, True
    proven, first_problems = [], None
    for pr in landing_prs(repo, number):              # the check is the oracle: keep each pair it accepts
        for ret in changed_returns(repo, [pr]):
            pair = {"number": number, "disposition": "completed", "pull_requests": [pr], "returns": [ret]}
            problems = prove(repo, number, pair, notice=lambda _: None)
            if not problems:
                proven.append((pr, ret))
            elif first_problems is None:
                first_problems = problems
    if not proven:
        return {"number": number, "disposition": "completed", "pull_requests": [], "returns": [],
                "needs_review": "; ".join(first_problems or ["no merged PR the issue's timeline cites changed "
                                                             "a role return for it"])}, True
    entry = {"number": number, "disposition": "completed",
             "pull_requests": sorted({pr for pr, _ in proven}), "returns": sorted({r for _, r in proven})}
    if prove(repo, number, entry, notice=lambda _: None):   # each pair holds; keep the first if the union doesn't
        pr, ret = proven[0]
        entry.update(pull_requests=[pr], returns=[ret])
    return entry, False


def build(repo, epic, gh=None):
    issues = tg.descendants(repo, epic, gh)
    entries, review = [], 0
    for number in sorted(issues):
        entry, needs = disposition(repo, number, issues[number])
        entries.append(entry)
        review += needs
    return {"epic": epic, "scope": "slice-epic-descendants", "generated_by": "reconcile_epic.py (ADR-0049)",
            "issues": entries}, review


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--epic", type=int, required=True)
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true", help="print the file instead of writing it")
    a = ap.parse_args(argv)
    try:
        if not tg.has_complete_history():
            print("::error::reconcile_epic needs the default branch's full history (git fetch --unshallow)")
            return 2
        report, review = build(a.repo, a.epic)
    except (ValueError, OSError, subprocess.SubprocessError, SystemExit) as e:
        print(f"::error title=Reconciliation failed::{e}")
        return 2
    text = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    if a.dry_run:
        print(text)
    else:
        out = pathlib.Path(a.out or tg.RECONCILIATION_DIR / f"{a.epic}.yaml")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    print(f"AFS-RESULT gate=reconcile-epic epic={a.epic} issues={len(report['issues'])} needs_review={review}")
    return 1 if review else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
