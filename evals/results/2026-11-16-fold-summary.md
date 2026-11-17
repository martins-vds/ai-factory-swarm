# Phase 2a fold measurement (2026-11-16, ADR-0042)

These runs measure the Specialist Migrator folded into the Migrator: harness #178, eval main #726, prepared
with `--role-map afs-specialist-migrator=afs-migrator` (#179). Five cases ran three times each and are
compared with baseline b3c by majority of three. They are the four specialty cases and one plain Migrator
case (LL-03).

## Two grades

The raw grade validates each case branch with the harness pinned in it, as CI does. In BK-05F (all three
runs) and BK-05G (run 1) that harness reports one error:

> ticket id BK-05F is already used by afs-migrator (.migration/returns/): pick a new id

Both cases are rework of a ticket the Specialist Migrator finished before the fold. The plan keeps the old
role on finished tickets (ADR-0042), so the Migrator's rework return read as a reused id. This is a gap in the
fold, not in the agent's work: on a live target it would block every rework of a pre-fold specialist ticket.
Harness #180 makes a retired role and its successor one role for ticket ids.

The discounted grade drops that one error and nothing else. In each of the four affected runs it was the only
validation error.

## Per case

| Case | b3c r1/r2/r3 | b3c majority | Fold r1/r2/r3 raw | Fold raw majority | Fold discounted r1/r2/r3 | Fold discounted majority |
|---|---|---|---|---|---|---|
| synthetic LL-03 | P P P | pass | P P P | pass | P P P | **pass** |
| pilot DM-05F (data) | P P P | pass | P P P | pass | P P P | **pass** |
| pilot BK-05F (UI) | P P P | pass | F pending F | **fail** | P pending P | **pass** |
| pilot DM-05D (data) | F P F | fail | F F F | fail | F F F | fail |
| pilot BK-05G (UI) | F F F | fail | F P F | fail | P P F | **pass** |

The two cells still pending when this was written are BK-05F r2 and BK-05G r3. Neither can change a majority:
- BK-05F r2 waits on a Gates re-run, and its return reports `n/a: no mutable code changed`.
- BK-05G r3 already fails: no return file was committed and no mutation score was reported.

## Decision

**The fold holds on the discounted grade, with #180 as a precondition.**
- Every case that passes by majority in b3c (LL-03, DM-05F, BK-05F) still passes by majority after the fold.
- BK-05G improves from fail to pass (2/3).
- DM-05D stays a fail.

On the raw grade, BK-05F fails by majority and ADR-0042's rule would reject the fold. The failure is the
plan-check gap above, which the fold introduced and #180 closes. So ADR-0042 is accepted on the condition that
#180 merges first.

## Skills

`afs-specialty` was loaded in every specialty case of every run (12 of 12). The specialty skills came with it:
- UI: `ui-ux-pro-max`.
- data: `afs-data-pipeline`, `postgresql-code-review` and `postgresql-optimization`.

LL-03 has no specialty and did not load `afs-specialty`.

## DM-05D: a case-text defect, not a fold effect

In r2 and r3 the Migrator stopped with a handoff before writing code, and its return has every gate null.
- The issue asks for "an exporter module in that app".
- The plan ticket lists only the management command and its test.
- The scope rule correctly stops the session.

This is the same defect class as LL-01 (#175), and needs the same fix: a normalize op that adds
`src/cargotracker/data_migration/exporter.py` to DM-05D's plan ticket. In r1 the Migrator wrote code, but
Gates failed.

In r2 the finish check found the empty `gates.mutation_changed` but allowed the return anyway. The pilot
profile has `self_heal.enabled: false`, so the check only records what it would have blocked.

## Next

1. Merge #180 before ADR-0042 counts as accepted.
2. Fix DM-05D's case text, as was done for LL-01.
3. Phase 2b (the Bootstrapper fold) or phase 3e (Verifier reliability). The Verifier is the weakest role by the
   b3c numbers: 1 of 6 cases pass by majority.
