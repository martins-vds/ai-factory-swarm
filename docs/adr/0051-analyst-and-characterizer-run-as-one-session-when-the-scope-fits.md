# ADR-0051: The Analyst and the Characterizer run as one session when the scope fits

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-19
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 6 (part 2);
  [plan](../reviews/agent-topology-plan.md), phase 4b; [results](../../evals/results/2026-11-19-4b-summary.md)

## Context
Phase 4b compared the Analyst followed by the Characterizer (two sessions) with one "understand" session
that runs both procedures. The case was the synthetic target's member-billing source, at tier B.
- **Quality:** both configurations wrote all seven golden ledger rules and recorded all five golden
  characterization values, on both runs.
- **Cost:** the one session took about a third less time (9.8 against 14.4 minutes), with about the same
  requests.
- **The miss:** it didn't commit the Characterizer's return in either run.

The plan's rule (no worse on both runs, and finished within the session's lifetime) is met. But the case is a
four-file source, so it can't show what a fold risks on a large one: running out of a session's lifetime or
context.

## Decision
1. **Fold for a scope that fits one session.**
   - When the Planner or the orchestrator can size a scope as small (a handful of files, or one bounded
     context's flows), one session runs the Analyst's procedure, then the Characterizer's.
   - Larger scopes keep the two sessions. They are the unmeasured case, and the stop rule ("hand off after
     the Analyst's part") is the fallback either way.
2. **One return contract the finish check enforces.**
   - Before this ships, the combined session's return contract names both parts.
   - The finish check refuses a return that lacks the characterization part, so the miss 4b saw can't
     happen silently.
   - That change, and its eval on a larger scope (the synthetic `legacy` source's catalog flows), is the
     follow-up PR. The roles stay as they are until it lands.

## Consequences
- A small scope saves one session and a handoff of context.
- The two agent files stay, and the combined session reads them as skills (the 4b variant's design), so
  nothing is lost when a scope is too large.
- Until the follow-up lands, nothing changes for live targets: this ADR records the evidence and the
  direction.
- **The larger scope, measured (2026-11-21).** On the whole synthetic `legacy/` source (7 files, 17
  capabilities, tier A), one session failed 3 of 3. It never extended the characterization (0 of 6 golden
  values), wrote fewer ledger rules each run (12, 9, 8 of 14), and in one run committed no Characterizer
  return. The two sessions passed 3 of 3. That confirms decision 1: fold only a scope like phase 4b's (four
  files). Decision 2's check would catch the missing return but not a characterization that only re-runs the
  existing suite ([summary](../../evals/results/2026-11-21-fold-summary.md)).
