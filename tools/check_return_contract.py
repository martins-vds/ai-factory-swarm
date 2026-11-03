#!/usr/bin/env python3
"""Fail an agent PR that does not commit its return file (harness rule, migration contract).

Usage (in CI, on pull_request events, with full history):
  python .migration/harness/tools/check_return_contract.py --base origin/<base branch>
                                                           [--event $GITHUB_EVENT_PATH]

Applies to agent PRs only: head branch `copilot/…` or a bot/Copilot author. Others pass untouched.
An agent PR must add or update at least one `.migration/returns/<ticket>.<role>.yaml` (diff against
--base). When the PR body says `Fixes #N` / `Closes #N` / `Resolves #N`, one of those files must have
`issue: <owner>/<repo>#N`, or name the ticket #N is a sub-issue of (a Verifier's or a fix's own issue). The file's content is validated against schemas/return.schema.json by
`validate.py` in the same workflow. A return contract pasted into the PR description (instead of
linked) produces a warning, not a failure, because later sessions cannot edit the description.
Needs git and PyYAML.
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


def pasted_contract(body):
    """True if the PR body pastes a return file (a yaml block with role/ticket/issue) instead of linking it."""
    for block in re.findall(r"```ya?ml\s*\n(.*?)```", body or "", re.S):
        try:
            doc = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and "ticket" in doc and ("role" in doc or "gates" in doc):
            return True
    return False


def changed_return_files(base, root="."):
    out = subprocess.run(["git", "-C", root, "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD", "--",
                          ".migration/returns/"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split() if re.search(r"\.ya?ml$", p)]


def github_parent(number):
    """The parent ticket of a sub-issue (a Verifier's or a fix's own issue), via the REST API in CI; else None."""
    import urllib.request
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not repo or not token:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues/{number}",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            url = json.load(r).get("parent_issue_url") or ""
    except (OSError, ValueError):
        return None
    m = re.search(r"/issues/(\d+)$", url)
    return m.group(1) if m else None


def check(body, files, root=".", parent_of=lambda n: None):
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
        # A Verifier or a fix runs on its own issue, a sub-issue of the ticket (agents/README.md): its PR closes
        # that issue while the return file names the ticket. Either counts.
        accepted = issues | {p for p in (parent_of(n) for n in issues) if p}
        if not accepted & found:
            return False, (f"the PR closes #{', #'.join(sorted(issues))} but no changed return file has a "
                           f"matching `issue:` (the issue, or the ticket it is a sub-issue of; files: "
                           f"{', '.join(files)})")
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
    ok, msg = check(pr.get("body") or "", changed_return_files(a.base), parent_of=github_parent)
    if pasted_contract(pr.get("body") or ""):
        # A warning, not a failure: a follow-up session cannot edit the description to fix it.
        print("::warning title=Return contract pasted into the PR description::Link to "
              ".migration/returns/<ticket>.<role>.yaml instead of pasting it; the pasted copy goes stale when "
              "the file changes.")
    if ok:
        print(msg)
        return 0
    print(f"::error title=Return file missing::{msg}. See afs-migration-contract → Return files.")
    return 1


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
