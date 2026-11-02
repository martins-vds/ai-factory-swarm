# ADR-0018: Ledger evidence and runtimes are checked, not trusted

- Status: Accepted
- Date: 2026-11-02

## Context
The M5 re-audit of Track Cargo (pilot #77) found two gaps that no check had caught:
- `track-cargo.data-voyage` cited 11 raw logs under `.migration/runs/`. That folder is gitignored, so
  the logs vanished with the session that wrote them. Earlier audits also found evidence pointing at
  test functions that had since been renamed.
- The profile declares `python-3.13`, but bootstrap wrote a hard-coded `3.12` into every generated
  workflow. Agent sessions and CI tested on a runtime the profile doesn't name, and nothing compared the
  two.

## Decision
1. **Evidence.** `validate.py` checks every ledger evidence item:
   - it must be a committed file, a test id `path::name`, or `legacy-test: .source/path::name`;
   - the file must exist, and a test id's name must still be defined there (a language-neutral
     `name(` or `class|def|function name` match);
   - nothing under `.migration/runs/` is accepted; cite the run journal instead;
   - `.source/` items are checked only where the source is checked out.

   Harness samples are validated with `--sample`, which skips these on-disk checks.
2. **Runtime.**
   - Bootstrap writes the Python version from the profile's `python-X.Y` stack into every workflow, and
     falls back to 3.12 only when the profile names none.
   - `tools/check_runtime.py` compares the runtimes on PATH (python, node and java) with the profile.
     It runs in CI's gates job and as `afs-setup-check` check 6. A mismatch stops the agent.

## Consequences
- Dead or stale evidence fails CI on the PR that introduces it, or on the PR that renames the test.
- A target whose profile changes its runtime gets it everywhere on the next bootstrap. Any drift fails
  fast instead of surfacing at acceptance.
