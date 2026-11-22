# ADR-0064: A coupling guard on the test lines a branch adds

- Status: Proposed (merging the harness PR that adds it accepts it; it reports until a target sets
  `test_health.block`, which waits for step 3.3's eval)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), phase 3 (gap 3); the phase 0 baseline and refactor eval

## Context
The phase 0 baseline counted, on the pilot, 10 patches of the project's own code and 5 reaches into private
helpers. The refactor eval then showed the cost: every behaviour-preserving restructuring of the pilot's
exporter had to edit the export tests that call `exporter._format_value`. The synthetic target's tests go
through HTTP and patch only the payment gateway's network call, and they needed no change.

The customer spec (ADR-0061 to ADR-0063) now holds a slice's acceptance behaviour. The Migrator's own unit
tests remain, and nothing stops them from coupling to the implementation.

## Decision
1. **`afs-test-health --check` is the coupling guard.**
   - It scans only the lines a branch added to its test files: committed, uncommitted and untracked, against
     the merge base with `$AFS_BASE` (CI: the PR base), else `origin/main`. A test written before the guard
     is never blamed.
   - It flags three things:
     - **an own-code patch:** `patch`, `patch.object` or `monkeypatch.setattr` on the project's code, unless
       the target is a boundary;
     - **private access:** `obj._name`, or `from <project> import _name`. Framework names such as `_meta` are
       allowed, and so is `self._x`;
     - **an interaction assertion:** `assert_called*`, `call_count`, `call_args`, unless it is on a boundary
       double. `gateway.charge.assert_called_once_with(...)` checks what leaves the system, which is
       behaviour.
   - Boundaries are the clock, randomness, sleeping, the network, the environment and mail, plus anything
     named like an adapter (gateway, http, smtp, mail, logging), as in phase 0.
2. **A reasoned exemption.** A line ending in `# afs: allow-mock <why>` is exempt. The reason is required:
   a bare marker still counts. The reason is visible in the diff a reviewer reads.
3. **Report first.**
   - CI's gates job runs the guard after the gates, through `afs-run`, and annotates each finding on the PR.
   - The finish check records the findings in its trace.
   - Neither fails while the profile's `test_health.block` is off.
   - With `block: true`:
     - the CI step fails on a finding;
     - the finish check sends the session back with each line, how to rewrite it, and the exemption marker.
4. **The rule is in the contract** (`references/gates.md`, "Tests that survive a refactor"), and the
   finish-check message repeats it where the agent needs it.

## Consequences
- New unit tests that couple to the code become visible on the PR, and later refused, without touching the
  existing suite.
- The guard is a syntax check. It can't tell a well-chosen double from a poor one, and the exemption marker
  is the escape valve for the first. Its reasons are evidence for the human review.
- Step 3.3 turns it on per target only after an eval with `block: true` shows no loss of pass rate.
