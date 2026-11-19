# Retired: Slice Coordinator (ADR-0050)

`afs-slice-coordinator` was folded into the Program Orchestrator on 2026-11-19. The orchestrator runs every
slice's ticket loop itself (its step 6), and slice acceptance is the `afs-slice-acceptance` skill, whose return
is the orchestrator's with an `acceptance` block. This file keeps only the retired role's return contract, so
`tools/gen_return_schema.py` still validates the returns it committed. History is never rewritten. New plans
can't use the role (`check_plan.py`), and the sign-off checks still read its returns.

## Return contract
Commit it as `.migration/returns/<ticket>.<role>.yaml` with `role`, `ticket` and `issue` added
(`afs-migration-contract` → Durable outputs). In the PR description, describe the change and **link** to
the return file; never paste its contents (a description can't be updated later, so a copy goes stale).
```yaml
slice: <name>
tickets: {total: <n>, merged: <n>, open: <n>, blocked: ["<link: blocker>"]}
acceptance: {report: <path>, gates: <all-green or failing gate names>, mutation_score: <0-1>, coverage_gaps: <n>}
human_check: <requested | passed | issues | deferred>
human_check_issues: [<link>]
quirk_tickets: [<link>]
```
