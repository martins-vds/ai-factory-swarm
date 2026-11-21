# ADR-0059: An orchestrator's return keeps slice acceptance in its `acceptance` block

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-21
- Source: [fold eval](../../evals/results/2026-11-21-fold-summary.md) (ADR-0050)

## Context
After the fold (ADR-0050), the Program Orchestrator records a slice acceptance in an `acceptance` block of its
return. `check_signoff.py` and `check_slice_returns.py` read only that block for an orchestrator return, and
the retired Slice Coordinator's whole return for history.

In the fold eval, 2 of 9 folded acceptances wrote the fields elsewhere:
- **LF r1** used the retired coordinator's layout, with `slice`, `tickets` and `human_check` at the top level
  and only `report`, `gates` and `mutation_score` nested.
- **LC r2** wrote a complete block but put `human_check` outside it.

On a live target neither return's human check would register: the sign-off check would see no
`human_check` at all. `validate.py` accepted both, and the pre-fold coordinator never made the mistake.
It is the fold's only failure that the coordinator didn't share.

## Decision
1. **`validate.py` refuses an orchestrator return** that has any slice-acceptance field (`slice`,
   `tickets`, `human_check` and its companions, `report`, `gates`, `mutation_score`, `coverage_gaps`) at
   the top level alongside an `acceptance` block, `slice` or `human_check`.
2. **An `acceptance` block must hold** `slice`, `tickets`, `report`, `gates` and `human_check`.
3. **Earlier returns are exempt** (`ACCEPTANCE_BLOCK_RULE_V1`, as other return rules are). Neither target
   has an orchestrator acceptance return yet.
4. **`afs-slice-acceptance` says so in one line.** The finish check runs `validate.py`, so a session that
   gets it wrong is sent back with the fix before it stops.

## Consequences
- The fold can't produce a return the sign-off check can't read.
- Run against all nine folded returns, the rule refuses exactly the two above.
- The acceptance cases join the phase 5 re-run, to confirm the folded orchestrator with this rule.
