# ADR-0001: Behavioral equivalence at observable boundaries

- Status: Accepted
- Date: 2026-10-30

## Context
A migration can aim for (a) a near-literal translation of the source structure, (b) idiomatic code
that keeps the source's module structure, or (c) freedom to re-architect as long as observable
behavior is preserved. The target should be idiomatic and follow modern design (DDD, clean
architecture, dependency injection, clean code, design patterns), which rules out (a) and constrains
(b) heavily.

## Decision
Choose (c). Equivalence is judged at the **equivalence boundary**: API requests and responses, UI
screens, flows and states, persisted data, published messages, produced files, external-system
calls, scheduled-job effects, error responses and authorization decisions. Behind the boundary the
target is free to differ completely. For the UI, what users can do is inside the boundary; how it looks
is decided separately (ADR-0014).

## Consequences
- Verification must observe behavior at the boundary (characterization tests, side-by-side runs);
  structural similarity proves nothing.
- Graph comparison changes from a node-for-node diff to a **capability-coverage** check
  (architecture §10.5).
- Target architecture decisions become first-class ADRs in the target repo and are checked by gate 3.
