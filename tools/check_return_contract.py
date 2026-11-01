#!/usr/bin/env python3
"""Fail an agent PR that does not commit its return file (harness rule, migration contract).

Usage (in CI, on pull_request events, with full history):
  python .migration/harness/tools/check_return_contract.py --base origin/<base branch>
                                                           [--event $GITHUB_EVENT_PATH]

Applies to agent PRs only: head branch `copilot/…` or a bot/Copilot author. Others pass untouched.
An agent PR must add or update at least one `.migration/returns/<ticket>.<role>.yaml` (diff against
--base). When the PR body says `Fixes #N` / `Closes #N` / `Resolves #N`, one of those files must have
`issue: <owner>/<repo>#N`. The file's content is validated against schemas/return.schema.json by
`validate.py` in the same workflow. Needs git and PyYAML.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

AGENT_AUTHORS = {"Copilot", "copilot-swe-agent[bot]", "copilot-swe-agent"}
CLOSES = re.compile(r"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s+#(\d+)")


def is_agent_pr(pr):
    author = (pr.get("user") or {}).get("login", "")
    return pr["head"]["ref"].startswith("copilot/") or author in AGENT_AUTHORS or author.endswith("[bot]")


def changed_return_files(base, root="."):
    out = subprocess.run(["git", "-C", root, "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD", "--",
                          ".migration/returns/"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split() if re.search(r"\.ya?ml$", p)]


def check(body, files, root="."):
    if not files:
        return False, ("no return file in this PR: commit .migration/returns/<ticket>.<role>.yaml "
                       "(your agent's return contract plus role, ticket, issue)")
    issues = set(CLOSES.findall(body or ""))
    if issues:
        found = set()
        for f in files:
            try:
                doc = yaml.safe_load(pathlib.Path(root, f).read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            m = re.search(r"#(\d+)$", str(doc.get("issue") or ""))
            if m:
                found.add(m.group(1))
        if not issues & found:
            return False, (f"the PR closes #{', #'.join(sorted(issues))} but no changed return file has a "
                           f"matching `issue:` (files: {', '.join(files)})")
    return True, f"return file(s): {', '.join(files)}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="e.g. origin/main")
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    a = ap.parse_args()
    if not a.event or not pathlib.Path(a.event).exists():
        print("no event payload; nothing to check")
        return 0
    pr = json.loads(pathlib.Path(a.event).read_text(encoding="utf-8")).get("pull_request")
    if not pr:
        print("not a pull request event; nothing to check")
        return 0
    if not is_agent_pr(pr):
        print(f"not an agent PR ({pr['head']['ref']}); skipped")
        return 0
    ok, msg = check(pr.get("body") or "", changed_return_files(a.base))
    if ok:
        print(msg)
        return 0
    print(f"::error title=Return file missing::{msg}. See afs-migration-contract → Return files.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
