# ADR-0048: Plan checks catch what planning lost

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-19
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 6 (part 1);
  [plan](../reviews/agent-topology-plan.md), phase 3b

## Context
Four planning losses on the synthetic target each cost a fix PR after the work merged:
- **Anchors:** a slice spec named target routes the code never had, so the graph gate failed after the
  work merged (#77, #89, #99).
- **Target paths:** templates sat outside the profile's `graph.target_paths`, so the target graph never
  saw the pages (#76).
- **Removals:** a ticket deleted a module that tests it didn't own still imported.
- **Issue drift:** an issue's file list drifted from the plan, and the session followed the issue (LL-01
  #71, LL-04 #107).

## Decision
`tools/check_plan.py`, run by `validate.py` on every plan, gains four checks:
1. **Anchors.** For a slice whose tickets are all still open, every target anchor in its spec
   (`data_paths.target`, `entry_points.target`) is listed under some ticket's new `builds:` field.
2. **Target paths.** A template or static file an open ticket plans is under `graph.target_paths`, unless
   it is under `graph.target_exclude`.
3. **Removals.** A module an open ticket lists under the new `removes:` field has every test that imports
   it in the ticket's files, or owned by a ticket it is blocked by. A removed file is also in `files`.
4. **Issue drift.** With `--issues` or `--repo`, each open ticket's dispatched issue (`<ID> · …`) lists the
   files the plan lists. `AFS-SCOPE:` lines are allowed extensions, and the session's own return and
   evidence files may go unlisted. The plan file is the scope.

## Consequences
- Plans already started aren't held to `builds:`; a new plan must write it.
- The Planner's step 7 names the two new fields.
