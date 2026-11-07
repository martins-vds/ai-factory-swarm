# ADR-0033: The source graph only grows

- Status: Accepted
- Date: 2026-11-07

## Context
On the pilot, a graph run asked for one domain entry point (the admin live map) returned a domain graph
with that **one** flow. The committed graph had nine: Register Cargo, Route Cargo, Change Destination,
Track Cargo, the handling flows and more. Its PR (pilot #212) passed every gate and a review, and merged.
The structural checks looked at the knowledge graph and at the requested flow, and nothing compared the
new domain graph with the old one. The next slice's Analyst found it: "the domain graph has only Admin
Live Cargo Map flow".

The prompt was the immediate cause: it asked for the requested entry points and didn't say to keep the
rest. But a better prompt can't be the guarantee, because Understand Anything is an LLM.

## Decision
The source is frozen (ADR-0002), so what a committed source graph describes stays true. A regeneration
may add or improve, but must not lose.
1. **Merge on generation.** On the source side, the graph workflow keeps every flow of the committed
   domain graph that the new run didn't produce, with its steps, its domain and their edges
   (`preserve_graph.py domain`). Flows match by name; where both runs have one, the new run's version wins.
2. **Check in CI.** On every PR, `preserve_graph.py check` compares each changed source graph folder with
   the base. Every domain flow must still be there, and so must every table, endpoint, page and command in
   the knowledge graph. Those node types come from the deterministic enrichers, so losing one is a
   regression, not LLM noise. A loss fails the PR and names what was lost.
3. **Prompt.** A run with requested entry points asks for the whole source's flows as well. This helps,
   but the merge is what guarantees it.

## Consequences
- A flow the LLM renames on a later run appears twice (old and new name). That's acceptable: a reviewer
  can merge them, and nothing is lost silently.
- The target graph is not covered: the target's code changes, and its graph is regenerated per slice.
- Reviewing a graph PR now means reading what the check reports, not only the requested flow.
