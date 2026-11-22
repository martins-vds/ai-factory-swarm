# ADR-0061: Customer tests are data the implementer can't rewrite

- Status: Proposed (merging the harness PR that adds it accepts it; phase 2 of the test-trust plan decides who
  writes them and protects them)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), phases 1–2; Matteo Vaccari, [Tests as
  data](https://martinfowler.com/articles/tests-as-data.html) (martinfowler.com, 11 Nov 2026)

## Context
The Migrator writes a capability's code and the tests that prove it, and can change both. The phase 0 baseline
and the refactor eval found where that goes wrong:
- **Pilot:** 10 patches of the project's own code and 5 reaches into private helpers. Every
  behaviour-preserving restructuring of the data exporter had to edit the export tests that call
  `exporter._format_value`.
- **Both targets:** no test was written in the customer's terms or linked to the ledger rule it proves.

So the person who owns the migration can trust the tests only by reading them.

The article names the fix. When AI writes the code, the human is its customer, and the contract between them
should be customer tests: what the software does, not how. Kept as data run by a small generic runner, they
are easy to read and review, and easy to protect from the agent. Its other points apply too:
- assertions must be mandatory, so a case can't be empty;
- the runner must be protected;
- expected values should come from an independent oracle. Here that is the legacy app itself, through its
  characterization goldens.

## Decision
1. **A slice's behaviour is written as data** under `.migration/spec/<slice>/*.yaml`
   (`schemas/spec.schema.json`).
   - Each file names a ledger capability.
   - Each case names the rule (or rules) it proves, sets up through side channels (fixtures, setup commands,
     the clock), acts once through a public entry point (an HTTP request or a management command), and states
     what must come back (status, JSON, text that must or must not appear, headers).
   - A `then` with no assertion is refused by the schema.
   - Tables (`examples`) give one case per row.
   - A case whose expected value comes from a quirk ruling names it (`ruling:`), so a spec never silently
     keeps a legacy bug.
   - No case names a module, class or function of the code.
2. **`afs-spec` is the runner,** and it belongs to the harness.
   - It is installed with the tools and drift-checked like them.
   - `check` validates the files, and checks that every `rule:` exists in its capability's ledger entry.
   - `run` executes the cases through the stack's adapter. `afs_spec_django.py` uses the Django test client
     and `call_command`, with one transaction per case, rolled back, on the test database.
   - A failure prints expected against actual as text.
   - `render` writes a slice's living spec: each rule, the cases that prove it and their last result.
3. **`validate.py` runs `afs-spec check`** whenever `.migration/spec/` exists.
   - With the profile's `spec.required`, every rule of a capability that has a spec file must be proved by a
     case, or carry `no_spec: <why>` in the ledger.
   - `spec.required` is off until a target's slices have specs.
4. **Not yet decided here (phase 2):**
   - who writes the spec, before implementation;
   - that a Migrator ticket may not change `.migration/spec/`;
   - that the spec run is a gate.

   Each gets its own change and eval.

## Consequences
- The customer reviews one page per slice, in the domain's words, and it is executed in CI.
- A behaviour-preserving refactor can't break a spec case, because cases reach the code only through its
  public entry points.
- The Django adapter is written without a Django runtime in the harness's CI. It is proven on the synthetic
  target before any target requires specs.
- Rejected: Gherkin with pytest-bdd. Step definitions are code an agent maintains and can bend, and they
  couple the spec to the implementation again. Plain data with a harness-owned runner avoids both.
