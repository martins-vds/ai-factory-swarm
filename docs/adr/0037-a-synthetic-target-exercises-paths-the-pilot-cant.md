# ADR-0037: A synthetic target exercises the paths the pilot can't

- Status: Accepted (martins-vds, 2026-11-07: "Merge … 122")
- Date: 2026-11-08
- Extends: ADR-0027

## Context
ADR-0027 computes harness coverage: every role, return value, ledger value, tool, workflow and label the
installed harness can produce, and whether the pilot has produced it. On 2026-11-08 the pilot stood at
82 of 104. Drills can close the open tools and workflows: each breaks one thing on purpose and checks
that the named check catches it. Nine paths are different, because they are **outcomes of real work**:

| Path | Produced when |
|---|---|
| Auditor `gaps.class: misplaced` | the target puts a responsibility in the wrong layer |
| Bootstrapper `characterization_tier: B` / `C` | the legacy app runs only partly, or not at all |
| Ledger `characterization_tier: C` | a capability can only be characterized from a spec |
| Ledger `status: deferred` | the operator defers a capability |
| Ledger `verification: review-only` | a capability has nothing executable to test |
| Program Orchestrator `dispatched.status: blocked` | a dispatch is genuinely blocked |
| Coordinator `human_check: issues` | the human side-by-side check finds a problem |
| label `wayfinder:prototype` | a decision is settled by building a prototype |

Writing these values by hand would fake the evidence. The pilot (Eclipse Cargo Tracker) runs fully, so it
will never produce tier B or C. Whether it ever produces a misplaced responsibility or a prototype decision
is luck. A harness that has never produced a path hasn't shown that the path works. One pilot can't
guarantee every path; a target built to trigger them can.

## Decision
1. **A synthetic target.** A second target repository, `ai-factory-synthetic-target`, bootstrapped by the
   harness like any other. It has its own small legacy app, built **from a scenario catalog** in the harness
   repo (`synthetic/scenarios.yaml`). Each scenario names the coverage path it's meant to produce, and the
   legacy code or setup that produces it honestly:
   - a business rule computed in a view, to be audited as `misplaced`;
   - a module whose legacy runtime can't start, so tier B;
   - a module with only a written spec, so tier C;
   - a capability the operator defers;
   - a static page with nothing to execute, so `review-only`;
   - a seeded visible defect for the human check to find, so `issues`;
   - an open design question settled by a prototype;
   - a ticket blocked on another, so the Program Orchestrator records `blocked`.
2. **Real sessions, real outcomes.** The synthetic target is migrated with the same role agents, gates and
   rules as the pilot. Nothing is written by hand. If a scenario doesn't produce its path, that is a
   finding about the harness or the scenario, and it's investigated, not patched over.
3. **The human stays human.** The human side-by-side check and approvals on the synthetic target are
   still the operator's act (ADR-0031, ADR-0036). The seeded defect is there to be found, but the operator
   finds it.
4. **Coverage is computed across targets.** `harness_coverage.py` accepts several `--repo` values and
   reports the union, with the target that produced each path. The validation goal becomes: every path
   exercised by the pilot or the synthetic target.
5. **The catalog grows with the harness.** A test fails when the harness can produce a path that no
   scenario targets and the pilot hasn't exercised. A new role value or tool ships with its scenario or
   drill.

## Consequences
- Every coverage path has a deliberate way to be exercised. "We hope the pilot hits it" no longer counts as
  validation.
- The synthetic app is small, so its slices are cheap. Its migrations cost Copilot sessions like any other.
- The operator gets a second, smaller workload: human checks and approvals on the synthetic target.
- The repo must be created by the operator, or by the dispatcher with the operator's permission. Bootstrap
  then installs the harness as on the pilot.
- To build:
  - the scenario catalog and the generator for the synthetic legacy app;
  - multi-repo `harness_coverage.py`;
  - the catalog test;
  - bootstrapping the new repo.

### Amendment (2026-11-08): one source per characterization tier

The first blind Bootstrapper built and ran `legacy/` and rated it tier A. That was correct: a payment
gateway answering 502 is behaviour of an app that runs, not a blocked build. The tier rates a whole
source, so one legacy app can only ever produce one tier.

Tiers B and C get their own sources in the synthetic repo:
- `legacy-billing/` can't be built, because a vendor library is only in a private repository. Its
  vendor-free classes and tests still compile from source, so it should rate tier B.
- `legacy-reports/` has only a specification and saved output, so it should rate tier C.

Each gets one Bootstrapper session that assesses that source and commits its return under its own ticket
id. Only `legacy/` continues past bootstrap. The catalog test checks that tiers A, B and C each have a
distinct source, and the blindness test now covers all three.
