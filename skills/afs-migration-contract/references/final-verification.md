# Final verification (Auditor, Phase 7)

Carried over from the Java → Django skill (code-migration-hackathon PR #6), generalized.

## Rules
- **Objective, first principles.** Ignore progress artifacts (done/deferred lists, status reports, prior
  reviews, even ledger status labels): each is a claim to re-prove, not evidence. Evidence = code +
  graphs + tests/runs executed in this audit.
- **Refresh first.** Update the target graph; confirm the source graph snapshot matches the pinned SHA.
- **Two directions, both mandatory.**
  - **Top-down** from every screen, route and workflow: UI fidelity (fields, flows, validations, states,
    permissions) and the behavior each screen triggers.
  - **Bottom-up** from every non-UI capability: jobs, batch, integrations, handlers, APIs, services,
    security and recovery paths.
- **Trust but verify.** Confirm suspected graph gaps in code before reporting them.
- **Write every gap down** as a ticket (or plan entry) the moment it is found.

## Report — exactly these sections
- **A. Graph refresh** — what was refreshed; inconsistencies found.
- **B. Top-down findings** — missing/degraded UI fidelity and screen-triggered behavior.
- **C. Bottom-up findings** — missing/degraded background, integration and system behavior.
- **D. Capability coverage** — the five gap classes ([capability-coverage.md](capability-coverage.md)).
- **E. Tickets created** — every gap filed, with dependencies and sequencing notes.
- **F. Final gap list** — each classified: UI fidelity · non-UI fidelity · top-down · bottom-up · graph
  inconsistency · integration.
- **G. Assessment** — is the migration complete? What must be fixed before it is?

## Gate
The migration is not complete while any gap is unresolved, except human-approved, documented
divergences in the ledger.
