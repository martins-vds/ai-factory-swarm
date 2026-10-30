# ADR-0005: Characterization tests first; "review-only" as the signed fallback

- Status: Accepted
- Date: 2026-10-30

## Context
Legacy systems often have few tests and may be hard to run. We cannot assume the source's own tests
are sufficient, or even runnable. Yet behavior at the equivalence boundary (ADR-0001) must be
captured before it can be preserved.

## Decision
- Generating characterization tests from the source is **mandatory** and happens before migration
  (lifecycle Phase 3).
- Behavior asserted by any existing legacy test must reappear as a test in the target, written in
  the target's idiom. The target then adds more coverage on top.
- Characterization effort is focused by the source risk map (ADR-0013). Where the stack allows,
  coverage of the source is collected while characterization runs, and the risk map is refreshed so
  complex code the characterization never reached stands out.
- Where a capability cannot reasonably be characterized, it is marked `review-only` in the fidelity
  ledger and requires a human tester's sign-off before cutover.

## Consequences
- A dedicated Characterizer role builds and maintains a harness around the source.
- Each ledger entry records which evidence rung it reached (architecture §10.1).
- Cutover is blocked until every `review-only` capability is signed off.
