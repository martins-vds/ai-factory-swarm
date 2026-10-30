# ADR-0013: A best-effort CRAP risk map of the source

- Status: Accepted
- Date: 2026-10-30

## Context
Some legacy code is far riskier to migrate than the rest: complex, poorly tested, brittle. Knowing
where that code is helps decide where to characterize hardest and which slices need a design step.
CRAP (ADR-0011) captures exactly that, but legacy code may have no tests, may not build easily, and
CRAP tooling may fail on it.

## Decision
- In Phase 2 the Analyst runs CRAP over the source, **best effort**, and writes a ranked **risk map**
  to `.migration/risk-map/`, linked from ledger entries.
- **It never blocks.** If the tooling fails, the failure is logged and work continues without it (or
  with a partial map).
- With no source tests, coverage is zero and CRAP reduces to a complexity ranking, still useful. After
  characterization (Phase 3), the map is refreshed with coverage collected while characterization ran,
  where the stack allows.
- The map is used by:
  - the **Characterizer**, to focus characterization on the hottest areas;
  - the **Planner**, to give hot slices an explicit design ticket;
  - **Migrators**, who redesign hot spots in the target using the architecture and refactoring skills
    (`improve-codebase-architecture`, `codebase-design`, `domain-modeling`, refactoring skills)
    instead of translating them.

## Consequences
- Risk becomes visible early and shapes the plan.
- The source is never changed; all refactoring happens in the target.
