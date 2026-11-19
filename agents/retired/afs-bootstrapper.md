# Retired: Bootstrapper (ADR-0046)

`afs-bootstrapper` was folded into the Program Orchestrator on 2026-11-19. Its procedure is the
`afs-bootstrap` skill, which the orchestrator runs at intake, and the tier-C proof (`tier_b_attempt`) moved
into `.migration/capabilities.yaml`. This file keeps only the retired role's return contract, so
`tools/gen_return_schema.py` still validates the returns it committed. History is never rewritten. New plans
can't use the role (`check_plan.py`).

## Return contract
Commit it as `.migration/returns/<ticket>.<role>.yaml` with `role`, `ticket` and `issue` added
(`afs-migration-contract` → Durable outputs). In the PR description, describe the change and **link** to
the return file; never paste its contents (a description can't be updated later, so a copy goes stale).
```yaml
setup_pr: <link>
characterization_tier: <A|B|C>
tier_evidence: <one line>
# tier_b_attempt: "ran: <command> -> <result>" | "no code: <contents>"   (required for tier C)
capabilities: {met: <n>, gap: <n>, waived: <n>, not_applicable: <n>}
gap_tickets: [<link: capability>]
validation: <pass|fail + first errors>
```
