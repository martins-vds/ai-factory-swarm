# ADR-0014: UI — functional fidelity is mandatory; visual direction is decided on the map

- Status: Accepted
- Date: 2026-10-30

## Context
The UI is always part of a rewrite: the target has its own front-end stack, chosen at intake together
with the back end. ADR-0001 places UI screens, flows and states inside the equivalence boundary. But
teams often want the rewritten UI to look modern, not to copy a dated design pixel for pixel. Treating
every visual difference as a fidelity defect would block that, while treating the UI as free-form
would lose behavior users depend on.

## Decision
- **Functional UI fidelity is mandatory.** Screens, fields, navigation and flows, validations and
  error messages, loading/empty/error/success states, conditional rendering and permissions must
  match the source. These are ledger capabilities with characterization and end-to-end evidence.
- **Visual direction is a decision.** Phase 4 includes a `wayfinder:prototype` ticket that decides,
  with a human: keep the current look, or modernize it and with which design system. The prototype
  uses `ui-ux-pro-max` to produce options.
- `ui-ux-pro-max` is in the built-in skill menu. The UI Specialist Migrator uses it to build screens
  in the chosen direction, and the Verifier uses its UX and accessibility rules in review.
- The per-slice human side-by-side check and final UAT judge functional equivalence. Visual
  differences that follow the chosen direction are not defects.

## Consequences
- Modernizing the look never silently drops behavior: every functional UI capability is still in the
  ledger.
- Accessibility can improve over the source as part of a modernized direction; any change in what
  users can do is still a quirk or decision ticket, not a free choice.
