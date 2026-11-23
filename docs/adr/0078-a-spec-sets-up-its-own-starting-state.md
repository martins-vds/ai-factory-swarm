# ADR-0078: A spec sets up its own starting state

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-23
- Source: synthetic target #179 (HM-01, the first spec written before its code); ADR-0062, ADR-0070, ADR-0074

## Context
HM-01's spec set up its cases from nine Django fixtures under `tests/holds/fixtures/`, a folder the Migrator's ticket
owns. None of them existed. A spec written before the code can't know the target's models, and the only setup it
had was fixtures or management commands, both of which the build writes. So the Migrator would have written each
case's starting state, which hands the build part of the spec that judges it. The run also exposed two
smaller faults:
- `afs-run` left all of `.migration/` out of its code fingerprint, so fixing a spec, or the characterization script
  that lives there, looked like a pass on unchanged code and was logged as flaky.
- `afs-spec rulings` needs issue access, which a session may not have. The session handed off for a gate CI already
  ran and passed.

## Decision
1. **`given.requests`:** a case can set up state with requests through the public HTTP interface (the `when.http`
   shape), sent in order after fixtures and commands. Each must answer below 400, or the case fails, naming the
   request.
2. **Fixtures belong to the spec.** `afs-spec check` refuses a fixture, including one filled in from `examples`, that
   isn't a file under `.migration/spec/` that exists now.
3. **`afs-run`'s fingerprint** leaves out only the session's own records under `.migration/` (`runs`, `evidence`,
   `costs`, `returns`, `handoffs`). The spec, ledger, characterization harness, recordings and plan count as code.
4. **`afs-spec rulings` is a CI gate.** The Characterizer leaves it to CI when the session can't read issues.

## Consequences
- A spec-first case recreates the state its legacy recording started from through the same public API the target
  must offer. It stays independent of the target's schema, and the Migrator can't shape it.
- Flaky records mean a pass on the same inputs, not a fix the session made.
