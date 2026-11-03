#!/usr/bin/env python3
"""Open the "re-walk the fog" wayfinder task when a slice epic closes (ADR-0022).

Wayfinder graduates fog into tickets when a ticket is resolved. In a migration, slices execute outside the
decision map, and their work sharpens fog no ticket resolution touches, so the map's *Not yet specified*
list can go stale for months. This tool turns the re-walk into an open ticket instead of a memory:
a `wayfinder:task` child of the map, assigned to the person who closed the epic, whose checklist is the
current *Not yet specified* list.

  fog_rewalk.py --repo owner/repo --epic 9 --closed-by alice      (the AFS map fog workflow runs this)
  fog_rewalk.py --print --map-body FILE --epic-title "Slice: X"   (render the ticket body only; tests)

Uses `gh api`. Does nothing when the repo has no open `wayfinder:map` issue, when the epic is still open, or
when the map already has this re-walk ticket (so a re-run is safe). Exit 0 unless the API fails.
"""
import argparse
import json
import re
import subprocess
import sys


def fog_items(map_body):
    """The bullet items of the map's '## Not yet specified' section (continuation lines folded in)."""
    m = re.search(r"^## Not yet specified\s*$(.*?)(?=^## |^---\s*$|\Z)", map_body or "", re.M | re.S)
    if not m:
        return []
    items, cur = [], None
    for line in m.group(1).splitlines():
        if re.match(r"^\s*<!--", line):
            continue
        b = re.match(r"^[-*]\s+(.*)", line)
        if b:
            cur = b.group(1).strip()
            items.append(cur)
        elif cur is not None and line.strip():
            items[-1] = f"{items[-1]} {line.strip()}"
    return items


def ticket(epic_title, epic_url, items):
    title = f"Re-walk the fog after accepting \"{epic_title}\""
    lines = ["## Question", "",
             f"[{epic_title}]({epic_url}) is accepted. Its work may have made parts of the map's *Not yet "
             "specified* list precise enough to ask. For each item below, either open a ticket for it (a "
             "child of the map with its `wayfinder:` type, blocking edges wired) and remove it from the list, "
             "or confirm it is still fog. Also add any decision the slice surfaced that is nowhere on the map. "
             "Resolve this ticket with one line per item: its new ticket, or \"still fog: why\".", ""]
    lines += [f"- [ ] {i}" for i in items] or ["- [ ] *Not yet specified* is empty: confirm nothing new surfaced."]
    return title, "\n".join(lines) + "\n"


def is_slice_epic(number, labels, slices_dir=".migration/slices"):
    """A slice epic carries the `afs:slice` label, or a slice spec names it (`epic: <n>`): either is enough,
    so a forgotten label doesn't silently skip the re-walk."""
    if "afs:slice" in labels:
        return True
    import pathlib
    import yaml
    for spec in sorted(pathlib.Path(slices_dir).glob("*.y*ml")):
        doc = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
        if str(doc.get("epic", "")).lstrip("#") == str(number):
            return True
    return False


def gh(*args, data=None):
    cmd = ["gh", "api", *args] + (["--input", "-"] if data is not None else [])
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"gh api {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo")
    ap.add_argument("--epic", type=int)
    ap.add_argument("--closed-by")
    ap.add_argument("--print", action="store_true", help="render only")
    ap.add_argument("--map-body")
    ap.add_argument("--epic-title", default="the slice")
    a = ap.parse_args(argv)
    if a.print:
        title, body = ticket(a.epic_title, "#", fog_items(open(a.map_body, encoding="utf-8").read()))
        print(title)
        print(body)
        return 0
    R = f"repos/{a.repo}"
    epic = gh(f"{R}/issues/{a.epic}")
    if not is_slice_epic(a.epic, [lbl["name"] for lbl in epic.get("labels", [])]):
        print(f"#{a.epic} is not a slice epic (no afs:slice label, not named by a slice spec); nothing to do.")
        return 0
    if epic.get("state") != "closed":
        print(f"#{a.epic} is still open; the re-walk follows acceptance. Nothing to do.")
        return 0
    maps = gh(f"{R}/issues?labels=wayfinder:map&state=open&per_page=10") or []
    if not maps:
        print("::notice::No open wayfinder:map issue; nothing to re-walk.")
        return 0
    for m in maps:
        title, body = ticket(epic["title"], epic["html_url"], fog_items(m.get("body")))
        existing = [i for i in gh(f"{R}/issues/{m['number']}/sub_issues?per_page=100") or [] if i["title"] == title]
        if existing:
            print(f"map #{m['number']} already has {existing[0]['html_url']}; not opening another")
            continue
        issue = gh(f"{R}/issues", "-X", "POST",
                   data={"title": title, "body": body, "labels": ["wayfinder:task"],
                         **({"assignees": [a.closed_by]} if a.closed_by else {})})
        gh(f"{R}/issues/{m['number']}/sub_issues", "-X", "POST", data={"sub_issue_id": issue["id"]})
        print(f"opened {issue['html_url']} on map #{m['number']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
