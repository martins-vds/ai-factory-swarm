# ADR-0068: Contracts are checked at the boundary

- Status: Proposed (merging the harness PR that adds it accepts it; it applies where the profile sets
  `spec.required`)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 4.3; ADR-0061, ADR-0064, ADR-0067

## Context
Step 4.3 asked for contract tests at the boundaries: a schema snapshot of each REST or report contract, and a
stub contract for each gateway. The targets' integrations differ:
- **Pilot:** a REST route-search API with randomized answers, so its values can't be fixed but its shape can;
  message queues, several now replaced by in-process calls; and map assets loaded in the browser.
- **Synthetic:** an outbound payment gateway, recorded at tier A. The recording has the requests the legacy
  app sent and how each gateway answer surfaced.

Today a Migrator tests a gateway by patching its own code: the coupling guard's one finding in eval 2.4
patched `payment_application`. A test at the real boundary, an HTTP server standing in for the gateway, checks
the same behaviour without knowing how the code is wired.

## Decision
1. **`then.schema`:** the JSON body must satisfy a JSON Schema, given inline or as a file from the repo root.
   This is the contract of an API whose values can't be fixed. A failure lists each violation by its path.
2. **`given.gateways`:** for the case, each named gateway gets a real HTTP server on 127.0.0.1
   (`tools/afs_spec_stub.py`, stack-agnostic, installed and drift-checked with `afs-spec`).
   - It answers as the case says, in order, and the last answer repeats; `unreachable: true` gives a port
     nothing listens on.
   - It records every request.
   - The profile's `spec.gateways: {<name>: {env: VAR}}` (or `setting:`, through the stack adapter) says how
     the target finds it.
3. **`then.sent`:** exactly the requests each stubbed gateway received, in order (method and path equal, body
   containing the given text). `[]` asserts the gateway was never called.
4. **With `spec.required`, an `integration` capability with a spec has a contract case** (`then.schema` or
   `then.sent`), or its ledger entry says why none can exist (`no_contract`).
5. **Smaller additions:** a replay can name the key its recording nests exchanges `under`, and a status can
   come from an examples column.

## Consequences
- The synthetic payment gateway's spec replays its recorded payments with a stub answering as the recording's
  test gateway did, and asserts the charge request the target sent. An unknown loan is never charged, and an
  unreachable gateway is reported. Its 4 cases passed against the target in CI on a trial branch, so the stub
  really was in the path.
- Gateway behaviour is specified without patching the target's code. The coupling guard (ADR-0064) and this
  step push the same way.
- Not covered: message queues and browser-loaded assets. A queue replaced in-process is `no_contract`. A real
  broker stub can come later if a target keeps one.
