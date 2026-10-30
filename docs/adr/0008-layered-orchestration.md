# ADR-0008: Layered orchestration with local or remote workers

- Status: Proposed
- Date: 2026-10-30

## Context
In PR #6 a single orchestrator holds the plan and ledger and personally verifies every agent result.
That works for one service but caps scale at one context window and one session.

## Decision
- **L0 Program Orchestrator:** works with the operator; owns the map, slice plan, human gates,
  escalations and cutover readiness.
- **L1 Slice Coordinators:** one per active slice; pull from the frontier, dispatch workers, verify
  evidence, run slice acceptance.
- **L2 Workers:** Migrators, Specialist Migrators and Verifiers, one per ticket.
- Workers are launched through a **dispatch adapter**: locally as subagents, or remotely as cloud agents
  working a ticket in the target repo and reporting back through the PR and ticket.
- All state lives in the tracker and `.migration/`; every operation is idempotent and resumable from
  the ticket alone.

## Consequences
- No agent needs the whole migration in context.
- Concurrency (number and mix of workers) is an operator-set profile value.
- The first remote runner(s) to support are still open (architecture §13).
