# ADR-0046: The Bootstrapper folds into the Program Orchestrator

- Status: Proposed (merging the harness PR that adds it accepts it). Eval: no flip; the bootstrap case passes 2 of 2 (runs 2b-r3, 2b-r4) after the setup-check fix ([summary](../../evals/results/2026-11-19-2b-summary.md))
- Date: 2026-11-19
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 4; [plan](../reviews/agent-topology-plan.md),
  phase 2b

## Context
The Bootstrapper ran once per migration, at intake, and its work always went back to the Program
Orchestrator. The orchestrator wrote `source.lock` and dispatched it, then reviewed its setup PR with the
operator. In a cloud session it could only do steps 1–4: Copilot may not write `.github/agents/`, so the
dispatcher always ran step 5 (`bootstrap.py`). A separate role added a session and a return contract
without adding judgment the orchestrator lacks.

Its one rule a tool enforces (tier C only after the tier-B recipe, ADR-0005) was checked on its *return*,
a file that only that role writes.

## Decision
1. **Bootstrap is a skill of the orchestrator.** `skills/afs-bootstrap/` holds the procedure: detection,
   tier, checklist, profile, test services, scaffold, graph first and validation. Step 5 (install) stays
   `tools/bootstrap.py`, which the dispatcher runs. The orchestrator's intake step runs the skill, and the
   Bootstrapper's skills (Docker, compose, `find-skills`, `skill-creator`, `self-learning`,
   `architecture-patterns`, `setup-matt-pocock-skills`) move to the orchestrator in `skills.lock.json`.
2. **The tier-C proof moves into `capabilities.yaml`.** `characterization.tier_b_attempt` is required for
   tier C, by the schema and by `validate.py`, which still checks a retired Bootstrapper return the same
   way.
3. **The role retires.** `agents/afs-bootstrapper.agent.md` is deleted, and its return contract moves to
   `agents/retired/`, so its committed returns still validate. `ticket_guard.py` and `afs-finish-check`
   keep it as a legacy role. `check_plan.py` refuses it on tickets that haven't started, and `afs-eval`
   re-plans it to the orchestrator.
4. **The bootstrap eval case runs the orchestrator.** `synthetic-sy-01-bootstrap` dispatches
   `afs-program-orchestrator` with the skill. Its new `harness_copy` field puts that agent and its harness
   skills on the branch, since a bootstrap case runs before the harness is installed.

## Consequences
- One fewer role, and one fewer session and return per migration.
- The orchestrator's context grows at intake by the size of one skill, loaded only then.
- A target installed before this keeps its Bootstrapper returns valid. Re-running bootstrap removes the
  role's agent file.
