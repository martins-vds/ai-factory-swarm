#!/usr/bin/env python3
"""Check that the code graphs describe the code they claim to (ADR-0019). Deterministic; needs git.

Each graph folder `.migration/graphs/<side>/<scope>/` has a SNAPSHOT.txt (`key: value` lines) written
by the afs-understand workflow, and the graph JSONs carry the same identity in `project.gitCommitHash`.

  source/<scope>   fresh when SNAPSHOT `source_sha` and both JSONs' gitCommitHash equal .migration/source.lock's sha
  target/full      fresh when SNAPSHOT `tree.<path>` equals `git rev-parse HEAD:<path>` for every analysed path
                   (code changes make it stale; test-only changes don't, because tests live outside src/)

A graph written before ADR-0019 (no `source_sha` / `tree.*` lines) is reported as unstamped, i.e. stale.

Usage:
  check_graph_fresh.py                                 exit 1 on a stale source graph; a stale target graph
                                                       is only a warning (code changes every merge)
  check_graph_fresh.py --require source,target         also exit 1 when a required side has no graph
  check_graph_fresh.py --only .migration/graphs/target/full   check just that graph (the workflow's own build)
  check_graph_fresh.py --acceptance-since origin/main  require both sides if the change adds or updates an
                                                       auditor return with `verdict: complete` (CI)
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

import yaml

GRAPHS = pathlib.Path(".migration/graphs")


def snapshot(folder):
    path = folder / "SNAPSHOT.txt"
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def json_commits(folder):
    out = {}
    for name in ("knowledge-graph.json", "domain-graph.json"):
        p = folder / name
        if p.is_file():
            try:
                out[name] = (json.loads(p.read_text(encoding="utf-8")).get("project") or {}).get("gitCommitHash")
            except ValueError:
                out[name] = "<invalid JSON>"
    return out


def check_source(folder, pinned):
    snap = snapshot(folder)
    if "source_sha" not in snap:
        return [f"{folder}: unstamped (no source_sha in SNAPSHOT.txt); rebuild it with afs-understand side=source"]
    problems = []
    if snap["source_sha"] != pinned:
        problems.append(f"{folder}: built from {snap['source_sha'][:12]}, but source.lock pins {pinned[:12]}")
    for name, commit in json_commits(folder).items():
        if commit != snap["source_sha"]:
            problems.append(f"{folder}/{name}: gitCommitHash {str(commit)[:12]} != source_sha {snap['source_sha'][:12]}")
    return problems


def check_target(folder):
    snap = snapshot(folder)
    trees = {k[len("tree."):]: v for k, v in snap.items() if k.startswith("tree.")}
    if not trees:
        return [f"{folder}: unstamped (no tree.<path> lines in SNAPSHOT.txt); rebuild it with afs-understand side=target"]
    problems = []
    for path, recorded in sorted(trees.items()):
        now = git("rev-parse", f"HEAD:{path}")
        if now != recorded:
            problems.append(f"{folder}: {path}/ changed since the graph was built "
                            f"(graph {recorded[:12]}, now {str(now)[:12]}); rebuild it with afs-understand side=target")
    commit = snap.get("target_commit")
    for name, c in json_commits(folder).items():
        if commit and c != commit:
            problems.append(f"{folder}/{name}: gitCommitHash {str(c)[:12]} != target_commit {commit[:12]}")
    return problems


def accepting(base):
    """True if the change adds or updates an auditor return whose verdict is `complete`."""
    changed = git("diff", "--name-only", f"{base}...HEAD", "--", ".migration/returns/") or ""
    for name in changed.splitlines():
        p = pathlib.Path(name)
        if p.name.endswith(".afs-auditor.yaml") and p.is_file():
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if doc.get("verdict") == "complete":
                return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require", default="", help="comma-separated sides that must have a fresh graph")
    ap.add_argument("--acceptance-since", metavar="REF")
    ap.add_argument("--only", metavar="FOLDER", help="check this graph folder alone, as a hard requirement")
    a = ap.parse_args(argv)
    required = {s for s in a.require.split(",") if s}
    if a.acceptance_since and accepting(a.acceptance_since):
        print("acceptance (auditor verdict: complete): both graphs must be fresh")
        required |= {"source", "target"}

    pinned = yaml.safe_load(pathlib.Path(".migration/source.lock").read_text(encoding="utf-8"))["sha"]
    problems, warnings, fresh = [], [], []
    if a.only:
        folder = pathlib.Path(a.only)
        side = folder.parent.name
        if side not in ("source", "target") or not folder.is_dir():
            print(f"{folder}: not a graph folder (.migration/graphs/<source|target>/<scope>)", file=sys.stderr)
            return 2
        problems = check_source(folder, pinned) if side == "source" else check_target(folder)
        for p in problems:
            print(p, file=sys.stderr)
        print(f"graph {folder}: {'STALE' if problems else 'OK'}")
        return 1 if problems else 0
    for side in ("source", "target"):
        folders = sorted(p for p in (GRAPHS / side).glob("*") if p.is_dir()) if (GRAPHS / side).is_dir() else []
        if not folders and side in required:
            problems.append(f"{GRAPHS / side}: no graph; build it with afs-understand side={side}")
        for folder in folders:
            found = check_source(folder, pinned) if side == "source" else check_target(folder)
            # The source never moves without a source.lock change, so a stale source graph is always an error.
            (problems if side == "source" or side in required else warnings).extend(found)
            if not found:
                fresh.append(str(folder))
    ci = "GITHUB_ACTIONS" in os.environ
    for p in problems:
        print(f"::error::{p}" if ci else p, file=sys.stderr)
    for w in warnings:
        print(f"::warning::{w}" if ci else f"warning: {w}", file=sys.stderr)
    print(f"graphs {'STALE' if problems else 'OK'}: fresh = {', '.join(fresh) or 'none'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
