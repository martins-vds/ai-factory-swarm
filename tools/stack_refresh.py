#!/usr/bin/env python3
"""Refresh stacked PRs when the default branch moves (ADR-0038).

  stack_refresh.py --repo OWNER/NAME [--prs PRS.json] [--dry-run] [--comment]

A stacked PR targets another PR's branch. When the default branch moves, check_stack_base.py fails every
such PR until someone merges the default branch into the bottom of the stack, then each branch into the
one above it. This tool does that, bottom-up, in a clone with full history and an `origin` it may push to:

* The stack is every open PR whose base is not the default branch, plus every PR whose head is the base
  of a PR already in it (the bottom of a stack targets the default branch itself).
* Parents before children: each branch is merged with its base only after that base was refreshed.
* A branch that already contains its base is left alone (no empty merge commits).
* A PR whose title starts with "[WIP]" has an agent session pushing to it; it and everything above it are
  skipped and reported, never pushed over.
* A merge that conflicts is aborted; the PR gets a comment (with --comment) and everything above it is
  skipped. Conflicts are a person's or a session's job; the tool never resolves them.
* PRs from forks are skipped: their branches aren't ours to push.

Exit 0 when every stacked PR is current or was refreshed, 1 when any was skipped or conflicted (the
summary says which and why), 2 on a usage or git error. Standard library plus git and gh.
"""
import argparse
import json
import subprocess
import sys

MARK = "<!-- afs-stack-refresh -->"
WIP = "[WIP]"


def git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def contains(ancestor, descendant):
    r = git("merge-base", "--is-ancestor", ancestor, descendant, check=False)
    if r.returncode not in (0, 1):
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r.returncode == 0


def open_prs(repo):
    out = subprocess.run(["gh", "api", "--paginate", f"repos/{repo}/pulls?state=open&per_page=100"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out.replace("][", ","))


def default_branch(repo):
    return subprocess.run(["gh", "api", f"repos/{repo}", "-q", ".default_branch"],
                          capture_output=True, text=True, check=True).stdout.strip()


def stack_order(prs, default, repo):
    """Stacked PRs, parents before children. Each entry: (pr, depth)."""
    own = [p for p in prs if (p.get("head", {}).get("repo") or {}).get("full_name") == repo]
    by_head = {p["head"]["ref"]: p for p in own}
    stacked = {p["number"] for p in own if p["base"]["ref"] != default}
    frontier = list(stacked)
    while frontier:   # pull in the PRs whose heads the stack is built on
        number = frontier.pop()
        p = next(q for q in own if q["number"] == number)
        parent = by_head.get(p["base"]["ref"])
        if parent and parent["number"] not in stacked:
            stacked.add(parent["number"])
            frontier.append(parent["number"])
    order, seen = [], set()

    def depth(p, trail=()):
        parent = by_head.get(p["base"]["ref"])
        if not parent or parent["number"] in trail:
            return 0
        return 1 + depth(parent, trail + (p["number"],))

    for p in sorted((q for q in own if q["number"] in stacked), key=lambda q: (depth(q), q["number"])):
        if p["number"] not in seen:
            seen.add(p["number"])
            order.append((p, depth(p)))
    return order, [p for p in prs if p not in own and p["base"]["ref"] != default]


def comment(repo, number, text):
    subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/comments", "-f",
                    f"body={MARK}\n{text}"], capture_output=True, text=True, check=True)


def refresh(repo, prs, default, dry_run=False, post=False, ident=("AFS stack refresh", "afs-stack-refresh@users.noreply.github.com")):
    git("fetch", "--quiet", "origin", "+refs/heads/*:refs/remotes/origin/*")
    order, forks = stack_order(prs, default, repo)
    blocked, lines, problems = set(), [], 0
    for p in forks:
        lines.append(f"- #{p['number']} skipped: its branch is in a fork")
        problems += 1
    for p, _ in order:
        n, head, base = p["number"], p["head"]["ref"], p["base"]["ref"]
        parent_blocked = base in blocked
        if parent_blocked:
            blocked.add(head)
            lines.append(f"- #{n} `{head}` skipped: its base `{base}` couldn't be refreshed")
            problems += 1
            continue
        if contains(f"origin/{base}", f"origin/{head}"):
            lines.append(f"- #{n} `{head}` current: contains `{base}`")
            continue
        if p.get("title", "").startswith(WIP):
            blocked.add(head)
            lines.append(f"- #{n} `{head}` skipped: an agent session is still working on it ({WIP}); "
                         f"it gets refreshed after the session ends and the default branch moves again, "
                         f"or by hand: merge `origin/{base}` into it")
            problems += 1
            continue
        git("checkout", "--quiet", "-B", head, f"origin/{head}")
        merged = git("-c", f"user.name={ident[0]}", "-c", f"user.email={ident[1]}", "merge", "--no-ff",
                     "--quiet", f"origin/{base}", "-m", f"Merge {base} into {head} (stack refresh, ADR-0038)",
                     check=False)
        if merged.returncode != 0:
            git("merge", "--abort", check=False)
            blocked.add(head)
            files = git("diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
            lines.append(f"- #{n} `{head}` CONFLICT merging `{base}`: resolve by hand or in a session")
            problems += 1
            if post and not dry_run:
                comment(repo, n, f"Stack refresh (ADR-0038) couldn't merge `{base}` into `{head}`: the merge "
                                 f"conflicts{(' in ' + ', '.join(f'`{f}`' for f in files)) if files else ''}. "
                                 f"Merge `origin/{base}` into this branch, resolve, and push; the PRs stacked "
                                 f"on it are refreshed on the next push to `{default}`.")
            continue
        if dry_run:
            lines.append(f"- #{n} `{head}` would be refreshed from `{base}` (dry run)")
            git("reset", "--quiet", "--hard", f"origin/{head}")
            blocked.add(head)   # children can't be tested against an unpushed parent
            continue
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{head}")
        git("fetch", "--quiet", "origin", f"+refs/heads/{head}:refs/remotes/origin/{head}")
        lines.append(f"- #{n} `{head}` refreshed from `{base}`")
    return problems, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--prs", help="open PRs as JSON (the GitHub pulls API shape); default: ask gh")
    ap.add_argument("--default", help="default branch; default: ask gh")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--comment", action="store_true", help="comment on a PR whose refresh conflicts")
    a = ap.parse_args(argv)
    try:
        prs = json.load(open(a.prs)) if a.prs else open_prs(a.repo)
        default = a.default or default_branch(a.repo)
        problems, lines = refresh(a.repo, prs, default, a.dry_run, a.comment)
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        print(f"::error title=Stack refresh failed::{detail.strip()}")
        return 2
    print(f"Stack refresh against `{default}`:" if lines else f"No stacked PRs against `{default}`.")
    print("\n".join(lines))
    print(f"AFS-RESULT gate=stack-refresh stacked={len(lines)} problems={problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
