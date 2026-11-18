#!/usr/bin/env python3
"""Check that the code graphs describe the code they claim to (ADR-0019). Deterministic; needs git.

Each graph folder `.migration/graphs/<side>/<scope>/` has a SNAPSHOT.txt (`key: value` lines) written
by the afs-understand workflow, and the graph JSONs carry the same identity in `project.gitCommitHash`.

  source/<scope>   fresh when SNAPSHOT `source_sha` and both JSONs' gitCommitHash equal .migration/source.lock's sha
  target/full      fresh when SNAPSHOT `tree.<path>` equals `git rev-parse HEAD:<path>` for every analysed path
                   (code changes make it stale; test-only changes don't, because tests live outside src/),
                   and complete when no tracked Django template (an .html file with {% %} or {{ }}) lies
                   outside those paths: such pages are invisible to the graph (add their folder to the
                   profile's graph.target_paths, or a non-app folder to graph.target_exclude)

A graph written before ADR-0019 (no `source_sha` / `tree.*` lines) is reported as unstamped, i.e. stale.

Usage:
  check_graph_fresh.py                                 exit 1 on a stale source graph; a stale target graph
                                                       is only a warning (code changes every merge)
  check_graph_fresh.py --require source,target         also exit 1 when a required side has no graph
  check_graph_fresh.py --only .migration/graphs/target/full   check just that graph (the workflow's own build)
  check_graph_fresh.py --acceptance-since origin/main  if the change adds or updates an auditor return with
                                                       `verdict: complete` (CI): the source graph must be fresh, and
                                                       a passed acceptance run in the change must have built its
                                                       own target graph for a commit in this history (ADR-0035);
                                                       the committed target graph is a reference only

AFS_GRAPH_TARGET_DIR (set by afs-acceptance) points the target side at the acceptance run's own build.
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


NOT_APP = {".github", ".migration", ".source", "docs", "tests", "test", "node_modules"}


def target_exclude(profile=".migration/profile.yaml"):
    """The profile's graph.target_exclude: folders of this repo that hold no application pages."""
    p = pathlib.Path(profile)
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else {}
    return [x.rstrip("/") for x in ((doc or {}).get("graph") or {}).get("target_exclude") or []]


def outside_templates(paths, exclude=()):
    """Tracked Django templates that no analysed path covers (the graph can't see those pages)."""
    out = []
    under = lambda f, folders: any(f == p or f.startswith(p.rstrip("/") + "/") for p in folders)
    for f in (git("ls-files", "*.html") or "").splitlines():
        parts = pathlib.PurePosixPath(f).parts
        if NOT_APP & set(parts) or under(f, paths) or under(f, exclude):
            continue
        try:
            text = pathlib.Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "{%" in text or "{{" in text:
            out.append(f)
    return out


def check_target(folder, rev="HEAD"):
    snap = snapshot(folder)
    trees = {k[len("tree."):]: v for k, v in snap.items() if k.startswith("tree.")}
    if not trees:
        return [f"{folder}: unstamped (no tree.<path> lines in SNAPSHOT.txt); rebuild it with afs-understand side=target"]
    problems = [f"{folder}: {f}: a Django template outside the analysed paths ({', '.join(sorted(trees))}); add its "
                f"folder to graph.target_paths (or, if it holds no app pages, graph.target_exclude) in .migration/profile.yaml, then rebuild with afs-understand side=target"
                for f in outside_templates(trees, target_exclude())]
    for path, recorded in sorted(trees.items()):
        now = git("rev-parse", f"{rev}:{path}")
        if now != recorded:
            problems.append(f"{folder}: {path}/ changed since the graph was built "
                            f"(graph {recorded[:12]}, now {str(now)[:12]}); rebuild it with afs-understand side=target")
    commit = snap.get("target_commit")
    for name, c in json_commits(folder).items():
        if commit and c != commit:
            problems.append(f"{folder}/{name}: gitCommitHash {str(c)[:12]} != target_commit {commit[:12]}")
    return problems


def target_folders():
    """The target graphs to check: the acceptance run's own build when AFS_GRAPH_TARGET_DIR is set (ADR-0035)."""
    env = os.environ.get("AFS_GRAPH_TARGET_DIR")
    if env:
        return [pathlib.Path(env)] if pathlib.Path(env).is_dir() else []
    side = GRAPHS / "target"
    return sorted(p for p in side.glob("*") if p.is_dir()) if side.is_dir() else []


def acceptance_runs(base):
    """Acceptance results (`.migration/evidence/acceptance-runs/*.json`) this change adds or updates."""
    changed = git("diff", "--name-only", f"{base}...HEAD", "--", ".migration/evidence/acceptance-runs/") or ""
    out = []
    for name in changed.splitlines():
        p = pathlib.Path(name)
        if p.suffix == ".json" and p.is_file():
            try:
                out.append((p, json.loads(p.read_text(encoding="utf-8"))))
            except ValueError:
                out.append((p, {}))
    return out


RUNS_DIR = pathlib.PurePosixPath(".migration/evidence/acceptance-runs")


def cited_runs(base):
    """Acceptance results an accepting auditor return cites with `acceptance_run:`, already committed (pilot
    BK-05J re-audit: acceptance merged its run in #474, then a later audit returned `complete`)."""
    out = []
    for doc in accepting_returns(base):
        cited = doc.get("acceptance_run")
        if not cited:
            continue
        p = pathlib.PurePosixPath(str(cited))
        if p.parent != RUNS_DIR or p.suffix != ".json" or ".." in p.parts:
            out.append((pathlib.Path(str(cited)), {"status": f"not a committed acceptance result ({cited})"}))
            continue
        path = pathlib.Path(p.as_posix())
        try:
            out.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            out.append((path, {"status": f"missing or unreadable ({cited})"}))
    return out


def binding_problems(base):
    """ADR-0035: an accepting change must carry a passed acceptance run whose own target graph describes its
    commit, and that commit must be in this change's history. Today's `main` may have moved on: fine. The run
    is one this change adds, or an already committed one the accepting return cites (`acceptance_run:`)."""
    runs = acceptance_runs(base) + cited_runs(base)
    if not runs:
        return ["acceptance (auditor verdict: complete) cites no acceptance run: commit the verified result.json "
                "to .migration/evidence/acceptance-runs/<run-id>-<attempt>.json (afs-evidence, ADR-0035), or cite "
                "an already committed one in the auditor return's `acceptance_run:`"]
    reasons = []
    for path, doc in runs:
        commit, graph = doc.get("commit"), doc.get("target_graph") or {}
        trees = graph.get("trees") or {}
        if doc.get("status") != "passed" or doc.get("exit") != 0:
            reasons.append(f"{path}: the run did not pass (status {doc.get('status')}, exit {doc.get('exit')})")
        elif not commit or subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                                          capture_output=True).returncode != 0:
            reasons.append(f"{path}: commit {str(commit)[:12]} is not in this change's history")
        elif not trees:
            reasons.append(f"{path}: the run built no target graph (an acceptance run from before ADR-0035)")
        else:
            off = [p for p, t in sorted(trees.items()) if git("rev-parse", f"{commit}:{p}") != t]
            if off:
                reasons.append(f"{path}: its target graph doesn't describe commit {commit[:12]} ({', '.join(off)})")
            else:
                return []
    return reasons


def accepting_returns(base):
    """Auditor returns this change adds or updates with `verdict: complete`."""
    changed = git("diff", "--name-only", f"{base}...HEAD", "--", ".migration/returns/") or ""
    docs = []
    for name in changed.splitlines():
        p = pathlib.Path(name)
        if p.name.endswith(".afs-auditor.yaml") and p.is_file():
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if doc.get("verdict") == "complete":
                docs.append(doc)
    return docs


def accepting(base):
    """True if the change adds or updates an auditor return whose verdict is `complete`."""
    return bool(accepting_returns(base))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require", default="", help="comma-separated sides that must have a fresh graph")
    ap.add_argument("--acceptance-since", metavar="REF")
    ap.add_argument("--only", metavar="FOLDER", help="check this graph folder alone, as a hard requirement")
    a = ap.parse_args(argv)
    required = {s for s in a.require.split(",") if s}
    binding = []
    if a.acceptance_since and accepting(a.acceptance_since):
        print("acceptance (auditor verdict: complete): the source graph must be fresh, and the acceptance run's "
              "own target graph must describe its commit (ADR-0035)")
        required |= {"source"}
        binding = binding_problems(a.acceptance_since)

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
        if side == "target":
            folders = target_folders()
        else:
            folders = sorted(p for p in (GRAPHS / side).glob("*") if p.is_dir()) if (GRAPHS / side).is_dir() else []
        if not folders and side in required:
            problems.append(f"{GRAPHS / side}: no graph; build it with afs-understand side={side}")
        for folder in folders:
            found = check_source(folder, pinned) if side == "source" else check_target(folder)
            # The source never moves without a source.lock change, so a stale source graph is always an error.
            (problems if side == "source" or side in required else warnings).extend(found)
            if not found:
                fresh.append(str(folder))
    problems += binding
    ci = "GITHUB_ACTIONS" in os.environ
    for p in problems:
        print(f"::error::{p}" if ci else p, file=sys.stderr)
    for w in warnings:
        print(f"::warning::{w}" if ci else f"warning: {w}", file=sys.stderr)
    print(f"graphs {'STALE' if problems else 'OK'}: fresh = {', '.join(fresh) or 'none'}")
    return 1 if problems else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
