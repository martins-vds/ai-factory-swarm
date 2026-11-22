# ADR-0070: A flaky test is a ticket, not a retry

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 5.2; evals 2.4 and 3.3 (LL-01 and LL-03 browser
  failures); harness #233's dashboard job, which failed on an ENOTEMPTY race and passed when re-run

## Context
A flaky test fails and then passes on the same code. Today it is handled by retrying. A session re-runs the gate
until it passes, or the operator re-runs a red CI job, as with the dashboard job on harness #233. The green
result then hides the flake, and nobody fixes it. A test that sometimes fails says nothing reliable about the
code, and the browser flakes behind LL-01 and LL-03 kept costing eval runs.

Two places can see a flake for certain:
- **an agent session:** `afs-run` already records every gate run;
- **CI:** a re-run attempt that passes on the same commit.

## Decision
1. **`afs-run` records a flake.**
   - Each run's record carries a fingerprint of the code it ran on: a git tree of the working tree, tracked and
     untracked files, with `.migration/` left out because the journal changes on every run.
   - When a command passes where the same command failed on the same fingerprint, afs-run prints `AFS-FLAKY`.
     It also appends the failure to `.migration/evidence/flaky/<ticket>.md`: the command, both times, and the
     failing test ids (pytest `FAILED`/`ERROR` lines in the failed log).
   - A pass after a code change is a fix, not a flake, and isn't recorded.
2. **The finish check sends a session back if that record isn't committed.** The gates reference asks for the
   tests to be named in the return, and for no more re-runs.
3. **`afs-flaky tickets`** runs in a new workflow, AFS flaky tests: daily, on every push of a record to main,
   and on demand.
   - It reads the committed records.
   - It also finds CI jobs that failed on one attempt and passed on a later attempt of the same run, taking the
     failing test ids from the failed attempt's log.
   - It opens one issue per test, labelled `afs-flaky` and found again by a hidden marker, or comments on the
     existing one. Evidence already on the issue isn't repeated.
   - The issue asks for a fix of the test, not a retry: `expect(...)` in a browser (ADR-0065), isolation
     (gates.md).
4. **Nothing is skipped or quarantined from the gates.** The test keeps running, so a fix is visible as soon
   as it lands. The ticket is the quarantine: the flake is named, owned and counted.

## Consequences
- Retrying stops being invisible. Each flaky test has one ticket that collects every time it flaked, from
  sessions and from CI.
- A flake that never fails twice in a row on the same code is still invisible to afs-run. CI re-runs catch some
  of the rest.
- Some flakes come from shared state between tests, not from one test. The ticket names the test that failed,
  and the fix may be elsewhere.
- The workflow needs `issues: write` and `actions: read` with the default token. No new secret.
