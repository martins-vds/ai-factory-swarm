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

## Conventions (checked by `tests/test_agents.py`)
- Every agent first loads `afs-migration-contract`, then runs `afs-setup-check`.
- **Skills** lists exactly the skills `skills.lock.json` assigns to the role; agents load each only when a
  step needs it (ADR-0015).
- Sections: Inputs, Skills, Procedure, Rules, Return contract (a YAML block the dispatcher can parse).
- Files stay under 9,000 characters.
