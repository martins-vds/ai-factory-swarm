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
- **The customer reads specs, not code.** Trust comes from a short spec per slice (rule, example, test,
  status) that is executed in CI, and from tests that the agent implementing the code can't rewrite.

## Steps
Status: ☐ not started · ◐ in progress · ☑ done (with the PR).

### Phase 0: measure (no change to agent behaviour)
| # | Gap | Step | Status |
|---|---|---|---|
| 0.1 | 3, 6 | **`afs-test-health`**: a report-only tool with an AST scan of test files. It counts patches of the project's own code against boundaries (clock, random, network, gateways), private-name access to project code, interaction assertions, and HTTP-client and browser tests. From git history it computes the *coupling ratio*: the share of commits that change production code and also have to change existing tests. | ☑ PR #227 |
| 0.2 | 6 | Run it on both targets and record the baseline below. | ☑ PR #227 |
| 0.3 | 4 | **Eval case kind `refactor`**: "restructure this module, preserving behaviour, and touch no test". It passes when no test file changes, every gate passes, and the characterization goldens still match. Every test that would have to change counts as one coupled test. | ☐ |
| 0.4 | 4 | Run the refactor cases, pinned, 3 runs each, on one pilot module and one synthetic module. | ☐ |

### Phase 1: rule → test traceability (gap 2)
| # | Step | Status |
|---|---|---|
| 1.1 | Ledger rules get `verified_by: [tests/…::test_name]`. `validate.py` checks that each one names an existing test function. It applies to new entries only (`predates_rule`). | ☐ |
| 1.2 | The Verifier's rule check uses `verified_by`, and the mutation evidence shows that at least one listed test fails on a mutant of the rule's code. | ☐ |
| 1.3 | **Living spec**: `afs-spec <slice>` renders rule, example, test and last CI status as `.migration/evidence/<slice>/spec.md`. The acceptance report links it, and the human side-by-side check starts from it. | ☐ |

### Phase 2: tests the implementer can't rewrite (gap 1, ATDD)
| # | Step | Status |
|---|---|---|
| 2.1 | ADR: acceptance tests are written from the ledger rules before implementation, by a role other than the Migrator. Candidates are the Analyst or Characterizer, or a `*-SPEC` ticket per slice. They go under `tests/acceptance/<slice>/`. | ☐ |
| 2.2 | Scope rule: a Migrator ticket may not change `tests/acceptance/`. The finish check, the plan check and CI refuse it. A wrong acceptance test is a handoff with the evidence. | ☐ |
| 2.3 | Acceptance tests go through public entry points only (HTTP, use case, command), with no mocks except at boundaries. Phase 3's lint enforces this for that folder from day one. | ☐ |
| 2.4 | Eval: a slice with acceptance tests written first, against today's flow. It measures pass rate and the coupling ratio. | ☐ |

### Phase 3: coupling guard (gap 3)
| # | Step | Status |
|---|---|---|
| 3.1 | `afs-test-health --check` on changed test files. It finds: patching project code; private access to project code (allowlist: `_meta`); interaction assertions on project code. An inline `# afs: allow-mock <why>` exempts a line. | ☐ |
| 3.2 | The finish check and CI run it, report-only first. | ☐ |
| 3.3 | Turn it on as a blocking rule after one eval shows no pass-rate loss. | ☐ |

### Phase 4: test types a migration needs (gap 5)
| # | Step | Status |
|---|---|---|
| 4.1 | **Property-based tests** (Hypothesis) for rules with arithmetic or ranges. The Analyst marks the rule `kind: property`, the skill shows the pattern, and the stack pack pins Hypothesis. | ☐ |
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

**Reading the coupling ratio:**
- It counts every production commit that edited an existing test. A real behaviour change can need that;
  a refactor shouldn't.
- About a third is the starting point. The refactor eval (step 0.3) separates the two.

## Log
- 2026-11-22: plan written. Steps 0.1 and 0.2 done in PR #227 (`afs-test-health` and the baseline). Findings: the pilot already has differential tests for two slices and layering contracts (`check_layers.py`), so steps 4.2 and 4.4 extend what exists.
