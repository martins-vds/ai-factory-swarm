# ADR-0002: Three-repository topology; frozen, pinned, read-only source

- Status: Accepted
- Date: 2026-10-30

## Context
PR #6 kept the source (`SOURCE_DIR`) and output (`OUTPUT_DIR`) in one repo and relied on agent
instructions to keep the source untouched. At scale, with remote agents and many parallel PRs, an
instruction is not a sufficient guarantee, and mixing harness, legacy and new code in one repo
couples their histories.

## Decision
Use three repositories:
- **Harness** (this repo): generic role agents, skills, profile templates, bootstrap. Versioned.
- **Source**: the legacy application. **Read-only, enforced by credentials.** Frozen for the life of
  the migration and pinned to a commit SHA recorded in the target's `.migration/source.lock`.
- **Target**: the new application plus all migration state (profile, ledger, graphs, evidence,
  tickets). Agents write only via pull requests to a protected `main`.

## Consequences
- Graphs and characterization results are reproducible against the pinned SHA.
- The target carries a pinned copy of the agents and skills so remote agents running in its context
  are self-sufficient; upgrading the harness mid-migration is an explicit PR.
- Remote agents need a read-only checkout of the source in their setup steps.
- Because the source is frozen, no source-drift re-sync process is needed. If that assumption ever
  changes, add a re-graph-and-diff step that turns source changes into new tickets.
