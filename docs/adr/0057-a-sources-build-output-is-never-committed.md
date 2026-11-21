# ADR-0057: A source's build output is never committed

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-20
- Source: phase 5 re-runs of `synthetic-sy-01-bootstrap` (`2026-11-20-p5v-r1`, `-r2`)

## Context
With ADR-0055 the bootstrap case's setup passes, and both re-runs pass the grader. Both also committed 50
files of `legacy/target/`: classes and dependency jars from building the legacy source for
characterization.

The synthetic target keeps its legacy source in the repository (`source.lock` `path: legacy`). The pinned
copy in `.source/` is read-only, so the agent built the in-repo copy. Before bootstrap nothing ignores
build output, and bootstrap's `.gitignore` covers only the harness's own paths. Nothing the grader or CI
checks looks for it.

## Decision
1. **A stack pack names its source build's output.** `source_build_outputs` lists paths relative to the
   source root; `java-to-django` names `target/` (Maven).
2. **The setup steps exclude it locally.** When `source.lock` has a `path` (a source inside the target
   repository), the step that makes `.source` read-only also writes `/<path>/<output>` for each entry to
   `.git/info/exclude`. That works before bootstrap writes `.gitignore`.
3. **Bootstrap adds the same entries to `.gitignore`.** A separate source repository (no `path`) needs
   none: its builds happen in `.source/`, which is already ignored.

## Consequences
- An agent can build the legacy source in place for characterization without its output reaching the PR.
- A new stack pack whose source builds in place should name its build output.
- Rejected: ignoring `target/` everywhere. A target project can have a directory of that name; the
  entries are anchored to the source's path.
