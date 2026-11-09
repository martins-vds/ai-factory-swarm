#!/usr/bin/env python3
"""Close capability-gap issues once the checklist on the default branch says the gap is closed.

  close_gap_issues.py --repo owner/repo [--capabilities .migration/capabilities.yaml] [--dry-run]

Bootstrap opens one `afs:capability-gap` issue per gap, titled `Capability gap: <id> (<applies_to>)`.
The checklist entry then turns `met`, `waived` or `not-applicable`, and nothing closed the issue: on the
synthetic target six stayed open after the scaffolding met them, and the operator had to ask. This runs on
every push to the default branch and closes each open gap issue whose entry is no longer a gap, with a
comment naming the evidence: `provided_by` for met (closed as completed), the waiver or reason otherwise
(closed as not planned). An issue is matched by the entry's `ticket` (`owner/repo#N`) or, when the entry
dropped it, by its exact bootstrap title. An entry still `gap`, or an issue matching no entry, is left
open. Exit 0, or 2 when GitHub can't be read or written. Standard library plus PyYAML and gh.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

CLOSED = {"met": "completed", "waived": "not_planned", "not-applicable": "not_planned"}
LABEL = "afs:capability-gap"


def gh(*args, data=None):
    cmd = ["gh", "api", *args] + (["--input", "-"] if data is not None else [])
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"gh api {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def open_gap_issues(repo):
    issues, page = [], 1
    while True:
        batch = gh(f"repos/{repo}/issues?state=open&labels={LABEL}&per_page=100&page={page}") or []
        issues += [i for i in batch if not i.get("pull_request")]
        if len(batch) < 100:
            return issues
        page += 1


def title(entry):
    return f"Capability gap: {entry.get('id')} ({entry.get('applies_to')})"


def evidence(entry):
    status = entry.get("status")
    if status == "met":
        names = [p.get("name") for p in entry.get("provided_by") or [] if isinstance(p, dict) and p.get("name")]
        return "met, provided by " + ("; ".join(f"`{n}`" for n in names) if names else "the checklist entry")
    if status == "waived":
        w = entry.get("waiver") or {}
        return f"waived by {w.get('approved_by', 'the operator')}: {w.get('reason', 'see the checklist')}"
    return f"not applicable: {entry.get('notes') or entry.get('reason') or 'see the checklist'}"


def plan(repo, entries, issues):
    """(issue, entry) pairs to close: the issue is open and its entry is no longer a gap."""
    by_ticket, by_title = {}, {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        m = re.fullmatch(rf"{re.escape(repo)}#([1-9][0-9]*)", str(e.get("ticket") or "").strip())
        if m:
            by_ticket[int(m[1])] = e
        by_title[title(e)] = e
    out = []
    for issue in issues:
        entry = by_ticket.get(issue["number"]) or by_title.get(issue.get("title"))
        if entry and entry.get("status") in CLOSED:
            out.append((issue, entry))
    return out


def main(argv=None):
    import yaml
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--capabilities", type=pathlib.Path, default=pathlib.Path(".migration/capabilities.yaml"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        doc = yaml.safe_load(a.capabilities.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"::error::cannot read {a.capabilities}: {e}")
        return 2
    try:
        issues = open_gap_issues(a.repo)
        todo = plan(a.repo, doc.get("capabilities") or [], issues)
        for issue, entry in todo:
            n = issue["number"]
            print(f"#{n} {issue.get('title')}: {evidence(entry)}" + (" (dry run)" if a.dry_run else ""))
            if a.dry_run:
                continue
            gh(f"repos/{a.repo}/issues/{n}/comments", "-X", "POST",
               data={"body": f"Closed by the harness: the capability checklist on the default branch says this gap is "
                             f"{evidence(entry)} (`.migration/capabilities.yaml`, `{entry.get('id')}`)."})
            gh(f"repos/{a.repo}/issues/{n}", "-X", "PATCH",
               data={"state": "closed", "state_reason": CLOSED[entry["status"]]})
    except RuntimeError as e:
        print(f"::error::{e}")
        return 2
    print(f"AFS-RESULT gate=gap-issues open={len(issues)} closed={len(todo)}")
    return 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
