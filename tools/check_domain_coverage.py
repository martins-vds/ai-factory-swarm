#!/usr/bin/env python3
"""Verify requested source entry points have a connected, source-backed domain flow."""
import argparse
import collections
import json
import pathlib
import sys

from check_graph import BACKWARD, FORWARD


def validate_entry_points(root, entry_points):
    """Return canonical source-relative file paths, rejecting missing or escaping paths."""
    try:
        source_root = pathlib.Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"source root is not accessible: {root}") from exc
    if not source_root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")

    validated = []
    for raw in entry_points:
        if not isinstance(raw, str) or not raw or raw != raw.strip() or any(ord(c) < 32 for c in raw):
            raise ValueError(f"invalid source entry point: {raw!r}")
        if "\\" in raw:
            raise ValueError(f"source entry point must use a relative POSIX path: {raw!r}")
        rel = pathlib.PurePosixPath(raw)
        if rel.is_absolute() or any(part in ("", ".", "..") for part in raw.split("/")):
            raise ValueError(f"source entry point must stay inside the source root: {raw!r}")
        try:
            resolved = (source_root / pathlib.Path(*rel.parts)).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"source entry point does not exist: {raw!r}") from exc
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(f"source entry point resolves outside the source root: {raw!r}") from exc
        if not resolved.is_file():
            raise ValueError(f"source entry point is not a file: {raw!r}")
        validated.append(rel.as_posix())
    return list(dict.fromkeys(validated))


def _reachable_from(starts, edges, known_ids):
    adjacent = collections.defaultdict(list)
    for edge in edges:
        source, target, kind = edge.get("source"), edge.get("target"), edge.get("type")
        if source not in known_ids or target not in known_ids:
            continue
        if kind in FORWARD:
            adjacent[source].append(target)
        elif kind in BACKWARD:
            adjacent[target].append(source)
    reached = set(starts)
    queue = collections.deque(starts)
    while queue:
        for target in adjacent[queue.popleft()]:
            if target not in reached:
                reached.add(target)
                queue.append(target)
    return reached


def coverage_failures(root, knowledge_graph, domain_graph, entry_points):
    """Return explicit failures unless each request has a connected, source-backed flow."""
    try:
        requested = validate_entry_points(root, entry_points)
    except (OSError, RuntimeError, ValueError) as exc:
        return [str(exc)]
    if not requested:
        return []
    if not isinstance(knowledge_graph, dict):
        return ["knowledge graph is missing or invalid"]
    if not isinstance(domain_graph, dict):
        return ["domain graph is missing or invalid"]

    source_nodes = knowledge_graph.get("nodes")
    domain_nodes = domain_graph.get("nodes")
    source_nodes = [n for n in source_nodes if isinstance(n, dict)] if isinstance(source_nodes, list) else []
    domain_nodes = [n for n in domain_nodes if isinstance(n, dict)] if isinstance(domain_nodes, list) else []
    source_by_id = {n.get("id"): n for n in source_nodes if isinstance(n.get("id"), str)}
    domain_by_id = {n.get("id"): n for n in domain_nodes if isinstance(n.get("id"), str)}
    all_source_ids = set(source_by_id)
    source_by_path = collections.defaultdict(list)
    for node in source_nodes:
        path = node.get("filePath")
        if isinstance(path, str):
            source_by_path[path].append(node)

    edges = domain_graph.get("edges")
    source_edges = knowledge_graph.get("edges")
    edges = [e for e in edges if isinstance(e, dict)] if isinstance(edges, list) else []
    source_edges = [e for e in source_edges if isinstance(e, dict)] if isinstance(source_edges, list) else []
    source_reachability = {}
    failures = []

    for entry_point in requested:
        starts = source_by_path.get(entry_point, [])
        if not starts:
            failures.append(f"{entry_point}: no source-graph node has this exact filePath")
            continue
        if entry_point not in source_reachability:
            source_reachability[entry_point] = _reachable_from(
                [node["id"] for node in starts], source_edges, all_source_ids,
            )
        reached = source_reachability[entry_point]
        entry_flows = set()
        for edge in edges:
            domain_id, flow_id = edge.get("source"), edge.get("target")
            if (edge.get("type") == "contains_flow"
                    and domain_by_id.get(domain_id, {}).get("type") == "domain"
                    and domain_by_id.get(flow_id, {}).get("type") == "flow"):
                flow = domain_by_id[flow_id]
                meta = flow.get("domainMeta")
                if isinstance(meta, dict) and meta.get("entryPoint") == entry_point:
                    entry_flows.add(flow_id)

        covered = False
        for edge in edges:
            flow_id, step_id = edge.get("source"), edge.get("target")
            step = domain_by_id.get(step_id)
            if (edge.get("type") != "flow_step" or flow_id not in entry_flows
                    or step is None or step.get("type") != "step"):
                continue
            step_path = step.get("filePath")
            if not isinstance(step_path, str) or not step_path:
                continue
            try:
                backed_path = validate_entry_points(root, [step_path])[0]
            except (OSError, RuntimeError, ValueError):
                continue
            if backed_path != step_path:
                continue
            backing_nodes = source_by_path.get(step_path, [])
            if any(node["id"] in reached for node in backing_nodes):
                covered = True
                break

        if not covered:
            failures.append(
                f"{entry_point}: no connected domain -> flow -> source-backed step reaches this "
                "entry point through the knowledge graph"
            )
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="analyzed source root")
    parser.add_argument("--knowledge", required=True, help="knowledge-graph.json")
    parser.add_argument("--domain", required=True, help="domain-graph.json")
    parser.add_argument("--domain-entry-point", action="append", default=[], metavar="PATH",
                        help="requested source-relative entry-point file path")
    args = parser.parse_args()
    if not args.domain_entry_point:
        print("domain coverage: SKIP (no requested entry points)")
        return 0
    try:
        with open(args.knowledge, encoding="utf-8") as source:
            knowledge = json.load(source)
    except (OSError, ValueError) as exc:
        knowledge = None
        load_error = f"cannot read knowledge graph: {exc}"
    else:
        load_error = None
    try:
        with open(args.domain, encoding="utf-8") as source:
            domain = json.load(source)
    except (OSError, ValueError) as exc:
        domain = None
        domain_error = f"cannot read domain graph: {exc}"
    else:
        domain_error = None

    failures = [error for error in (load_error, domain_error) if error]
    if not failures:
        failures = coverage_failures(args.root, knowledge, domain, args.domain_entry_point)
    if failures:
        for failure in failures:
            print(f"domain coverage: FAIL: {failure}", file=sys.stderr)
        return 1
    print("domain coverage: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
