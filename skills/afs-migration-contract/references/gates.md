# Gates

Commands come from `.migration/profile.yaml` (`gates.*`); thresholds from `thresholds.*`. Run every gate
through `afs-run` so the raw log is kept as evidence (`afs-evidence`). A gate passes only on fresh output
from this session, or verified durable Actions output for identical execution inputs (`afs-evidence`).

| Gate | Question | When |
|---|---|---|
| 1 · Build | Compiles, loads and configures cleanly? (`gates.build`) | every PR |
| 2 · Behavior | Characterization and transcribed legacy tests pass at the boundary? (`gates.tests`) | every PR |
| 3 · Idiom & architecture | Idiomatic for the target (`gates.idiom`); conforms to target ADRs — layers, DI, domain boundaries (review with `clean-architecture`, `domain-driven-design`, `code-review`) | every PR |
| 4 · CRAP | No method above `thresholds.crap_max_per_method` (`gates.crap`) | every PR |
| 5 · Mutation | Mutation score on the **files a PR changes** ≥ `thresholds.mutation_score_min` (`gates.mutation_changed`, run by `afs-mutation`: changed files only, each mutant runs its context's tests, shards run in parallel; CI runs it too). The full run (`gates.mutation_full`) happens **once, at slice acceptance**, never per ticket | every PR / slice |
| 6 · Regression | Full suite green; earlier slices unaffected | every PR (CI) |
| 7 · Capability coverage | Every capability in scope has a target counterpart and passing evidence ([capability-coverage.md](capability-coverage.md)) | slice acceptance, final |

## Per-PR gate function (Migrator, then Verifier)
```
1 build ok? 2 behavior ok? 3 idiom ok? 4 CRAP ok? 5 mutation (changed) ok? 6 full suite ok?
all yes → open/mark the PR ready, ledger entries updated in the same PR
any no  → fix; same failure after two honest attempts → stop, handoff, escalate
```
Never weaken a threshold, skip a gate, disable a test, or use `--no-verify`. Thresholds are a human
decision recorded in the profile.

## Differential fidelity

Source observations are evidence, not permission to override an approved human decision. Before
classifying a difference, resolve the ledger, ADRs and linked quirk rulings for **every capability the
scenario observes**, including previously migrated slices. Record the applicable decisions and the
source/target revisions with the differential evidence. Missing or conflicting decisions remain
unresolved; an agent cannot approve a divergence.

Classify each case/field difference in the committed evidence report:

| Class | Required action |
|---|---|
| Approved divergence | Cite the human decision and assert its precise replacement behavior. |
| Comparison or setup defect | Repair the oracle or replay setup and rerun the affected gates. |
| Unresolved source observation or quirk | Preserve the evidence, raise/link a quirk ticket, and block only work that needs its answer. |
| Target implementation defect | Report the reproducible input, field and independently justified expected value for a Migrator to fix. |

Keep the original source goldens unchanged. Apply approved differences narrowly: never skip whole
fields, cases or objects, and never calculate expected values by calling the production behavior
under test. Use the ruling, characterized inputs and independent boundary evidence to justify the
expected result. Test that the approved replacement holds, not merely that the old value is absent.

Check observation boundaries before treating a legacy snapshot as one coherent state. Separate
endpoint reads, background processing, caches and persistence reloads may expose different states.
If an approved target transaction removes a legacy stale-state window, assert the independently
justified post-transaction state; do not make the target reproduce the stale window or ignore its
state fields. If the evidence cannot establish the expected state, report the ambiguity instead.

A passing classification is not a passing gate. Unapproved differences remain findings; failed
behavior or regression runs cannot support a `pass` verdict. Verifiers fix tests/evidence only,
never production code, and send implementation defects back to a Migrator.

## Slice acceptance (Slice Coordinator + Auditor)
1. Slice's end-to-end characterization suite against the target.
2. Automated differential checks where a legacy environment exists (tier A); otherwise against the
   characterization tests and derived specs.
3. Full mutation run on the slice's code.
4. Target graph updated incrementally; gate 7; ledger reconciled.
5. Evidence report at `.migration/evidence/<slice>/report.md`.
6. Human side-by-side (or spec-based) check of the slice's flows.

If full mutation exceeds a cloud worker's lifetime, dispatch the generated `afs-acceptance.yml`
workflow on the reviewed ref. It runs the profile's full gate outside the model session and preserves
raw logs, journal and exact-revision provenance. The Auditor verifies/imports that evidence through
`afs-evidence`; cancelled or incomplete runs never establish acceptance. This does not change per-PR
gates, human sign-off, or the requirement for explicit merge approval.

## Project acceptance
Every slice accepted; final verification report with no unresolved gap; data pipeline rehearsed on a
fresh snapshot; every `review-only` capability signed off; cutover approved by a human.
