# ADR-0052: The Auditor stays

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-19
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 7; [plan](../reviews/agent-topology-plan.md),
  phase 4c

## Decision
**Keep the Auditor as its own read-only session**, run after the work at the acceptance run's exact commit.
It is the independent check after the loop:
- it re-proves every capability of the slice;
- it found the genuine `misplaced` gap in LC-AUDIT, which no ticket-level check could see.

Since ADR-0045 no Verifier follows each ticket, which leaves the Auditor as the one reviewer that isn't the
author.

Its graph-freshness and acceptance-run preconditions are tools (`check_graph_fresh.py`,
`afs-acceptance verify`). Phase 5 trimmed its prompt to those tools: 4,927 to 4,122 characters.
