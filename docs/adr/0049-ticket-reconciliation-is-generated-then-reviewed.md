# ADR-0049: Ticket reconciliation is generated, then reviewed

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-19
- Amends: ADR-0030 (who writes the reconciliation file)
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 3; [plan](../reviews/agent-topology-plan.md),
  phase 3c

## Context
ADR-0030 has the Slice Coordinator write `.migration/evidence/ticket-reconciliation/<epic>.yaml` by hand.
`ticket_guard.py --reconcile-epic` then checks it, using evidence it computes itself: landing PRs in the
default branch's history, and role returns that attribute to each issue. Writing by hand what a tool
already computes cost several rounds per slice of fixing a file until the check accepted it.

## Decision
1. **`tools/reconcile_epic.py`** writes the file from the same evidence.
   - **Completed issues:** each merged PR that an issue's timeline cites is paired with each role return
     it changed. `ticket_guard.completed_evidence_problems`, the function the check runs, decides which
     pairs are the issue's evidence, so the writer and the check share one implementation and can't
     disagree.
   - **Unproven issues:** an issue it can't prove, and every open or not-planned issue, is written with
     `needs_review: <why>` and empty fields, so the check keeps failing until a person decides.
2. **The coordinator reviews; it no longer writes.** It runs the tool, reviews every entry, fills in and
   clears each `needs_review`, and commits. A person still closes issues. The tool never closes anything.

## Consequences
- On synthetic epic 58 (loan-catalog), the tool proved all four issues with no review needed.
- The closing workflow and the check are unchanged.
