#!/usr/bin/env python3
"""The source graph only grows (ADR-0033): a regeneration never silently loses what an earlier one found.

The source is frozen, so anything a committed source graph describes is still true. Understand Anything is
an LLM, so a new run can still omit things. On the pilot, a run asked for one domain entry point and
returned a domain graph with that one flow, dropping the nine flows it had before.

  preserve_graph.py domain --previous OLD.json --new NEW.json
      Keep every flow of the previous domain graph that the new one doesn't have (matched by flow name,
      case-insensitive), with its steps, its domain and their edges; the new run's version wins where both
      have a flow. Writes NEW.json in place. Run by the graph workflow on the source side before its gates.

  preserve_graph.py check --base origin/main [--side source]
      For each graph folder of that side changed since --base: every flow of the base's domain graph is
      still there (by name), and every table, endpoint, page and command of the base's knowledge graph is
      still there (by name). Those node types come from the deterministic layers (enrichers), so losing one
      is a regression, not LLM noise. Exit 1 with the lost names. Run in CI on pull requests.
Standard library only; `check` needs git.
"""
import argparse
import json
import pathlib
import subprocess
import sys

KEPT_TYPES = ("table", "endpoint", "page", "command")


def key(name):
    return " ".join((name or "").lower().split())


def flows(g):
    return {key(n.get("name")): n for n in g.get("nodes", []) if n.get("type") == "flow"}


def merge_domain(prev, new):
    """Add prev's flows that new lacks (with their steps, domains and edges). Returns the names added."""
    have = flows(new)
    nodes = {n["id"]: n for n in prev.get("nodes", [])}
    new_ids = {n["id"] for n in new.get("nodes", [])}
    out_edges = {}
    for e in prev.get("edges", []):
        out_edges.setdefault(e["source"], []).append(e)
    added, take = [], set()
    for k, f in flows(prev).items():
        if k in have:
            continue
        added.append(f.get("name"))
        take.add(f["id"])
        for e in out_edges.get(f["id"], []):              # the flow's steps
            if e.get("type") == "flow_step":
                take.add(e["target"])
    for e in prev.get("edges", []):                       # the domains that contain them
        if e.get("type") == "contains_flow" and e["target"] in take:
            take.add(e["source"])
    for nid in sorted(take):
        if nid not in new_ids and nid in nodes:
            new.setdefault("nodes", []).append(nodes[nid])
    seen = {(e["source"], e["target"], e.get("type")) for e in new.get("edges", [])}
    ids = {n["id"] for n in new.get("nodes", [])}
    for e in prev.get("edges", []):
        t = (e["source"], e["target"], e.get("type"))
        if t not in seen and e["source"] in ids and e["target"] in ids and (e["source"] in take or e["target"] in take):
            new.setdefault("edges", []).append(e)
            seen.add(t)
    return added


def names(g, types):
    return {(n.get("type"), key(n.get("name"))) for n in g.get("nodes", []) if n.get("type") in types}


def show(ref, path):
    r = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def lost(base_k, new_k, base_d, new_d):
    out = []
    if base_d and new_d is not None:
        out += [f"flow {f.get('name')!r}" for k, f in flows(base_d).items() if k not in flows(new_d)]
    if base_k and new_k is not None:
        out += [f"{t} {n!r}" for t, n in sorted(names(base_k, KEPT_TYPES) - names(new_k, KEPT_TYPES))]
    return out


def check(base, side):
    changed = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD", "--", f".migration/graphs/{side}/"],
                             capture_output=True, text=True).stdout.split()
    folders = sorted({str(pathlib.PurePosixPath(p).parent) for p in changed if p.endswith(".json")})
    problems = []
    for d in folders:
        def head(name):
            p = pathlib.Path(d) / name
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        gone = lost(show(base, f"{d}/knowledge-graph.json"), head("knowledge-graph.json"),
                    show(base, f"{d}/domain-graph.json"), head("domain-graph.json"))
        problems += [f"{d}: lost {x}" for x in gone]
    return folders, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("domain")
    d.add_argument("--previous", required=True)
    d.add_argument("--new", required=True)
    c = sub.add_parser("check")
    c.add_argument("--base", required=True)
    c.add_argument("--side", default="source")
    a = ap.parse_args(argv)
    if a.cmd == "domain":
        prev_p = pathlib.Path(a.previous)
        if not prev_p.exists() or not prev_p.read_text(encoding="utf-8").strip():
            print("no previous domain graph; nothing to preserve")
            return 0
        prev = json.loads(prev_p.read_text(encoding="utf-8"))
        new_p = pathlib.Path(a.new)
        new = json.loads(new_p.read_text(encoding="utf-8"))
        added = merge_domain(prev, new)
        new_p.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
        for name in added:
            print(f"kept flow from the committed graph: {name}")
        print(f"AFS-RESULT gate=graph-preserve flows_kept={len(added)} flows_now={len(flows(new))}")
        return 0
    folders, problems = check(a.base, a.side)
    for p in problems:
        print(f"::error::{p} (the {a.side} graph only grows, ADR-0033)")
    print(f"AFS-RESULT gate=graph-preserve side={a.side} folders={len(folders)} lost={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
