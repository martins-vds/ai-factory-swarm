# ADR-0077: Recorded exchanges are append-only

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-23
- Source: synthetic target #172 (SY-08, characterizing holds); ADR-0062, ADR-0076

## Context
A Characterizer recording new capabilities re-ran `--record`, which rewrote the shared recording files whole. On a
later day, every answer that depends on the date changed: a late fee went from 296 to 311 days, and loan, due and
return dates moved. These were exchanges of capabilities the ticket never touched, and they are the evidence
behind accepted work. The spec gate caught one of the eight changes, the only one a spec replays. The other seven
would have merged, silently rewriting evidence.

## Decision
`check_recordings.py --base <PR base>` runs in the target's harness check on every PR. A recording is a `.json`
file under `.migration/characterization/` whose entries (top level or one level down) have a `request` and a
`response`.
- A change may add recordings and exchanges.
- A change may not change, remove or rename an existing exchange, or delete a recording.
- Changed legacy behaviour is recorded under a new key.

The one exception is a change that itself moves the source pin (the profile's `source.sha`, ADR-0076).

## Consequences
- Characterization harnesses must merge new exchanges into existing recordings, or write new files, rather than
  rewrite them.
- Evidence for accepted capabilities can't drift with the calendar.
- Re-recording after a re-pin happens in a later Characterizer PR, which doesn't move the pin. So new behaviour
  after a re-pin goes under new keys, and the old recordings stay as the record of the old source.
