# Plan: tests a customer can trust

Status: **in progress**. Started 2026-11-22. This file is updated as each step lands. Source: the review
of 2026-11-21, which asked what testing is missing and how a customer of the code can trust tests an AI
writes: little mocking, no coupling to the implementation, resistant to refactoring, and kept up for the
long run.

## Where the targets are today
Measured 2026-11-21 by grepping each target's tests, excluding characterization:

| | Pilot | Synthetic |
|---|---|---|
| Test functions (files) | 282 (48) | 70 (14) |
| Files that mock or patch | 9 | 3 |
| Patch sites | 36: mostly the clock; some own code (`worker.process_registration_attempt`, `worker.sleep`) | 6 |
| References to private names | 53: mostly Django `._meta`; some project internals (`._repository`, `._format_value`, `._process_registration_attempt_once`) | 5 |
| Interaction assertions (`assert_called…`) | 0 | 0 |
| HTTP-client or browser tests | 2 | 5 |
| Executable acceptance specs | none | none |

**What already earns trust:**
- characterization against the running legacy app;
- mutation testing on changed code;
- business rules written into the ledger before the code;
- an independent Verifier.

**What's missing:** nothing stops the code's author from writing and changing its own tests, nothing links
a rule to its test, and nothing measures coupling.

## Principles
- **Measure before tightening.** Every rule that changes agent behaviour starts with a baseline. It is then
  measured like the folds were, pinned to one model with the finish check on (ADR-0058, ADR-0060, #225).
- **Deterministic first.** A validator, the finish check or CI enforces each rule. A skill only explains
  it.
- **Behaviour, not implementation.** A customer test says what the software does, seen from outside, in the
  domain's words. It never asserts that one function calls another, and it never names internal modules.
- **The customer reads specs, not code.** Trust comes from the slice's spec as data (rule, example, status),
  run in CI by a runner the agents can't change, and written by a role other than the implementer.

## Steps
Status: ☐ not started · ◐ in progress · ☑ done (with the PR).

### Phase 0: measure (no change to agent behaviour)
| # | Gap | Step | Status |
|---|---|---|---|
| 0.1 | 3, 6 | **`afs-test-health`**: a report-only tool with an AST scan of test files. It counts patches of the project's own code against boundaries (clock, random, network, gateways), private-name access to project code, interaction assertions, and HTTP-client and browser tests. From git history it computes the *coupling ratio*: the share of commits that change production code and also have to change existing tests. | ☑ PR #227 |
| 0.2 | 6 | Run it on both targets and record the baseline below. | ☑ PR #227 |
| 0.3 | 4 | **Eval case kind `refactor`**: "restructure this module, preserving behaviour, and touch no test". It passes when no test file changes, every gate passes, and the characterization goldens still match. Every test that would have to change counts as one coupled test. | ☑ PR #228: kind `refactor`, cases `pilot-refactor-exporter` (expected coupled) and `synthetic-refactor-fee-views` (expected not); both dry-run clean |
| 0.4 | 4 | Run the refactor cases, pinned, 3 runs each, on one pilot module and one synthetic module. | ☑ 6 of 6 pass; the pilot needed 1 test file changed in every run, the synthetic none (see Baseline) |

### Phases 1–2: customer tests as data (gaps 1 and 2)
Redesigned 2026-11-22 after Matteo Vaccari's [Tests as data](https://martinfowler.com/articles/tests-as-data.html)
(martinfowler.com, 11 Nov 2026). Its argument fits this harness exactly:
- When AI writes the code and the tests, the human is the *customer*. **Customer tests**, which say what
  the software does and not how, are the contract between them.
- Keeping that contract in **data files** run by a small generic runner makes it easy to read, review and
  protect from the agent.

So the acceptance tests of phase 2 and the traceability of phase 1 become one thing: a slice's behaviour
written as tables and scenarios in the domain's language. Each row names the ledger rule it proves.

| # | Step | Status |
|---|---|---|
| 1.1 | **The spec format** (`schemas/spec.schema.json`): `.migration/spec/<slice>/*.yaml`, with two forms. A **table** is stateless rows of `input → expected`. A **scenario** is `given` (seed state) → `when` (one action through a public entry point: an HTTP request, a use case or a command) → `then` (expected response and resulting state). Every case carries `rule:` (a ledger rule id) and a mandatory, non-empty `then`/`expect`, so an empty or assertion-free case can't be written. The domain's words are used, with no module, class or function names. | ☑ PR #230: schema, ADR-0061 |
| 1.2 | **The runner** (`afs-spec`, harness-owned): it interprets the files through the stack pack's adapter. For Django: the test client for HTTP, the management command runner, side-channel seeding through fixtures. A **printer** turns responses and state into stable text, so a failure is a readable diff. The runner is harness code, installed and drift-checked like the other tools (`check_installed`), so a target agent can't change it. | ☑ PR #230, #231; proven on the synthetic target (synthetic PR #150): CI ran 10 fee cases through the Django adapter, all passed, and a deliberately wrong fee failed with a readable message |
| 1.3 | **Traceability falls out:** `validate.py` checks that every ledger rule of a finished capability is named by at least one spec case (or `no_spec: <why>`), and that every `rule:` exists. This replaces the planned `verified_by` field. | ◐ PR #230: `validate.py` checks every `rule:` exists, and with `spec.required` that every rule has a case or `no_spec`. Requiring specs on a target waits for phase 2 |
| 1.4 | **Living spec:** `afs-spec --render <slice>` writes the slice's spec as one readable page with each case's last CI result. The acceptance report links it, and the human side-by-side check starts from it. | ☑ PR #230: `afs-spec render <slice>` |
| 2.1 | **Who writes the spec:** a role other than the Migrator, before implementation. The Characterizer writes it from the ledger rules and the legacy goldens, which are an independent **oracle**: the article's "alternative implementation", here the running legacy app. Rows whose expected value comes from a quirk ruling cite the ruling, so a spec never silently preserves a legacy bug. ADR. | ◐ PR (ADR-0062): Planner, Characterizer and the spec reference updated; each case names its `oracle` or `ruling`; unbuilt capabilities are pending. Waits for the 2.4 eval |
| 2.2 | **Protected:** a Migrator ticket may not change `.migration/spec/`. The finish check, the plan check and CI refuse it, like any out-of-scope file. A spec that is wrong is a handoff with the evidence, and the human or the Characterizer decides. | ◐ PR (ADR-0062): `check_plan.py`, the finish check and `check_return_contract.py` refuse it; `spec dispute` handoff in the Migrator prompt. Waits for the 2.4 eval |
| 2.3 | **Gates:** the spec run is a gate (`spec`) next to behaviour and regression. Mutation testing also runs against the spec runner, so a mutant that no spec case kills is reported separately: the article's point that the tests themselves need validating. | ☐ |
| 2.4 | **Eval:** one slice with the spec written first, against today's flow. It measures pass rate, the refactor-resistance result of phase 0, and how often the Migrator hands off a spec dispute. | ☐ |

Code-level unit tests stay allowed, and phase 3's lint applies to them. But the spec is what a customer
reads and trusts. Unit tests are the Migrator's own scaffolding.

### Phase 3: coupling guard (gap 3)
| # | Step | Status |
|---|---|---|
| 3.1 | `afs-test-health --check` on changed test files. It finds: patching project code; private access to project code (allowlist: `_meta`); interaction assertions on project code. An inline `# afs: allow-mock <why>` exempts a line. | ☐ |
| 3.2 | The finish check and CI run it, report-only first. | ☐ |
| 3.3 | Turn it on as a blocking rule after one eval shows no pass-rate loss. | ☐ |

### Phase 4: test types a migration needs (gap 5)
| # | Step | Status |
|---|---|---|
| 4.1 | **Property-based tests** (Hypothesis) for rules with arithmetic or ranges. The spec format gets a `property` form (for all inputs in a range, an invariant holds), run by the same runner. The stack pack pins Hypothesis. | ☐ |
| 4.2 | **Differential tests**: replay recorded legacy inputs against the target on every PR, from the tier-A characterization recordings, and compare normalized outputs. **Partly in place:** the pilot has `tests/differential/` for two slices. The step makes it the rule for every slice with tier-A characterization. | ☐ |
| 4.3 | **Contract tests** at boundaries: a schema snapshot of each REST or report contract in the ledger, and a stub contract for each gateway. | ☐ |
| 4.4 | **Architecture tests**: the domain layer imports no Django or HTTP. **Already in place** as `check_layers.py` and the profile's `layering.contracts`; the pilot has them. The step checks that every target declares contracts, and adds them to the synthetic target. | ☐ |
| 4.5 | **Browser tests**: a skill rule and a lint finding for a click followed by an immediate visibility check. LL-01 and LL-03 failed that way on 2026-11-21. | ☐ |

### Phase 5: maintenance over time (gap 6)
| # | Step | Status |
|---|---|---|
| 5.1 | The dashboard charts, per slice: mutation score, CRAP, test runtime, flaky count, coupling ratio and mock findings, from `afs-test-health` and the cost records. | ☐ |
| 5.2 | Flaky-test quarantine: a test that fails then passes on the same commit is recorded and gets a ticket instead of silently retrying. | ☐ |
| 5.3 | A periodic refactor ticket per slice, run as the phase 0 case on the live target, keeps the coupling trend honest. | ☐ |

## When to start
**Phase 0 can start now.** It changes nothing agents do, so it can't disturb the fold results or the DM
re-runs still pending. The fold eval is complete; only harness #226, its write-up, is waiting to be merged.
The DM cases need the API quota to reset, and they don't depend on this work.

**Phases 1–3 change agent behaviour.** Each starts after:
- phase 0's baseline is recorded;
- the DM re-run is done, so phase 5's must-pass set has a clean last measurement on today's harness.

Each then gets its own pinned eval before rollout to the targets.

## Baseline
`afs-test-health` on each target's `main`, 2026-11-22. The scan corrects the grep counts above: a test's own
double (`self._repository`) isn't private access, and patching an adapter to the outside world
(`fees.gateway._open`) or a logger counts as a boundary.

| | Pilot | Synthetic |
|---|---|---|
| Test files / tests (characterization excluded) | 48 / 282 | 14 / 70 |
| Own-code patches | **10** | 0 |
| Boundary patches | 25 | 6 |
| Private access to project code | **5** | 0 |
| Interaction assertions | 0 | 0 |
| Files driving the HTTP client or a browser | 19 | 7 |
| Coupling ratio | 13 of 36 = **0.36** | 2 of 7 = 0.29 |

**Where the pilot's findings are:**
- **The handling worker's tests** patch `process_registration_attempt` and `mark_registered` (5 sites).
- **The data-migration tests** reach into `exporter._format_value`, `_model_index` and
  `loader._set_deferred_references`, and patch two of them.
- **The pathfinder API test** replaces `routing_service`.

**Refactor resistance (step 0.4, runs `2026-11-22-ref-r{1,2,3}`, `gpt-6-luna`, finish check on):**

| Case | Passed | Existing tests modified (each run) | Minutes |
|---|---|---|---|
| `pilot-refactor-exporter`: move model lookup and value formatting into `schema.py` | 3 of 3 | `tests/data_migration/test_export.py`, every run | 12–13 |
| `synthetic-refactor-fee-views`: move the view helpers into `presentation.py` | 3 of 3 | none | 13–18 |

- **The pilot's coupling is exactly what `afs-test-health` flagged.** Two export tests called
  `exporter._model_index` and `exporter._format_value` directly, and one patched `exporter.apps`. Every
  run had to repoint them at `schema`, with the same assertions, and each said so in its return's
  `notes`.
- **The synthetic fee tests go through HTTP and needed nothing.**
- **So the static scan predicts refactor breakage:** the tests with private access or own-code patches
  are the ones a behaviour-preserving change breaks. That makes phase 3's lint worth having, since it
  stops new ones.

**Reading the coupling ratio:**
- It counts every production commit that edited an existing test. A real behaviour change can need that;
  a refactor shouldn't.
- About a third is the starting point. The refactor eval (step 0.3) separates the two.

## Log
- 2026-11-22: plan written. Steps 0.1 and 0.2 done in PR #227 (`afs-test-health` and the baseline). Findings: the pilot already has differential tests for two slices and layering contracts (`check_layers.py`), so steps 4.2 and 4.4 extend what exists.
- 2026-11-22: step 0.3 in PR #228. The `refactor` case kind grades the restructuring as done and records each existing test the agent had to change. A `yaml_append` normalize op adds the refactor ticket to the slice's plan.
- 2026-11-22: phases 1 and 2 redesigned as customer tests as data, after Matteo Vaccari's *Tests as data* (martinfowler.com, 11 Nov 2026), which the user pointed to.
- 2026-11-22: step 0.4 done. The refactor eval passed 6 of 6 runs. In every run the pilot's restructuring had to edit the export tests that reach into private helpers; the synthetic HTTP-level tests needed no change. Phase 0 is complete.
- 2026-11-22: phase 1 started in PR #230 (ADR-0061): the spec schema, `afs-spec` check/run/render, the Django adapter and the validator hook. The engine is tested with a fake adapter. The Django adapter needs a real run, which is next on the synthetic target.
- 2026-11-22: PR #230 merged. A trial spec on the synthetic target (fees, four cases, 11 example rows) found two gaps, fixed in PR "afs-spec: a clock from the examples": a case's clock can now come from an examples column (`{today}`), and `render` prints each case's examples as a table with a result column, so the rendered spec reads like a FIT table.
- 2026-11-22: step 1.2 proven. Synthetic PR #150 (harness `281a028`, five fee rules, a four-case spec) ran `afs-spec run` in the gates job: `gate=spec cases=10 failed=0`. A throwaway branch with one expected fee changed from $9.75 to $9.50 failed with `text: 'Fee: $9.50' not found` on that row, so the adapter can fail as well as pass. Requiring specs (`spec.required`) waits for phase 2.
- 2026-11-22: phase 2 started. Steps 2.1 and 2.2 in one PR (ADR-0062): the Characterizer writes the spec before the code, each case naming its legacy oracle or a ruling; a capability not built yet is pending in `afs-spec run`; only the Characterizer may change `.migration/spec/` (plan, finish check, CI). The agent prompts changed, so the eval repo needs a sync before 2.4.
