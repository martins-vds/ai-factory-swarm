# Role agents

GitHub Copilot custom agents (`*.agent.md`) for the ten roles in
[docs/architecture.md §4](../docs/architecture.md#4-agent-roles). Bootstrap copies them, pinned, into each
target repo's `.github/agents/` (ADR-0008). They run locally (VS Code / Copilot CLI) or remotely (assign an
issue to the Copilot coding agent and pick the agent).

| Agent | Layer | Phase | Writes |
|---|---|---|---|
| [`afs-program-orchestrator`](afs-program-orchestrator.agent.md) | L0 | all | tracker, `.migration/` decisions |
| [`afs-bootstrapper`](afs-bootstrapper.agent.md) | L0 | 1 | setup PR (profile, capabilities, installs, scaffold) |
| [`afs-analyst`](afs-analyst.agent.md) | L1 | 2 | graphs, ledger, risk map |
| [`afs-characterizer`](afs-characterizer.agent.md) | L1 | 3 | characterization suite, ledger evidence |
| [`afs-planner`](afs-planner.agent.md) | L1 | 4 | draft slice plan |
| [`afs-slice-coordinator`](afs-slice-coordinator.agent.md) | L1 | 5–6 | tracker, slice evidence report |
| [`afs-migrator`](afs-migrator.agent.md) | L2 | 5 | target code, one PR per ticket |
| [`afs-specialist-migrator`](afs-specialist-migrator.agent.md) | L2 | 5 | data / UI / messaging, one PR per ticket |
| [`afs-verifier`](afs-verifier.agent.md) | L2 | 5 | tests and a verdict (never production code) |
| [`afs-auditor`](afs-auditor.agent.md) | L1/L0 | 6–7 | audit reports and gap tickets (read-only) |

## Where each role can run
A remote session (Copilot coding agent) can read the repo and the source, run commands, and push
commits to its own branch and PR. It cannot reliably comment, create or label issues, assign issues, or
edit its PR description after opening it, and it has no user token. So:

- **Tracker writes and dispatch** (assigning a ticket to Copilot with a custom agent, opening quirk and
  gap issues, blocking edges, labels, merges) belong to whoever holds a user token: the Program
  Orchestrator locally, or the operator. A remote Slice Coordinator cannot dispatch workers; run it
  locally, or let L0 dispatch for it.
- **Everything a remote agent must leave behind is a committed file** — return file, handoff, quirk
  drafts, run journal (`afs-migration-contract` → Durable outputs). The dispatcher reads those files,
  turns quirk drafts into issues, and links them.
- **Verifier on someone else's PR:** dispatch it with `base_branch` set to the PR's head branch; its PR
  targets that branch and carries its tests, run journal and `<ticket>.afs-verifier.yaml`.
- Copilot PRs' workflow runs may wait for approval; a push by a human or L0 runs CI on them.

## Conventions (checked by `tests/test_agents.py`)
- Every agent first loads `afs-migration-contract`, then runs `afs-setup-check`.
- **Skills** lists exactly the skills `skills.lock.json` assigns to the role; agents load each only when a
  step needs it (ADR-0015).
- Sections: Inputs, Skills, Procedure, Rules, Return contract (a YAML block; the agent commits it as
  `.migration/returns/<ticket>.<role>.yaml`, validated by `schemas/return.schema.json`, generated from
  these blocks by `tools/gen_return_schema.py`).
- Files stay under 9,000 characters.
