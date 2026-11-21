# ADR-0055: Setup works before bootstrap, and mutation measures the working tree

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-20
- Source: phase 5 final eval, run `2026-11-20-p5z-r1`

## Context
Three cases failed in the last phase 5 run, and none of the failures was the agent's work going wrong.

- **`synthetic-sy-01-bootstrap`: setup failed before bootstrap.** The setup step "Start test services"
  runs `.migration/harness/tools/afs-services`. A repository that hasn't been bootstrapped has no harness
  tools yet, so the step failed and every later step was skipped. The agent still bootstrapped the
  repository, but it also committed `.source`, the pinned source checkout, as a gitlink: without a
  bootstrap there is no `.gitignore` to keep it out.
- **`pilot-bk-05f-fresh`: mutation said there was nothing to mutate.** `afs-mutation` listed changed files
  with `git diff <base>...HEAD`, which sees commits only. The agent ran mutation before committing its new
  view, got `score=n/a reason=no-mutable-code-changed`, and reported `n/a`. CI ran the same gate on the
  committed tree and scored 0.373 (19 killed, 32 survived). The tool told the agent that work was done
  when it wasn't.
- **`pilot-bk-05f`: Copilot timed out after the agent had finished.** The agent passed every gate
  (mutation 0.891) and handed off a genuine scope question: the route-assignment rule lives in the view,
  not the use case, and fixing that needs files outside the ticket's plan. Its last commit was at 00:10.
  Copilot's own post-processing then idled until the job's 59-minute timeout at 00:45. That isn't a harness
  defect, and this ADR changes nothing for it; the summary records it.

## Decision
1. **`afs-mutation` measures the working tree.** Changed files are those that differ from the merge base of
   the base ref and `HEAD`: committed, uncommitted and untracked files under `src`. In CI the tree is
   clean, so CI's result is unchanged. A base ref that doesn't exist falls through to the next candidate.
2. **The services step skips cleanly before bootstrap.** When `.migration/harness/tools` doesn't exist, it
   says so and passes. Once the harness is installed, a missing `afs-services` fails as before (and the
   harness check catches the broken install).
   The Understand Anything step does the same: its patches ship with the harness, and nothing builds a
   graph before bootstrap. (Added after the eval repo's own check, on a branch without the harness, failed
   at that step once the services step stopped masking it.)
3. **The source checkout is excluded locally.** The setup steps add `.source/` to `.git/info/exclude`, so
   an agent can't commit it, whether or not the repository has a `.gitignore` yet.

## Consequences
- A session that runs mutation before committing gets the same score CI will give it.
- The bootstrap case can run from the eval repo's setup steps. The eval repo's `main` needs the same setup
  steps change.
- Rejected: making the services step fail open whenever `afs-services` is missing. A half-installed harness
  should fail loudly; only the "not installed at all" state is expected.
