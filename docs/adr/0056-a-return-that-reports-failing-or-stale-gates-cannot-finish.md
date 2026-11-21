# ADR-0056: A return that reports failing or stale gates cannot finish

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-20
- Source: phase 5 re-runs of `pilot-bk-05f-fresh` (`2026-11-20-p5w-r1`, `-r2`)

## Context
ADR-0055 made `afs-mutation` measure the working tree. Both re-runs confirmed it: the agents' in-session
scores matched CI's (0.667 and 0.674; 0.839 and 0.839). Both runs still failed, and the finish check
(ADR-0034) let both stop.
- **p5w-r1 stopped with a failing gate and no handoff.** Its return said `mutation_changed: 0.667`
  against the 0.8 minimum and `handoff: none`. The finish check only asked that a score be present.
- **p5w-r2 reported a result that no longer applied.** `idiom` passed at 01:13. The agent then edited the
  code while raising mutation from 0.581 to 0.839, and never re-ran `idiom`. CI's ruff failed on a
  useless `return None` it had added.

In both cases the agent's own record held the evidence, so a check can catch it before the session stops.

## Decision
1. **Failing gates.** When a return has no handoff, the finish check refuses it if a gate reports a
   non-zero exit (`build`, `behavior`, `idiom`, `crap`, `regression`), or if `mutation_changed` is below
   the profile's `thresholds.mutation_score_min` (default 0.8). The fix is to make the gate pass or to
   hand off. `n/a: <reason>` scores are not numbers and are left alone.
2. **Stale gates.** For each numeric gate in the return, the finish check finds that gate's newest row
   in the `afs-run` journal (names compared with `-` read as `_`, by prefix, so `idiom-ruff-check` counts
   as `idiom`). It refuses the return if a code file the branch changed (anything outside `.migration/`)
   was modified after that row. A gate with no journal row is left to `validate.py`, which already
   requires one for mutation.
3. **Mutation doesn't count as an edit.** With one shard, mutmut rewrites each file in place and restores
   it. `afs-mutation` now puts back the modification time of every file whose content is unchanged, so
   gates run before mutation don't read as stale.

Both findings are mechanical, so they use the finish check's retry budget. When the budget is spent, the
session ends with a `self-check failed` handoff as before.

## Consequences
- A session can't stop on a return that CI will fail for a reason the session already knows.
- The stale check uses file modification times inside one session. A tool that rewrites code without
  changing it would make a gate look stale; mutation was the only one, and step 3 handles it.
- Rejected: recording a tree fingerprint in every journal row. That is exact, but it changes the journal
  format that CI and earlier returns trust, and the session-local times are enough to catch this.
