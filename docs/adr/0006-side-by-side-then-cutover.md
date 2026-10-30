# ADR-0006: Automated checks first, human side-by-side per slice, final UAT, single cutover

- Status: Accepted
- Date: 2026-10-30

## Context
Teams migrating legacy systems often lack expertise in the old code or find it hard to change, so
incremental production releases that bridge old and new code (strangler-fig) are frequently
impractical. A safe fallback is still required. Side-by-side comparison of the two applications can
be difficult to automate, but not impossible, and human attention is expensive.

## Decision
- Build and verify **incrementally**, slice by slice, in the target repo.
- **Automate first.** Before any human looks at a slice, it passes characterization tests,
  transcribed legacy-test behavior, the CRAP and mutation gates, and automated differential checks
  where feasible: the same inputs replayed against both applications from the same starting data,
  outputs compared after normalization. A second legacy instance on its own data copy is used for
  write comparisons where possible; otherwise only read-only requests are replayed.
- **Human side-by-side check per slice**, as part of slice acceptance: a person compares legacy and
  target for the slice's flows.
- **Final UAT** before cutover: test users exercise the whole target side by side with the running
  legacy application, on a copy of production data produced by the data-migration pipeline
  (ADR-0010). Every `review-only` capability is signed off here.
- Release as a **single cutover**. The legacy application stays available until cutover is accepted;
  that is the rollback path.

## Consequences
- No interop bridges between old and new code are needed.
- The two applications' data diverge during side-by-side periods; comparisons start from the same
  snapshot, not live sync.
- Human effort is spent on slices that already pass every automated check.
