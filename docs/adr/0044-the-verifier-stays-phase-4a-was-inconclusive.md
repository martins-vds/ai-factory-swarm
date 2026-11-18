# ADR-0044: The Verifier stays an independent session (phase 4a was inconclusive)

- Status: Accepted (2026-11-18), to be revisited when phase 4a is re-run on cases that can show a difference.
- Source: [plan](../reviews/agent-topology-plan.md), phase 4a; [results](../../evals/results/2026-11-18-4a-summary.md)

## Context
Phase 4a compared two configurations on seven Migrator tickets, two runs each, judged by hidden oracle checks:
- **A:** the Migrator, then a separate Verifier session;
- **B:** a Migrator that verifies its own work.

Neither configuration let a defect reach a merge candidate:
- The only defect the oracle found, BK-05F's route-specification check in the view, was already on BK-05F's
  base. Every BK-05F session in both configurations handed off without a merge candidate.
- The layering, htmx-error and built-CSS defects now fail the Migrator's own idiom gate (ADR-0043), so they
  never reach a Verifier.

B cost 23% fewer minutes and 25% fewer requests. A's Verifier raised one `changes-required`, a claimed
difference from the legacy behavior in LL-02, which the oracle can't judge.

## Decision
1. Keep the Verifier as an independent session (ADR-0040 unchanged). The fold rule ("B catches every defect A
   catches") was met only because no defect occurred; a role is not folded on zero evidence (ADR-0041).
2. The Verifier's remaining job is review: rule placement (covered through the ledger, ADR-0043) and claimed
   differences from the legacy behavior.
3. Re-run phase 4a once its Migrator cases start clean (BK-05F from before its first session) and include
   cases likely to produce those defects.

## Consequences
- A ticket still costs a second session. 4a's numbers put the Verifier at about 30% of A's minutes.
- The question stays open, and its evidence gap is now explicit.
