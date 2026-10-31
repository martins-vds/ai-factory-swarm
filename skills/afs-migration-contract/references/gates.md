# Gates

Commands come from `.migration/profile.yaml` (`gates.*`); thresholds from `thresholds.*`. Run every gate
through `afs-run` so the raw log is kept as evidence (`afs-evidence`). A gate passes only on fresh output
from this session.

| Gate | Question | When |
|---|---|---|
| 1 · Build | Compiles, loads and configures cleanly? (`gates.build`) | every PR |
| 2 · Behavior | Characterization and transcribed legacy tests pass at the boundary? (`gates.tests`) | every PR |
| 3 · Idiom & architecture | Idiomatic for the target (`gates.idiom`); conforms to target ADRs — layers, DI, domain boundaries (review with `clean-architecture`, `domain-driven-design`, `code-review`) | every PR |
| 4 · CRAP | No method above `thresholds.crap_max_per_method` (`gates.crap`) | every PR |
| 5 · Mutation | Mutation score on changed code ≥ `thresholds.mutation_score_min` (`gates.mutation_changed`); full run (`gates.mutation_full`) at slice acceptance | every PR / slice |
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

## Slice acceptance (Slice Coordinator + Auditor)
1. Slice's end-to-end characterization suite against the target.
2. Automated differential checks where a legacy environment exists (tier A); otherwise against the
   characterization tests and derived specs.
3. Full mutation run on the slice's code.
4. Target graph updated incrementally; gate 7; ledger reconciled.
5. Evidence report at `.migration/evidence/<slice>/report.md`.
6. Human side-by-side (or spec-based) check of the slice's flows.

## Project acceptance
Every slice accepted; final verification report with no unresolved gap; data pipeline rehearsed on a
fresh snapshot; every `review-only` capability signed off; cutover approved by a human.
