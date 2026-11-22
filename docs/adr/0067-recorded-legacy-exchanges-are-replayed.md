# ADR-0067: Recorded legacy exchanges are replayed

- Status: Proposed (merging the harness PR that adds it accepts it; it applies where the profile sets
  `spec.required`)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 4.2; ADR-0061, ADR-0062

## Context
Step 4.2 asked for differential tests: the legacy app's recorded inputs replayed against the target on every
PR, with the outputs compared after normalizing. The two targets record differently:
- **Pilot:** hand-written differential tests for two slices, `tests/differential/`. Each has its own code for
  normalizing dates and extracting embedded map data. It also has raw HTTP captures of the pathfinder
  service, prose observations of JSF screens, and ad-hoc JSON tables.
- **Synthetic:** one clean format: named exchanges, each a request (method, path, form) and a response
  (status, body).

Hand-written differential tests are code the Migrator owns and can bend. The customer spec (ADR-0061) is
already data the Migrator can't change, and its cases name an oracle (ADR-0062). The missing piece was a way
for the recording itself to be the expected value, instead of values copied from it by hand.

## Decision
1. **The spec gains a replay case.**
   - `when.replay: {recording, exchange}` names one exchange in a JSON recording.
   - The runner sends the recorded request through the stack's adapter, and expects the recorded status
     unless the case gives one.
   - `then.replay` compares the body: `exact` (line endings and trailing spaces normalized), `text` (markup
     dropped, entities decoded, whitespace collapsed), `json` (structural equality), or `ignore` (status only).
   - `mask` lists regular expressions replaced on both sides, for values that differ by design.
   - A failure prints the recorded and the target's bodies.
   - A replay is its own oracle, and examples can name many exchanges in one case.
2. **With `spec.required`, a tier-A capability with a spec replays at least one exchange.** Tier A means its
   exchanges were recorded from the running legacy app. Otherwise its ledger entry says why none can be
   replayed (`no_replay: <why>`). A JSF conversation whose steps depend on server state is the usual reason,
   and the pilot's prose observations are an example.
3. **The pilot's hand-written differential tests stay.** They cover what a single exchange can't, such as map
   data embedded in a page. New slices put recorded exchanges in the replay format.

## Consequences
- The synthetic fees spec replays four recorded exchanges: L3's fee, L1 capped at $10 on the recording's date,
  L2 returned early, and an unknown loan. They passed against the target in CI on a trial branch
  (`gate=spec cases=14 failed=0`).
- On every PR, the spec gate now compares the target with the legacy app directly, for every capability whose
  exchanges were recorded.
- The pilot's existing tier-A capabilities have no spec yet. Each gets a replay case or a `no_replay` reason
  when its Characterizer spec ticket is planned.
- Not covered: stateful flows, which stay `no_replay`. They need recorded sequences, not single exchanges. That
  can come later if a target needs it.
