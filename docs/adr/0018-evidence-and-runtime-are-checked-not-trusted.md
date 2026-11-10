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

## Durable long-running acceptance gates
Full mutation can exceed a cloud agent's lifetime; the agent's finish event is not evidence that the
gate finished. Bootstrap installs a separate manual `afs-acceptance.yml` workflow and `afs-acceptance`
runner. The job runs for up to six hours (330-minute gate step, leaving upload headroom), uses the
profile's Python/runtime/services/commands, and uploads logs, `afs-run` journal/records and a
machine-readable result even after failure or cancellation. Existing per-PR gates are unchanged.

The result binds the source SHA, Actions run/attempt, installed harness pin, profile/source-lock hashes
and tracked execution-input tree. Only audit-output Markdown, return YAML, handoff Markdown, cost JSON
and the reserved `.migration/evidence/acceptance-runs/*.json` result archives are excluded from that
tree so an Auditor can commit a report without invalidating the underlying measurement; JSON evidence
fixtures and code remain inputs. Gate execution requires clean inputs. Artifact verification rejects
changed inputs/logs, missing gates, interrupted status and
incomplete/N/A/non-full mutation accounting. It checks the unrounded killed/survived ratio against the
profile threshold as well as the tool's reported result.

Artifact hashes do not authenticate a run: the Auditor must independently verify its repository,
source SHA, workflow source, attempt and successful GitHub conclusion before importing journal rows.
No cancellation produces a successful completion row. There is no new cache/resume mechanism or
automatic verdict, evidence commit, PR creation or merge; independent coverage review, human flow
sign-off and explicit merge approval still apply.

## Amendment (2026-11-10, found by the synthetic target's circulation audit)
`validate.py` also resolves a `migrated` entry's `target.components`, the code the entry says implements it:
a repo path (a file or folder, optionally `file:symbol` or `file::symbol`), a dotted Python name with or
without the `src.` folder (module, then top-level name, then class member), a dotted template name, or a
file's target (`Makefile.run`). Text containing whitespace is prose (a library or service) and isn't
resolved. Synthetic LL-02 moved its use cases behind ports and left nine stale names; the circulation audit
caught two as `misplaced`, the catalog audit none, and no check failed on the PR that caused them. The pilot
had two more. Now the PR that moves code fails until the ledger follows.
