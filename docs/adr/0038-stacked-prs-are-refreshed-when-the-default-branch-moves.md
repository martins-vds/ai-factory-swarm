# ADR-0038: Stacked PRs are refreshed when the default branch moves

**Status:** accepted (2026-11-08)

## Context
A stacked PR targets another PR's branch: a Verifier PR on a Migrator PR, a continuation session on the
previous session's branch. `check_stack_base.py` (issue #59) rightly fails such a PR when its base no
longer contains the default branch, because CI would otherwise test stale code.

On the pilot the default branch moves several times a day. After almost every merge the operator, or
the dispatcher on their behalf, had to merge `main` into the bottom of each stack, then each branch into
the one above it, push, and wait for CI again. BK-05H, BK-05I and AM-04D each hit this. The refresh is
mechanical, it's the same every time, and it's easy to get wrong: merging in the wrong order, missing
a branch, or rerunning the old workflow, which doesn't refresh its merge commit.

## Decision
A generated workflow, `afs-stack-refresh.yml`, runs on every push to the default branch, and on demand.
`stack_refresh.py` does the refresh:

- **The stack** is every open PR whose base isn't the default branch, plus every PR whose head is the
  base of one already in it.
- **Order:** parents before children. Each branch is merged with its base only after that base is
  current. A branch that already contains its base is left alone, so no empty merge commits are made.
- **Never over an agent:** a PR titled `[WIP]` has a session pushing to it. It and every PR above it are
  skipped and reported, and get refreshed on a later push.
- **Conflicts are reported, never resolved:** the merge is aborted, the PR gets a comment naming the
  files, and the PRs above it are skipped. Conflicts are a person's or a session's job.
- **Forks** are skipped, because their branches aren't ours to push.
- **Exit codes:** the step fails (exit 1) when anything was skipped or conflicted, so the run shows
  red until the stack is current. Exit 0 means every stacked PR is current.

**The push token:** a push made with the workflow's own `GITHUB_TOKEN` starts no new workflow runs. A
"refreshed" PR whose checks never re-run would look current and be untested, which is worse than a
stale one. So the workflow requires the repository secret `AFS_STACK_TOKEN`: a fine-grained token for
this repository with Contents and Pull requests read and write. When the secret is missing, the
workflow fails with that instruction and pushes nothing.

`check_stack_base.py` stays as it is. The refresh makes the right state the usual one, and the check
still catches anything the refresh couldn't do.

## Consequences
- Stacked PRs stay current without anyone doing it by hand. A conflict or a running session shows up as
  a red refresh run and a PR comment, instead of being discovered later as a failed check.
- Merge commits authored by "AFS stack refresh" appear on work branches; the commit message names this ADR.
- Each target needs one secret. Until it's added, the workflow fails visibly and nothing else changes.
- A session that starts from a branch the refresh updated sees the merge commit like any other.
