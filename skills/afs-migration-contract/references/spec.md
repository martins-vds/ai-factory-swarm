# The customer spec (ADR-0061, ADR-0062)

A slice's behaviour, written as data the person who owns the migration can read: what the software does,
not how. `afs-spec` runs it through the target's public entry points. The Characterizer writes it before the
Migrator builds the code, and the Migrator can't change it.

## Who does what
| Role | With the spec |
|---|---|
| Planner | Plans one Characterizer ticket per slice whose files include `.migration/spec/<slice>/`, and blocks the slice's Migrator tickets on it. `check_plan.py` refuses a spec file in any other role's ticket, and, with the profile's `spec.required`, a Migrator ticket whose capability has no spec and no spec ticket before it. |
| Characterizer | Writes the ledger rules and the spec cases from the legacy app's recorded behaviour. |
| Migrator | Builds until every case passes. Never edits `.migration/spec/`: the finish check and CI refuse it, even with a handoff. |
| Human | Reviews the rendered spec (`afs-spec render <slice>`), rules on disputes, and may correct a spec in their own PR. |

## Writing it (Characterizer)
1. **Rules first.** For each capability in the ticket, write its business rules in the ledger entry
   (`rules: [{id, rule, source}]`): every check that refuses input or must hold, from the legacy code and
   its characterization. Ids are short and in the domain's words (`fee-capped-at-10`).
2. **One file per capability:** `.migration/spec/<slice>/<name>.yaml` (`schemas/spec.schema.json`), with
   `capability:` set to the ledger id.
3. **One case per behaviour.** Each case:
   - names the rule or rules it proves (`rule:`);
   - names its **oracle**: the recorded legacy output its expected values come from (`oracle:`, a path from
     the repo root, such as a golden file or a characterization test). The legacy app is the independent
     check on the values. A value the legacy app doesn't produce, because a quirk ruling changed it, names
     the ruling instead (`ruling: owner/repo#N`, the quirk issue listed in the ledger entry's `quirks`, closed with
     the operator's `**Ruling` comment; ADR-0074). A spec never silently keeps a legacy bug, and never invents a value;
   - sets up its starting state from the spec itself (ADR-0078): `given.requests`, setup calls through the
     public HTTP interface (each must succeed), or `fixtures` kept under `.migration/spec/<slice>/fixtures/`,
     never in files the build writes; plus setup `commands` and the `clock`. Written before the code exists,
     a spec can't know the target's schema, so prefer `requests`;
   - acts **once** through a public entry point: an HTTP request or a management command;
   - says what must come back: `status`, a `json` subset, `text` that must appear, `not_text`, `headers`.
4. **Replay what was recorded** (ADR-0067). For a tier-A capability, turn its recorded exchanges into replay
   cases instead of copying values: `when: {replay: {recording: <file>, exchange: <name>}}` and
   `then: {replay: {body: text}}`. A recording is a JSON file of (or with `under: <key>`, nesting) `{name: {request: {method, path, form?, json?,
   headers?}, response: {status, body}}}`. `body` compares `exact`, `text` (markup and whitespace dropped),
   `json`, or `ignore` (status only). `mask` lists regular expressions for values that differ by design, such
   as a date or an id. Set the clock to the recording's date when the response depends on it. With
   `spec.required`, a tier-A capability with a spec replays at least one exchange, or its ledger entry says why
   none can be replayed (`no_replay: <why>`, for example a stateful JSF conversation).
5. **Contracts at the boundary** (ADR-0068). For an `integration` capability:
   - an API whose values can't be fixed (randomized routes, generated ids): `then.schema`, a JSON Schema the
     body must satisfy, inline or a file such as `.migration/spec/<slice>/<name>.schema.json`;
   - a gateway the target calls: `given.gateways: {<name>: {respond: {status, body}}}` puts a real local HTTP
     stub in front of it (or `{unreachable: true}`). The profile's `spec.gateways: {<name>: {env: VAR}}` (or
     `setting:`) says how the target finds it. `then.sent: {<name>: [{method, path, body?}]}` lists exactly
     what the target must have sent, and `[]` means nothing.

   Take the answers and the expected requests from the recordings, which are the oracle. A replay with
   `given.gateways` covers both sides at once. With `spec.required`, an integration with a spec has such a
   case, or its ledger entry says why none can exist (`no_contract`, for example a queue replaced by an
   in-process call).
6. **Properties for invariants** (ADR-0069). A rule that holds over a whole range ("never more than $10",
   "a returned loan's fee never changes") is a property case: `forall: {today: {date: {from, to}}}` (also
   `int`, `number` with `places`, and `one_of` lists) instead of `examples`. `{name}` fills the drawn value in,
   the clock included. State the invariant with what must always hold: `then.number: {pattern, min, max}` for
   a number in the response, or `text`, `status`, `json`. The runner tries the range's edges, its middle and
   seeded random values, and reports the smallest input that fails. Keep tables for the exact values at the
   boundaries; add a property for what must hold between and beyond them.
7. **Tables for ranges.** Boundaries go in `examples` rows: zero, the last free value, the first charged one,
   the cap and past it, empty and missing input. `{column}` fills a row's value into `given`, `when` and
   `then`, the clock included.
8. **The domain's words only.** No module, class or function names, no database tables: a case must survive
   any restructuring that keeps the behaviour.
9. **Check it:** `afs-spec check --require` (through `afs-run`) passes, and `afs-spec render <slice>` reads as
   a page the customer can follow. Until the Migrator marks a capability `in-progress` or `migrated` in the
   ledger, `afs-spec run` reports its cases as pending, so your PR's checks pass before the code exists.

## The spec gate (ADR-0063)
A Migrator ticket that builds a capability with a spec reports `gates.spec`, the exit of the profile's
`gates.spec` (`afs-spec run`) through `afs-run`. Run it after the ledger marks the capability `migrated`:
before that its cases are skipped as pending, and `validate.py` refuses a run that skipped the ticket's own
capability. At slice acceptance, `afs-mutation --all --spec` runs every mutant against the spec alone; its
survivors are behaviour no customer case pins down, for the human and the next Characterizer ticket.

## A case you believe is wrong (Migrator)
Don't edit it, and don't make the code match a value you think is wrong. Write a handoff (`afs-handoff`)
whose **Blockers / questions** start with `spec dispute:` and give:
- the case (file and title, or the id `afs-spec run` printed);
- what the legacy app does instead, with the evidence (a golden, a characterization run, `file:line` in the
  source), or the quirk ruling that disagrees;
- what you built so far.

Set `handoff:` in your return and stop. The human or a Characterizer ticket corrects the spec, and your
ticket resumes against it.

A rule you find that the spec has no case for: add it to the ledger with `no_spec: found by <ticket>; needs a
Characterizer case`, and say so in your return. The rendered spec lists it under the rules no case proves
yet, where the human sees it.
