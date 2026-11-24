# ADR-0079: A setup request carries its own clock

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-23
- Source: synthetic target #179 (HM-01), after ADR-0078; ADR-0061

## Context
After ADR-0078, HM-01 set up almost every case through `given.requests`. The expiry cases still need a hold
placed on 2026-10-24 and checked on 2026-11-23 and 2026-11-24. The case has one clock, so no request could place
the hold on the earlier day, and the Characterizer wrote a Django fixture under `.migration/spec/`. That fixture
names the model and fields the build hasn't chosen yet (`holds.hold`, `sequence`, `placed_on`). If the Migrator
models holds any other way, the fixture fails to load, and the Migrator can't change the spec. The spec would
dictate the build's schema.

## Decision
1. A setup request may carry its own `clock`. It holds while that request is sent and overrides the case's
   `clock`, which applies again for the next request and the action.
2. With `--require`, a spec for a capability whose ledger entry is `status: pending` (not built yet) may not use
   fixtures. `afs-spec check` refuses them and says to place the state by requests, with a past `clock` where
   needed. Once the capability is being built, a fixture under `.migration/spec/` is allowed again (ADR-0078).

## Consequences
- A spec written before its code sets up every case through the same public interface it judges. It names
  endpoints and dates, never tables or models.
- Setup that the public interface can't reach at all is a gap to raise with the operator, not something to
  force with a fixture.
