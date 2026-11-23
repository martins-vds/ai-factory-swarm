# ADR-0073: Tests run without the data snapshot, as in CI

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-22
- Source: the data-migration re-run, `evals/results/2026-11-22-dm-summary.md` (runs `dm-r2` and `dm-r3`,
  DM-05F); ADR-0032

## Context
Copilot's setup steps fetch the newest data snapshot into the gitignored `data.snapshot_dir`, so data tickets can
run the loader and the reconciliation on real data (ADR-0032). Production data is never committed, so CI never
has it.

In the data-migration re-run, two of three DM-05F sessions wrote invariant tests that load the snapshot from
that folder. Every gate passed in the session and failed in CI with `no manifest.json`. The third session copied
a committed fixture snapshot into `tmp_path` and passed. The agent couldn't tell its environment from CI's, and
nothing told it.

## Decision
1. **The finish check runs the branch's changed test files once with the snapshot folder hidden**, as CI runs
   them. It does this when the profile defines `data.snapshot`, the folder exists, the session is a Migrator's,
   and the tests gate is a pytest command.
   - The folder is renamed aside for the run and always renamed back. An interrupted check's leftover is
     restored at the start of the next.
   - If the files fail without the snapshot, they run again with it. Only when they pass with it is the session
     sent back: the tail of the failing output, and the fix, a small committed fixture snapshot under `tests/`
     copied into `tmp_path`.
   - A test that fails both ways is a plain failing test, which the gates already catch.
2. **`afs-data-pipeline` states the rule:** tests never read the fetched snapshot. The real snapshot is for the
   loader and the reconciliation.

## Consequences
- The DM-05F failure mode is refused in the session, with the exact fix, before the PR reaches CI.
- The cost is one run of the changed test files at stop time, and a second only when the first fails. These are
  the branch's files only, not the suite.
- Only pytest is covered. Another test runner gets the check when a target uses one.
