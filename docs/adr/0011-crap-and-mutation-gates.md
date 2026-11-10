# ADR-0011: CRAP and mutation testing as mandatory quality gates

- Status: Accepted
- Date: 2026-10-30

## Context
Coverage shows which lines tests execute, not whether tests would catch a defect, and it says nothing
about where complexity concentrates risk. Agent-written code and tests need stronger evidence.

- **CRAP** (Change Risk Anti-Patterns) per method = complexity² × (1 − coverage)³ + complexity. High
  values mark code that is both complex and poorly tested.
- **Mutation testing** makes small changes to the code and checks that the tests fail. The share of
  changes caught (mutation score) measures test strength.

Both are language-agnostic ideas; the tools differ per stack (e.g. PIT for Java, Stryker for
JavaScript/TypeScript and .NET, mutmut for Python, cargo-mutants for Rust; crap4j, or CRAP computed
from complexity + coverage reports).

## Decision
- Both are mandatory gates on the **target**:
  - **CRAP:** no method above the threshold (default **30**), checked on every PR.
  - **Mutation:** score on new and changed code ≥ threshold (default **80%**) on every PR; full
    mutation run at slice acceptance.
- Thresholds and commands are operator-set in the migration profile.
- CRAP and mutation tooling for the target stack are **required capabilities** (ADR-0012).
- The Verifier adds tests when a gate fails; it never weakens a threshold.

## Consequences
- Slower PR checks (mutation testing is expensive); limited to changed code per PR for that reason.
- Changing a threshold is a human decision recorded in the profile.

## Amendment (2026-11-10, found by synthetic LL-04)
The default test selection runs, for each mutated file, the tests whose coverage context executed it. Code
that runs at import (decorators, URL tables, module constants) belongs to no test's context, and a request
that a decorator rejects never enters the view. So the tests that kill those mutants were never selected,
and their mutants "survived" untested: LL-04's two small views scored 0.375, 5 of 8 mutants being removed
`@require_GET` decorators and mutated `urlpatterns`. Earlier Django slices showed the same survivors. A
file with import-time code now also runs its bounded context's test folder (`tests/<context>/`, for
`src/<context>/…` as well as `src/<pkg>/<context>/…`), or the whole suite when it has none.
