---
name: afs-specialty
description: What a Migrator ticket with a specialty (data, ui or messaging) adds to the Migrator procedure — the data pipeline and reconciliation, UI fidelity in the chosen direction, message contracts — and which extra skills and evidence it needs. Load it when your ticket's plan entry has `specialty:` set (ADR-0042).
---

# Specialty tickets: data, UI, messaging

A ticket with `specialty:` set in its plan entry is still a Migrator ticket. The contract, the gates,
the scope rule and the return file are the same. This skill adds what the specialty needs.
It replaces the former Specialist Migrator role (ADR-0042).

## Before you start
- Read `specialty` from your ticket's plan entry (`.migration/plan/<slice>.tickets.yaml`).
- Load the stack skills that `profile.skills.specialists.<specialty>` lists, as well as the skills below
  for your specialty.
- Read the decision-map answer that governs your specialty: the data strategy, or the UI direction.

## Data (ADR-0010, ADR-0032)
Load `afs-data-pipeline` and `db-seed`.

1. **Build the pipeline.** Build the repeatable legacy → target pipeline for your slice's tables,
   following `afs-data-pipeline`: snapshot check, mapping, idempotent loader, export.
2. **Reconcile it.** Run `data_reconcile.py` through `afs-run`: row counts, checksums and referential
   integrity.
3. **Test the business rules.** Add tests for the business invariants, and for the characterized behavior of
   the legacy procedures or reports that the target replaces.
4. **Masking** applies only if the profile enables it.
5. **Never commit** snapshot or exported rows.

**Evidence:** the reconciliation report.

## UI (ADR-0014)
Load `ui-ux-pro-max`. Load `prototype` only when a screen's look is still open; a prototype is throwaway.

- **Functional fidelity is mandatory.** Every field, flow, validation, state and permission of the screen,
  per the ledger.
- **The look follows the UI direction** on the decision map. A visual difference that follows that
  direction is not a defect. Any change in what users can do is a quirk ticket or a decision ticket.
- **Tests.** End-to-end tests drive the screen, and the accessibility rules from `ui-ux-pro-max` apply.

**Evidence:** the end-to-end run.

## Messaging and integrations
- Preserve message contracts and delivery semantics at the boundary.
- Test against real or containerized brokers where possible.

**Evidence:** the contract tests.

## Return file
Add these to the Migrator's return block:
```yaml
specialty: <data | ui | messaging>
specialty_evidence: [<reconciliation report | e2e run | contract tests>]
```
