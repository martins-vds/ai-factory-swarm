# Retired: Specialist Migrator (ADR-0042)

`afs-specialist-migrator` was folded into `afs-migrator` on 2026-11-16. A ticket with `specialty:` set in its
plan entry is now a Migrator ticket that loads the `afs-specialty` skill. This file keeps only the retired
role's return contract, so `tools/gen_return_schema.py` still validates the returns it committed. History is
never rewritten. New plans can't use the role (`check_plan.py`).

## Return contract
Commit it as `.migration/returns/<ticket>.<role>.yaml` with `role`, `ticket` and `issue` added
(`afs-migration-contract` → Durable outputs). In the PR description, describe the change and **link** to
the return file; never paste its contents (a description can't be updated later, so a copy goes stale).
An initial WIP return may use `pr: null` before the PR exists. Before finishing, replace it with this
return's PR as `owner/repo#N` or a canonical PR URL and commit the update. If work is incomplete, record
a handoff; its `pr` may remain null.
```yaml
ticket: <link>
specialty: <data | ui | messaging>
pr: <link>
gates: {build: <exit>, behavior: <exit>, idiom: <exit>, crap: <exit>, mutation_changed: <score>, regression: <exit>}
specialty_evidence: [<reconciliation report | e2e run | contract tests>]
ledger_updated: [<ids>]
quirk_tickets: [<link>]
handoff: <none | .migration/handoffs/<ticket>.md>
```
