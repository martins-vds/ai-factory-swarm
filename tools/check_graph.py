#!/usr/bin/env python3
"""Check whether an Understand Anything graph has what the fidelity ledger and slice planner need.

Reads knowledge-graph.json (and domain-graph.json if given), then reports:
  * node and edge counts by type;
  * which REQUIRED node/edge types are present or missing;
  * for each --anchor (a substring of a node id, name or file path, e.g. "currency.jspx"),
    whether an end-to-end path exists from that anchor to any data node (table/schema),
    following edges in either direction, and the path found.

Gate mode (ADR-0020): with --gate, exit 1 when a --require-node/--require-edge type is absent or a
--data-path anchor has no *directed* path to data. A data path follows how the code actually flows:
routes, calls, contains, inherits, publishes, triggers, reads_from and writes_to forward, and implements
backwards (from an
interface to its implementation). The stack pack says which types its enrichers guarantee, and each
slice spec names its anchors (`data_paths`). Without --gate the exit code is 0 (a findings report).
Standard library only.

Example:
  python3 check_graph.py .ua/knowledge-graph.json --domain .ua/domain-graph.json \
      --anchor currency.jspx --anchor CurrencyTableBean > findings.md
"""
import argparse
import collections
import json
import sys

# What the ledger / slice planner rely on (architecture §8, §9).
REQUIRED_NODES = {
    "endpoint": "entry points for slices (HTTP)",
    "screen": "UI screens (ledger kind: ui)",
    "page": "UI pages (alternative to screen)",
    "table": "data capabilities and data-migration slices",
    "service": "service boundaries",
    "domain": "bounded contexts",
    "flow": "business flows → slice anchors",
    "step": "flow steps → capabilities",
}
REQUIRED_EDGES = {
    "calls": "dependency resolution",
    "reads_from": "data access (read)",
    "writes_to": "data access (write)",
    "routes": "UI/HTTP routing",
    "tested_by": "legacy test inventory",
    "contains_flow": "domain → flow",
    "flow_step": "flow → step",
}
DATA_TYPES = {"table", "schema"}


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("graph")
    ap.add_argument("--domain", help="domain-graph.json")
    ap.add_argument("--anchor", action="append", default=[], help="undirected search (findings only)")
    ap.add_argument("--data-path", action="append", default=[], metavar="ANCHOR",
                    help="directed path from this anchor to a table/schema node; TYPE=NAME matches exactly "
                         "(e.g. endpoint=/), otherwise a node's name or the end of its file path or id")
    ap.add_argument("--require-node", action="append", default=[], metavar="TYPE")
    ap.add_argument("--require-edge", action="append", default=[], metavar="TYPE")
    ap.add_argument("--gate", action="store_true", help="exit 1 on a missing required type or data path")
    a = ap.parse_args()

    g = load(a.graph)
    nodes, edges = list(g.get("nodes", [])), list(g.get("edges", []))
    if a.domain:
        d = load(a.domain)
        nodes += d.get("nodes", [])
        edges += d.get("edges", [])
    by_id = {n["id"]: n for n in nodes}
    ntypes = collections.Counter(n.get("type", "?") for n in nodes)
    etypes = collections.Counter(e.get("type", "?") for e in edges)

    out = []
    p = out.append
    proj = g.get("project", {})
    p(f"# Graph check: {proj.get('name', a.graph)}\n")
    p(f"- Commit: `{proj.get('gitCommitHash', '?')}` · analyzed {proj.get('analyzedAt', '?')}")
    p(f"- Languages: {', '.join(proj.get('languages', []))} · frameworks: {', '.join(proj.get('frameworks', []))}")
    p(f"- {len(nodes)} nodes, {len(edges)} edges, {len(g.get('layers', []))} layers\n")

    p("## Required node types\n\n| Type | Count | Needed for |\n|---|---|---|")
    for t, why in REQUIRED_NODES.items():
        p(f"| `{t}` | {ntypes.get(t, 0) or '**0**'} | {why} |")
    p("\n## Required edge types\n\n| Type | Count | Needed for |\n|---|---|---|")
    for t, why in REQUIRED_EDGES.items():
        p(f"| `{t}` | {etypes.get(t, 0) or '**0**'} | {why} |")

    p("\n## All node types\n")
    p(", ".join(f"`{t}` {c}" for t, c in ntypes.most_common()))
    p("\n## All edge types\n")
    p(", ".join(f"`{t}` {c}" for t, c in etypes.most_common()))

    adj = collections.defaultdict(list)
    for e in edges:
        s, t = e.get("source"), e.get("target")
        adj[s].append((t, e.get("type"), "→"))
        adj[t].append((s, e.get("type"), "←"))

    if a.anchor:
        p("\n## End-to-end paths (anchor → data)\n")
    for anchor in a.anchor:
        al = anchor.lower()
        starts = [n["id"] for n in nodes if al in n["id"].lower() or al in str(n.get("name", "")).lower()
                  or al in str(n.get("filePath", "")).lower()]
        if not starts:
            p(f"- **{anchor}**: no matching node — MISSING")
            continue
        prev = {s: None for s in starts}
        queue = collections.deque(starts)
        hit = None
        while queue and not hit:
            cur = queue.popleft()
            if by_id.get(cur, {}).get("type") in DATA_TYPES:
                hit = cur
                break
            for nxt, et, direction in adj[cur]:
                if nxt not in prev:
                    prev[nxt] = (cur, et, direction)
                    queue.append(nxt)
        if not hit:
            p(f"- **{anchor}**: {len(starts)} node(s) matched; no path to a table/schema node")
            continue
        chain, cur = [], hit
        while prev[cur] is not None:
            parent, et, direction = prev[cur]
            chain.append(f"`{by_id.get(cur, {}).get('name', cur)}`")
            chain.append(f"{direction}{et}")
            cur = parent
        chain.append(f"`{by_id.get(cur, {}).get('name', cur)}`")
        p(f"- **{anchor}**: " + " ".join(reversed(chain)))

    failures = []
    for tname in a.require_node:
        if not ntypes.get(tname):
            failures.append(f"required node type `{tname}` is absent")
    for tname in a.require_edge:
        if not etypes.get(tname):
            failures.append(f"required edge type `{tname}` is absent")
    if a.data_path:
        p("\n## Data paths (directed: anchor → code → data)\n")
    for anchor in a.data_path:
        line = data_path(anchor, nodes, edges, by_id)
        p(f"- **{anchor}**: {line}")
        if line.startswith("**NO PATH**") or line.startswith("no matching node"):
            failures.append(f"data path from `{anchor}`: {line}")
    if a.gate:
        p("\n## Gate\n")
        p("\n".join(f"- FAIL: {f}" for f in failures) if failures else "- PASS")
    print("\n".join(out))
    if a.gate:
        verdict = "fail" if failures else "pass"
        print(f"\nAFS-RESULT gate=graph verdict={verdict} failures={len(failures)} nodes={len(nodes)} edges={len(edges)}")
        return 1 if failures else 0
    return 0


FORWARD = {"routes", "calls", "contains", "inherits", "reads_from", "writes_to", "defines_schema",
           "publishes", "triggers"}     # asynchronous hops: producer → queue → consumer
BACKWARD = {"implements"}   # interface → implementation


def data_path(anchor, nodes, edges, by_id):
    ntype, sep, exact = anchor.partition("=")
    if sep and ntype.isidentifier():          # TYPE=NAME: exact name of a node of that type, e.g. endpoint=/
        starts = [n["id"] for n in nodes if n.get("type") == ntype and n.get("name") == exact]
    else:
        al = anchor.lower()
        starts = [n["id"] for n in nodes if n.get("type") not in DATA_TYPES and (
            str(n.get("filePath", "")).lower().endswith(al) or str(n.get("name", "")).lower() == al
            or n["id"].lower().endswith(al))]
    if not starts:
        return "no matching node (match a node's name, or the end of its file path or id)"
    adj = collections.defaultdict(list)
    for e in edges:
        s, t, et = e.get("source"), e.get("target"), e.get("type")
        if et in FORWARD:
            adj[s].append((t, et, "→"))
        elif et in BACKWARD:
            adj[t].append((s, et, "←"))
    prev = {s: None for s in starts}
    queue = collections.deque(starts)
    while queue:
        cur = queue.popleft()
        if by_id.get(cur, {}).get("type") in DATA_TYPES:
            chain = []
            while prev[cur] is not None:
                parent, et, d = prev[cur]
                chain.append(f"`{by_id.get(cur, {}).get('name', cur)}`")
                chain.append(f"{d}{et}")
                cur = parent
            chain.append(f"`{by_id.get(cur, {}).get('name', cur)}`")
            return " ".join(reversed(chain))
        for nxt, et, d in adj[cur]:
            if nxt not in prev:
                prev[nxt] = (cur, et, d)
                queue.append(nxt)
    return f"**NO PATH** from {len(starts)} matching node(s) to a table/schema over " \
           f"{'/'.join(sorted(FORWARD))} (implements backwards)"


if __name__ == "__main__":
    sys.exit(main())
