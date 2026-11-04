#!/usr/bin/env python3
"""Reject stacked PR checks against stale branches (issue #59).

Run after checkout with fetch-depth: 0. For a PR into a work branch, the current default branch must
be an ancestor of its base, and that base must be an ancestor of the PR's actual head. Checking the
head SHA from the event, not checkout's synthetic merge, prevents that merge from hiding stale code.
"""
import argparse
import json
import os
import pathlib
import subprocess


def is_ancestor(root, ancestor, descendant):
    result = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        result.check_returncode()
    return result.returncode == 0


def check(event, root="."):
    if not isinstance(event, dict):
        raise ValueError("the event must be a JSON object")
    pr = event.get("pull_request")
    if pr is None:
        return True, "not a pull request event; nothing to check"
    if not isinstance(pr, dict):
        raise ValueError("pull_request must be a JSON object")
    default = event["repository"]["default_branch"]
    base = pr["base"]["ref"]
    if not isinstance(default, str) or not default or not isinstance(base, str) or not base:
        raise ValueError("the event must name the default and base branches")
    if base == default:
        return True, f"PR targets the default branch ({default}); no stack to check"
    default_ref, base_ref = f"refs/remotes/origin/{default}", f"refs/remotes/origin/{base}"
    if not is_ancestor(root, default_ref, base_ref):
        return False, (f"stack base {base} is behind {default}. Merge origin/{default} into {base}, "
                       "then merge the updated base into this PR's head and push it to trigger fresh CI. "
                       "Rerunning the old workflow does not refresh its merge commit.")
    head = pr["head"]["sha"]
    if not isinstance(head, str) or len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise ValueError("the event must name the PR's full head SHA")
    if not is_ancestor(root, base_ref, head):
        return False, (f"the PR head does not contain current base {base}. Merge origin/{base} into "
                       "this PR's head and push it to trigger fresh CI; do not just rerun the old workflow.")
    return True, f"stack is current: {default} -> {base} -> PR head"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    a = ap.parse_args(argv)
    if not a.event:
        print("no event payload; nothing to check")
        return 0
    try:
        ok, message = check(json.loads(pathlib.Path(a.event).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as e:
        detail = e.stderr.strip() if isinstance(e, subprocess.CalledProcessError) else str(e)
        print(f"::error title=Cannot check stack base::{detail}. "
              "Checkout must fetch full history and origin's default and base branches.")
        return 2
    if not ok:
        print(f"::error title=Stale stack base::{message}")
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
