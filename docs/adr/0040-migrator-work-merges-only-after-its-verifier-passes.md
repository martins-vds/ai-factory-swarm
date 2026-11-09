# ADR-0040: Migrator work merges only after its Verifier passes it

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-09
- Enforces: the slice coordinator's ticket loop (`agents/afs-slice-coordinator.agent.md`, step 3)

## Context
The slice coordinator's loop says that after a migrator's PR comes back, a Verifier with a fresh context
checks it, and only work the Verifier passes goes to human review. On the pilot, that was the practice.
The Verifier's PR targeted the migrator's branch, and the migrator's PR reached `main` carrying both
returns.

Nothing checked it. On the synthetic target, LL-01's PR (#69) passed every check and was merged with no
Verifier return: the dispatcher reported it ready, and the operator merged it. LL-01 then had to be
verified after the fact, against `main` (#72). The checks made the wrong order easy.

## Decision
A new PR check, **Migrator work is verified before it merges** (`check_verified_merge.py`, in the AFS
harness check workflow):

- **Scope.** PRs whose base is the default branch. A Verifier's PR into the migrator's branch, and
  stacked PRs, are out of scope; the rule applies where work reaches the default branch.
- **Trigger.** The PR adds or changes `.migration/returns/<T>.afs-migrator.yaml` or
  `<T>.afs-specialist-migrator.yaml`.
- **Requirement.** At the PR head, `.migration/returns/<T>.afs-verifier.yaml` is a valid Verifier return
  for ticket T with verdict `pass`. Its latest change is a different, later commit than the migrator
  return's latest change: the first descends from the second. A Verifier return written in the same
  commit doesn't count, and neither does one from an earlier verification on the base branch.
- **Rework.** A migrator re-run after verification, including a fix for a Verifier's findings, changes
  the migrator return, so it needs a fresh Verifier pass before it merges.

The check reports failure until the Verifier passes, which on an open migrator PR means "waiting for
verification". Making it a required status check in branch protection turns it from a red signal into
a block; the operator checklist says so.

## Consequences
- The normal flow is unchanged: migrator PR, then a Verifier PR into the migrator's branch, then human
  review and merge of the migrator PR.
- Fix tickets for a Verifier's findings (on the pilot, #384 fixed by #385, re-verified by #389 and #390
  after #385 merged) now re-verify before the fix merges, not after.
- Work that already merged unverified (LL-01) is verified against `main` by a Verifier ticket whose PR
  targets `main`. That PR changes only the Verifier return and tests, not a migrator return, so this
  check passes it.
- The rule keys on the migrator return. A PR that changes production code without touching a migrator
  return isn't a migrator PR, and other checks cover it (return contract, gates).
