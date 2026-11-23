# ADR-0074: The spec proves every observed outcome and cites only decided rulings

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-23
- Source: operator review before the holds slice, the first slice run spec-first on a live target; ADR-0061,
  ADR-0062, ADR-0067

## Context
The customer spec is data, and `afs-spec check --require` already refused an empty `then`, an unknown rule, a
rule no case proves, and a case with neither an `oracle` nor a `ruling`. Two weak spots remained:

1. **A case could assert almost nothing.** `then: {status: 201}` passed, and nothing tied the cases to what
   the legacy app was recorded doing. A Characterizer could spec the happy path, leave out every recorded
   error, and the check passed as long as each ledger rule had some case.
2. **A ruling was only a string.** `ruling: "the operator said so"` passed. A case could cite a quirk that was
   never raised, never ruled, or ruled on another capability, and set its expected values from it. That is the
   way a legacy bug gets silently "fixed", or an invented value gets in, which ADR-0061 forbids.

Both were shown before the fix: a spec with a made-up ruling and a status-only case checked clean.

## Decision
1. **No case checks only a status.** It must also check what comes back (`text`, `json`, `replay`, ...). A 204
   or 304, which has no body, is the exception.
2. **Every recorded outcome is proved** (with `--require`, tier-A capabilities). The capability's endpoint is
   read from its ledger `source.graph_node` (`endpoint:<file>:METHOD /path`). Its recorded exchanges are the
   ones keyed `METHOD /path` or `METHOD /path <variant>`, in the ledger's `.json` evidence and the spec's replay
   recordings. Each status among them needs a case asserting that status. The error paths the Characterizer
   observed can't drop out of the spec.
3. **A ruling is a quirk raised on the capability.** `check` refuses a `ruling` that isn't `owner/repo#N`, or
   that the capability's ledger entry doesn't list under `quirks`.
4. **A ruling is decided.** `afs-spec rulings` reads each cited issue from GitHub. It must be an issue, not a pull
   request. It must be closed as completed and carry the operator's `**Ruling ...` comment. Otherwise CI fails:
   the case keeps the legacy value and its `oracle` until the operator rules. The target's harness check runs
   it with `issues: read`.
5. The Characterizer's instructions say to spec every distinct result and the recorded edges (each limit at,
   under and over; boundary dates; empty and missing input). They also say to keep a quirk with its oracle
   until it's ruled.

## Consequences
- A spec that covers only the happy path, or rests on a ruling nobody made, fails CI, whatever the session
  reports.
- Edge cases are enforced only as far as they were recorded: rule 2 proves what the legacy app was seen
  doing, so a limit the Characterizer never probed can still be missed. The instructions ask for it, and the
  holds slice checks whether they're followed.
- The ruling comment's author can't be told apart from a session using the operator's token, so rule 4
  checks the decision is recorded and the issue closed, not who typed it. Sessions never post rulings
  (they never sign off for the operator).
- Targets get the new CI step at their next stack refresh.
