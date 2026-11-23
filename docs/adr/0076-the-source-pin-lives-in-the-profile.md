# ADR-0076: The source pin lives in the profile

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-23
- Source: synthetic target #166, the first re-pin; ADR-0019, ADR-0075

## Context
Bootstrap writes `.migration/source.lock` from the profile's `source` (`repo`, `sha`, `path`). The first re-pin
edited only the lock. CI passed, and the profile still named the old commit. The next harness install wrote the
old pin back, silently undoing the re-pin. Nothing compared the two files.

## Decision
`validate.py` refuses a `source.lock` whose `repo`, `sha` or `path` differs from the profile's `source`. The
error says how to re-pin: change the profile's `source.sha` and re-run bootstrap, which writes the lock from it.
CI runs `validate.py` on every PR.

## Consequences
- A re-pin is one setup PR that changes the profile, the lock bootstrap writes from it, and whatever else
  bootstrap installs. ADR-0075 lets that PR carry the previous pin's graph.
- A lock edited by hand, or a profile edited without re-running bootstrap, fails CI.
