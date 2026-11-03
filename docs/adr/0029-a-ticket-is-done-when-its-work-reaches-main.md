# ADR-0029: A ticket is done when its work reaches the default branch

- Status: Accepted
- Date: 2026-11-03

## Context
A closed ticket is read as done: its blocking edges lift, the next tickets get dispatched, and the
slice-epic check (ADR-0024) counts it. On the pilot, tickets closed before their work reached `main`, twice:
1. **HR-04A/B:** re-assigning the work ticket to the Verifier connected the Verifier's PR to it. Merging that
   PR into the work branch closed the ticket. (Fix: each Verifier gets its own issue, ai-factory-swarm#51.)
2. **HR-04C:** the Verifier had its own issue, but merging its PR into the work branch, which GitHub treats as
   a stacked merge (`merge-async`), still closed the work ticket, one second before the Verifier's own issue.

GitHub decides when to close linked issues, and the rules differ by merge path. The harness can't control
that, but it can refuse the wrong outcome.

## Decision
The **AFS ticket guard** workflow runs `tools/ticket_guard.py` whenever an issue closes as *completed*. If an
**open PR into the default branch** still says it fixes, closes or resolves that issue, the issue is reopened
with a comment naming the PR. It closes again when that PR merges, because the PR still says it fixes it.
Closing as *not planned*, or with no such PR, is left alone.

## Consequences
- A ticket can't look done while its work is unmerged, whatever path closed it.
- Blocking edges and the slice-epic check see the truth without anyone reopening tickets by hand.
- Giving each Verifier its own issue (ai-factory-swarm#51) still matters: it keeps the Verifier's closure on its
  own issue.
