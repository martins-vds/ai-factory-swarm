# ADR-0047: Merges and parallel dispatch go through tools

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-19
- Amends: ADR-0038 (stack refresh) and ADR-0040 (how verified work merges)
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 8; [plan](../reviews/agent-topology-plan.md),
  phase 3a

## Context
Three dispatcher rules lived only as prose in `agents/README.md` and both orchestration agents, and each
was broken at least once:
- **Stacked merges:** `merge-async` on a stacked PR merged the whole stack into `main`, unverified (pilot
  HR-04C).
- **Stack refresh:** a child PR that had already merged was merged with its base again (synthetic #123).
- **Parallel dispatch:** two tickets dispatched together owned the same file, or a new package shadowed a
  module of the same dotted name.

## Decision
1. **`tools/afs-merge`.**
   - `afs-merge work` merges a work PR into the default branch through the plain merge API. It refuses a
     draft, a stacked PR, a PR with open PRs stacked on it, any check not finished green, a workflow run
     waiting for approval, or a verified-merge check that isn't green. It never calls `merge-async`.
   - `afs-merge verifier` merges an audit Verifier's PR into the work branch it targets with
     `git merge --no-ff`, and refuses a PR that targets the default branch or a branch that isn't an open
     work PR's head.
2. **`stack_refresh.py`** leaves out merged and closed PRs even when the PR list names them, and refreshes
   stacks of any depth, parents first (now tested three deep).
3. **`tools/check_dispatch_paths.py`.**
   - It fails when two pieces of concurrent work (tickets from the plan, open PRs) own the same file, or a
     path creates a package where a module of the same dotted name exists, or the other way round.
   - Each session's own records don't count.
   - The dispatcher runs it before every parallel dispatch (`--tickets`), and the harness CI runs it on
     every PR against the other open PRs outside its own stack (`--pr`).
4. **The prose is retired.** `agents/README.md` and both orchestration agents cite the tools instead.

## Consequences
- The operator still decides every merge and approves every workflow run. The tool only refuses the
  unsafe ways, and it doesn't approve runs.
- A new CI job (`Concurrent work owns distinct files`) runs on agent PRs. It needs `gh` and the job's token.
