# ADR-0071: Test health is tracked per slice

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 5.1; ADR-0064, ADR-0070

## Context
Each harness check describes a test suite at one moment: a mutation score, a CRAP maximum, a coupling finding,
a flaky run. Maintainability is a trend. A slice whose mutation score drifts down ticket after ticket, whose
tests get slower, or whose code changes keep editing existing tests is decaying, even while every PR is green.
The operator had no single place to see that.

The data is already committed on each target:
- returns carry each ticket's mutation score;
- the `afs-run` journals carry every gate run with its duration and the tool's own result (`gate=crap max=…`);
- the flaky records (ADR-0070), the test files (ADR-0064's scan) and the spec files sit alongside them.

## Decision
1. **`afs-dashboard health --target <checkout> …`** reads each target's plans, returns, journals, flaky records,
   test files and spec. It writes two snapshots:
   - `health.json`, one row per slice: its finished Migrator tickets; mutation score from the first ticket to
     the latest; the latest ticket's highest CRAP and test runtime; flaky runs; coupled-test findings (own-code
     patches, private access, interaction and browser assertions in the slice's planned test files); the
     coupling ratio (first-parent commits changing the slice's code that also modified an existing slice test);
     and the number of customer spec cases;
   - `health-tickets.json`, one row per finished Migrator ticket in the order its return landed. This is the
     trend.
2. **Journal rows are matched by what ran, not by their label.** Sessions name gate runs freely
   (`verifier-behavior`, `my-label`). CRAP comes from the tool's own `gate=crap` result, and test runtime from
   the last passing run of the profile's `gates.tests` command.
3. **The operator dashboard gains a Test health section:** the slice table, and the ticket table filtered by
   slice. Like the eval trend, it reads snapshots from `.afs-dashboard/`. It makes no GitHub call, never writes,
   and runs from local checkouts.

## Consequences
- The pilot's slices add up to the phase 0 baseline: 10 own-code patches and 5 private accesses, all in
  `booking`, `data-migration` and `handling-registration`. The synthetic slices show 22 browser findings,
  counting each shared UI test file once per slice that plans it. They are the existing tests that ADR-0065's
  rule flags in new code.
- The trend is only as current as the checkout. The operator pulls the targets before generating, as for
  `trend --target`.
- Not covered: values that no gate records, such as total suite time in CI. Those can be added when a gate
  records them.
