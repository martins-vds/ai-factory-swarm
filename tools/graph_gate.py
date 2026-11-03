#!/usr/bin/env python3
"""The code-graph gate for one side (ADR-0020): required types present, and every slice's anchors reach data.

Inputs, all in the target repo:
  .migration/graphs/<side>/full/knowledge-graph.json (+ domain-graph.json)   built and enriched by afs-understand
  .migration/profile.yaml   graph.require.<side>: {nodes: [...], edges: [...]}   (from the stack pack)
  .migration/slices/*.yaml  data_paths.<side>: [anchor, ...]   (written by the Planner; TYPE=NAME = exact match)
                            entry_points.target: [TYPE=NAME, ...]   target entry points the slice owns that
                            its data_paths don't reach (a frame, a health check, a seed command)

Data paths are directed (see check_graph.py): an anchor (a page, an endpoint, a view) must reach a table
the way the code really flows.

Ownership (target, ADR-0026): every target entry point (`endpoint` or `command` node) must belong to a
slice: reached by the flow from a slice's data_paths.target anchors, or listed in its entry_points.target.
An entry point no slice owns is a front door nobody approved (e.g. a framework's built-in admin left on by
a project template). At acceptance that fails the gate; otherwise it is a warning.

Usage:
  graph_gate.py --side source                  exit 1 on a failure; no graph yet = notice, exit 0
  graph_gate.py --side source --require-graph  also exit 1 when the graph is missing (Planner, setup)
  graph_gate.py --side target --acceptance-since origin/main
                                               enforce only when the change records an acceptance
                                               (auditor verdict: complete), like check_graph_fresh
Writes a Markdown report to stdout, then `AFS-RESULT gate=graph side=<side> verdict=<pass|fail> …`.
"""
import argparse
import collections
import json
import os
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True       # installed harness files are drift-checked (check_installed.py)
sys.path.insert(0, str(HERE))
import check_graph  # noqa: E402
import check_graph_fresh  # noqa: E402


def load_graph(side):
    folder = pathlib.Path(".migration/graphs") / side / "full"
    kg = folder / "knowledge-graph.json"
    if not kg.is_file():
        return None
    nodes, edges = [], []
    for name in ("knowledge-graph.json", "domain-graph.json"):
        p = folder / name
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            nodes += d.get("nodes", [])
            edges += d.get("edges", [])
    return nodes, edges


def anchors(side, key="data_paths"):
    out = []
    for spec in sorted(pathlib.Path(".migration/slices").glob("*.y*ml")):
        doc = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
        for a in (doc.get(key) or {}).get(side) or []:
            out.append((spec.stem, str(a)))
    return out


ENTRY_TYPES = ("endpoint", "command")


def unowned(nodes, edges):
    """Target entry points no slice owns, and listed entry points that match nothing."""
    starts = [i for _, a in anchors("target") for i in check_graph.anchor_nodes(a, nodes)]
    owned = check_graph.reachable(starts, edges)
    stale = []
    for slice_name, a in anchors("target", "entry_points"):
        hits = check_graph.anchor_nodes(a, nodes)
        owned |= set(hits)
        if not hits:
            stale.append(f"slice {slice_name}: entry_points.target `{a}` matches no node")
    entries = sorted((n for n in nodes if n.get("type") in ENTRY_TYPES), key=lambda n: (n["type"], n["name"]))
    return [n for n in entries if n["id"] not in owned], stale


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--side", choices=["source", "target"], required=True)
    ap.add_argument("--require-graph", action="store_true")
    ap.add_argument("--acceptance-since", metavar="REF")
    a = ap.parse_args(argv)
    ci = "GITHUB_ACTIONS" in os.environ
    if a.acceptance_since and not check_graph_fresh.accepting(a.acceptance_since):
        print(f"graph gate ({a.side}): not an acceptance; skipped")
        return 0
    loaded = load_graph(a.side)
    if loaded is None:
        msg = f".migration/graphs/{a.side}/full: no graph; build it with afs-understand side={a.side}"
        if a.require_graph or a.acceptance_since:
            print(f"::error::{msg}" if ci else msg, file=sys.stderr)
            print(f"AFS-RESULT gate=graph side={a.side} verdict=fail failures=1 reason=no-graph")
            return 1
        print(f"::notice::{msg}" if ci else f"notice: {msg}")
        return 0
    nodes, edges = loaded
    profile = yaml.safe_load(pathlib.Path(".migration/profile.yaml").read_text(encoding="utf-8")) or {}
    req = ((profile.get("graph") or {}).get("require") or {}).get(a.side) or {}
    ntypes = collections.Counter(n.get("type") for n in nodes)
    etypes = collections.Counter(e.get("type") for e in edges)
    by_id = {n["id"]: n for n in nodes}
    failures, out = [], [f"# Graph gate: {a.side}\n", f"- {len(nodes)} nodes, {len(edges)} edges"]
    enriched = sum(1 for e in edges if str(e.get("description", "")).startswith("afs-enriched"))
    out.append(f"- Edges added by harness enrichers: {enriched}\n")
    out.append("## Required types (profile graph.require)\n")
    for t in req.get("nodes") or []:
        out.append(f"- node `{t}`: {ntypes.get(t, 0)}")
        if not ntypes.get(t):
            failures.append(f"required node type `{t}` is absent")
    for t in req.get("edges") or []:
        out.append(f"- edge `{t}`: {etypes.get(t, 0)}")
        if not etypes.get(t):
            failures.append(f"required edge type `{t}` is absent")
    out.append("\n## Data paths (slice specs data_paths)\n")
    found = anchors(a.side)
    if not found:
        out.append("- none declared")
    for slice_name, anchor in found:
        line = check_graph.data_path(anchor, nodes, edges, by_id)
        out.append(f"- `{slice_name}` **{anchor}**: {line}")
        if line.startswith("**NO PATH**") or line.startswith("no matching node"):
            failures.append(f"slice {slice_name}: data path from `{anchor}`: {line}")
    warnings = []
    if a.side == "target":
        out.append("\n## Entry points owned by a slice (ADR-0026)\n")
        loose, stale = unowned(nodes, edges)
        owned_n = sum(1 for n in nodes if n.get("type") in ENTRY_TYPES) - len(loose)
        out.append(f"- {owned_n} owned, {len(loose)} not owned")
        problems = [f"{n['type']}={n['name']} ({n.get('filePath', '?')}) is owned by no slice: reach it from a "
                    "slice's data_paths.target or list it in its entry_points.target, or remove it" for n in loose]
        problems += stale
        for p in problems:
            out.append(f"  - {p}")
        (failures if a.acceptance_since else warnings).extend(problems)
    # Every entry point, for review: which pages/endpoints reach data at all
    entries = [n for n in nodes if n.get("type") in ("page", "endpoint", "screen")]
    reach = [n for n in entries if not check_graph.data_path(f"{n['type']}={n['name']}", nodes, edges, by_id)
             .startswith(("**NO PATH**", "no matching"))]
    out.append(f"\n## Entry points reaching data (for review)\n\n- {len(reach)} of {len(entries)} pages/endpoints")
    for n in entries:
        if n not in reach:
            out.append(f"  - no path: {n['type']} `{n['name']}`")
    out.append("\n## Gate\n")
    out.append("\n".join(f"- FAIL: {f}" for f in failures) if failures else "- PASS")
    print("\n".join(out))
    for f in failures:
        print(f"::error::graph gate ({a.side}): {f}" if ci else f"graph gate ({a.side}): {f}", file=sys.stderr)
    for w in warnings:
        print(f"::warning::graph gate ({a.side}): {w}" if ci else f"graph gate ({a.side}) warning: {w}", file=sys.stderr)
    verdict = "fail" if failures else "pass"
    print(f"\nAFS-RESULT gate=graph side={a.side} verdict={verdict} failures={len(failures)} "
          f"entry_points={len(entries)} reaching_data={len(reach)} enriched_edges={enriched}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
