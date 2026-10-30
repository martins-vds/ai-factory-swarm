# ADR-0006: Incremental build, side-by-side run on a production-data copy, single cutover

- Status: Accepted
- Date: 2026-10-30

## Context
Teams migrating legacy systems often lack expertise in the old code or find it hard to change, so
incremental production releases that bridge old and new code (strangler-fig) are frequently
impractical. A safe fallback is still required.

## Decision
- Build and verify **incrementally**, slice by slice, in the target repo.
- Release as a **single cutover**.
- Before cutover, run both applications concurrently: the legacy application as is, and the target on a
  **copy of the production database**. Test users verify the target.
- The legacy application stays available until cutover is accepted; that is the rollback path.

## Consequences
- No interop bridges between old and new code are needed.
- If the target changes the data model, a data-migration pipeline from the legacy schema is a
  deliverable and is exercised by producing the copy (see architecture §13, open question 1).
- Because the target works on a copy, the two applications' data diverge during the side-by-side
  period; comparisons are made on the same starting state, not live sync.
