#!/usr/bin/env python3
"""Fail an agent PR whose description lacks its role's return contract (harness rule, migration contract).

Usage (in CI, on pull_request events):
  python .migration/harness/tools/check_return_contract.py [--event $GITHUB_EVENT_PATH] [--agents .github/agents]

Applies to agent PRs only: head branch `copilot/…` or a bot/Copilot author. Others pass untouched.
Passes when the PR body contains a fenced ```yaml block that parses to a mapping whose top-level keys
include every key of at least one role agent's return contract (from the `## Return contract` block in
`.github/agents/afs-*.agent.md`). Values may be null. Prints the closest role and its missing keys.
Needs PyYAML.
"""
import argparse
import json
import os
import pathlib
import re
import sys

import yaml

AGENT_AUTHORS = {"Copilot", "copilot-swe-agent[bot]", "copilot-swe-agent"}


def contracts(agents_dir):
    out = {}
    for f in sorted(pathlib.Path(agents_dir).glob("afs-*.agent.md")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"## Return contract\s*```ya?ml\n(.*?)```", text, re.S)
        if m:
            keys = re.findall(r"^([a-z_]+):", m.group(1), re.M)
            if keys:
                out[f.name.split(".")[0]] = set(keys)
    return out


def yaml_blocks(body):
    for block in re.findall(r"```ya?ml\s*\n(.*?)```", body or "", re.S):
        try:
            doc = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            yield set(doc)


def check(body, roles):
    blocks = list(yaml_blocks(body))
    best = None
    for keys in blocks:
        for role, need in roles.items():
            missing = need - keys
            if not missing:
                return True, f"return contract found ({role})"
            if best is None or len(missing) < len(best[1]):
                best = (role, missing)
    if not blocks:
        return False, "no ```yaml block in the PR description"
    return False, f"closest role {best[0]}: missing keys {sorted(best[1])}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    ap.add_argument("--agents", default=".github/agents")
    a = ap.parse_args()
    if not a.event or not pathlib.Path(a.event).exists():
        print("no event payload; nothing to check")
        return 0
    pr = json.loads(pathlib.Path(a.event).read_text(encoding="utf-8")).get("pull_request")
    if not pr:
        print("not a pull request event; nothing to check")
        return 0
    author = (pr.get("user") or {}).get("login", "")
    agent_pr = pr["head"]["ref"].startswith("copilot/") or author in AGENT_AUTHORS or author.endswith("[bot]")
    if not agent_pr:
        print(f"PR by {author} from {pr['head']['ref']}: not an agent PR; skipped")
        return 0
    ok, msg = check(pr.get("body") or "", contracts(a.agents))
    if ok:
        print(msg)
        return 0
    print(f"::error title=Return contract missing::{msg}. End the PR description with your agent's "
          f"return contract YAML (see .github/agents/<role>.agent.md → Return contract); fill what you have, "
          f"null the rest.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
