# ADR-0009: Source and target graphs from a third-party tool, behind an adapter

- Status: Accepted
- Date: 2026-10-30

## Context
Agents need a graph of the source (and later the target) to plan slices, resolve dependencies and
check capability coverage. Building a graph engine is out of scope; tools such as Understand Anything
and Graphify already exist and are evolving.

## Decision
Use a third-party graph tool. Agents reach it through a **graph adapter** that exposes a minimum set
of operations: build a graph for a directory at a commit, query nodes and edges, list entry points
(endpoints, UI screens, jobs), explain a node, and diff two snapshots. The active tool is set in the
migration profile.

## Consequences
- Graph snapshots are stored in the target repo under `.migration/graphs/` for reproducibility.
- The graph is the primary interface to the code but not infallible: agents verify against source
  when the graph and code disagree, and regenerate the graph when it is wrong (carried over from
  PR #6).
- The exact minimum schema is an open question (architecture §13).
