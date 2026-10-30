# ADR-0008: Layered orchestration; local or Copilot coding agent workers; agents live in the target repo

- Status: Accepted
- Date: 2026-10-30

## Context
In PR #6 a single orchestrator holds the plan and ledger and personally verifies every agent result.
That works for one service but caps scale at one context window and one session. The agents are
GitHub Copilot custom agents (`.github/agents/*.agent.md`).

## Decision
- **L0 Program Orchestrator:** works with the operator; owns the map, slice plan, human gates,
  escalations and cutover readiness.
- **L1 Slice Coordinators:** one per active slice; pull from the frontier, dispatch workers, verify
  evidence, run slice acceptance.
- **L2 Workers:** Migrators, Specialist Migrators and Verifiers, one per ticket.
- The same role agent file runs either **locally** (custom agent / subagent in VS Code or the Copilot
  CLI) or **remotely**, by assigning the ticket to the **Copilot coding agent** with the named custom
  agent, via the UI or API. Remote workers open a PR and report on the ticket.
- **Agents live only in the target repo**, as pinned copies installed by bootstrap. No organization-
  level agent definitions.
- All state lives in the tracker and `.migration/`; every operation is idempotent and resumable from
  the ticket alone.

- **Second remote path (spike M1-1):** a GitHub Actions job can run a role agent through the Copilot
  SDK using the workflow's own `GITHUB_TOKEN` with `copilot-requests: write` — no personal token. Use it
  for batch-style roles (Analyst, Auditor, Characterizer runs); use issue assignment for ticket-driven
  roles that deliver PRs.

## Consequences
- No agent needs the whole migration in context.
- Behavior cannot change mid-migration through an org-level edit; harness upgrades are explicit PRs.
- Remote workers need a read-only checkout of the source at the pinned SHA in their setup steps.
- Concurrency (number and local/remote mix of workers) is an operator-set profile value.
- Remote dispatch depends on the team's Copilot plan and quotas; local dispatch is always available.
