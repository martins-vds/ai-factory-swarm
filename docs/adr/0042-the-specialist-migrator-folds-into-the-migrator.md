# ADR-0042: The Specialist Migrator folds into the Migrator

- Status: Proposed. It is accepted only once the eval comparison below holds (ADR-0041).
- Date: 2026-11-16
- Amends: ADR-0010 (who runs the data pipeline) and ADR-0014 (who builds UI screens)
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 2; [plan](../reviews/agent-topology-plan.md),
  phase 2a

## Context
`afs-specialist-migrator` said "Everything in `afs-migrator` applies; this file adds what is special":
- the same procedure, gates, scope rule and stop rules;
- almost the same return file.

What it added was procedure for three specialties:
- **data:** the pipeline and reconciliation;
- **UI:** fidelity in the chosen direction;
- **messaging:** contracts at the boundary.

Two prompts that must be kept in step drift apart. The mutation rule, for example, was written in both.
Anthropic's guidance on folding subagents puts procedure in skills and merges specialists that do the same
work on the same data.

The eval baseline b3c gives a measured starting point for the specialty cases:
- pilot BK-05F (UI) and DM-05F (data) pass in every run;
- DM-05D (data) and BK-05G (UI) fail by majority, through handoffs and one-hour timeouts.

## Decision
1. **One role.** A ticket with `specialty:` in its plan entry is an `afs-migrator` ticket.
   - The Migrator loads the new `afs-specialty` skill, which holds the data, UI and messaging procedures and
     their evidence. It also loads the specialty's skills: `afs-data-pipeline` and `db-seed` for data,
     `ui-ux-pro-max` and `prototype` for UI, plus the profile's `skills.specialists.<specialty>`.
   - The return file may carry `specialty` and `specialty_evidence`. The schema already allows extra keys, so
     the Migrator's required contract is unchanged.
2. **History stays valid.**
   - The retired role's return contract moves to `agents/retired/afs-specialist-migrator.md`.
     `gen_return_schema.py` reads it, so every return it committed still validates.
   - The tools that read returns keep accepting the role.
3. **New work can't use it.**
   - `check_plan.py` refuses `afs-specialist-migrator` on a ticket that has no return yet. The error names
     the fix: `role: afs-migrator` with `specialty:`.
   - Finished tickets keep their role.
4. **The fold has to measure up (ADR-0041).** The specialty cases (DM-05D, DM-05F, BK-05F, BK-05G) and one
   plain Migrator case (LL-03) run three times with the folded harness. They are compared with b3c by
   majority of three. If any case that passes by majority in b3c fails by majority after the fold, this ADR
   is rejected and the role restored.

## Consequences
- There are nine role agents, not ten, and one prompt fewer to keep in step.
- Live targets pick up the fold in their next rollout. Their open specialist tickets, if any, must be
  re-planned as `afs-migrator`, and `check_plan.py` says so.
- Dispatch is simpler: every implementation ticket goes to `afs-migrator`.
