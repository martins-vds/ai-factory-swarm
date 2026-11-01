#!/usr/bin/env python3
"""Check that every repo path a ticket names exists before work starts (afs-setup-check).

Usage: pipe the ticket body in, from the repo root:
  python .migration/harness/tools/check_inputs.py < ticket.md
  python .migration/harness/tools/check_inputs.py --text "$(gh issue view 22 --json body -q .body)"

Takes every `backticked` token that looks like a repo path (contains a "/" or starts with "."; no spaces,
no URL, no placeholder such as <ticket>) and checks it exists, as a file, folder or glob. Paths under
`.source/` are checked in the source checkout. Exit 1 if any is missing, listing them, so the agent
stops and hands off instead of concluding an input "is not present" without looking. Standard library only.
"""
import argparse
import glob
import os
import re
import sys

TOKEN = re.compile(r"`([^`\s]+)`")
SKIP = re.compile(r"(://|[<>{}$|]|^-|\(|\)|::|=)")
# Paths the ticket asks the agent to create, by convention.
OUTPUT_PREFIXES = (".migration/returns/", ".migration/handoffs/", ".migration/quirks/", ".migration/evidence/",
                   ".migration/runs/")


def candidates(text):
    seen = []
    for tok in TOKEN.findall(text):
        tok = tok.rstrip(".,;:")
        if SKIP.search(tok) or not ("/" in tok or tok.startswith(".")):
            continue
        if tok.startswith(OUTPUT_PREFIXES) or tok.startswith("http"):
            continue
        if re.match(r"^[\w.-]+/[\w.-]+#\d+$", tok):   # owner/repo#N
            continue
        if tok not in seen:
            seen.append(tok)
    return seen


def exists(path):
    path = path.rstrip("/")
    return os.path.exists(path) or bool(glob.glob(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", help="ticket body (default: stdin)")
    ap.add_argument("--ignore", action="append", default=[], help="a named path the ticket asks you to create")
    a = ap.parse_args()
    text = a.text if a.text is not None else sys.stdin.read()
    paths = [p for p in candidates(text) if p not in a.ignore]
    missing = [p for p in paths if not exists(p)]
    for p in paths:
        print(f"{'ok     ' if p not in missing else 'MISSING'} {p}")
    print(f"{len(paths)} named path(s), {len(missing)} missing")
    if missing:
        print("If the ticket asks you to create a path, re-run with --ignore <path>. Otherwise stop and hand "
              "off: an input your ticket names is missing.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
