# ADR-0050: The Slice Coordinator folds into the Program Orchestrator

- Status: Proposed (merging the harness PR that adds it accepts it). Roll it out to the synthetic target only
  once its open side-by-side checks finish under the current topology (plan, Ground rules).
- Date: 2026-11-19
- Amends: ADR-0024 (epic closure), ADR-0030 (who reconciles), ADR-0031 (whose return carries the sign-off)
  and ADR-0036 (deferrals)
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 3; [plan](../reviews/agent-topology-plan.md),
  phase 3d

## Context
The Slice Coordinator sat between the orchestrator and the workers, but a remote coordinator could never
dispatch: assigning issues needs a user token. So the orchestrator (or the operator) ran its loop anyway.
What it did that nothing else did was two kinds of work:
- **Prose rules**, which are now tools: path checks and merges (ADR-0047), planner checks (ADR-0048) and
  reconciliation (ADR-0049).
- **Slice acceptance**, a procedure that runs once per slice.

Since ADR-0045, it also no longer dispatches a Verifier on each return.

## Decision
1. **One dispatcher loop.** The orchestrator's step 6 runs every slice's ticket loop: frontier and claim,
   dispatch of `afs-migrator` (parallel only where `check_dispatch_paths.py` passes), returns accepted on
   green checks, and "restart, don't stretch". Its Skills section gains the coordinator's skills.
2. **`skills/afs-slice-acceptance/`** holds the coordinator's steps 5 and 6. Those steps are the
   acceptance gates run, the Auditor, the evidence report, the reconciliation file (generated with
   `reconcile_epic.py`), and the human check, with ADR-0031's and ADR-0036's sign-off and deferral rules
   unchanged.
3. **The acceptance return** is the orchestrator's own:
   - The orchestrator commits `.migration/returns/<acceptance-ticket>.afs-program-orchestrator.yaml`.
   - The return carries an `acceptance` block: `slice`, `tickets`, `report`, `gates`, `mutation_score`,
     `coverage_gaps`, `human_check`, `human_check_issues`, `human_check_issue`, `human_check_due` and
     `quirk_tickets`.
   - `check_signoff.py`, `check_slice_returns.py` and the operator dashboard read that block, and still
     read a retired coordinator's return.
4. **The role retires.**
   - `agents/afs-slice-coordinator.agent.md` is deleted, and its return contract moves to
     `agents/retired/`.
   - `check_plan.py` refuses the role on tickets that haven't started. It keeps the role as a legacy shared
     id, so its committed returns stay valid.
   - `afs-eval` re-plans the role to the orchestrator, and plans may name `afs-program-orchestrator` for an
     acceptance ticket.
   - The drills that wrote coordinator returns now write the orchestrator's `acceptance` block.

## Consequences
- **One fewer layer.** The ticket loop, acceptance and the human gates are all held by the role that
  already held the operator's attention.
- **Larger context.** The orchestrator's context grows by one skill at acceptance time, loaded only then.
- **Acceptance is still unmeasured.** No eval case covers slice acceptance. This ADR is proven by the next
  real slice acceptance on the synthetic target: it should run through the orchestrator with a generated
  reconciliation file, as the plan's "done when" says.
