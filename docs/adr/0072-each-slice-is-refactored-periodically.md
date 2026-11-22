# ADR-0072: Each slice is refactored periodically, and the tests it breaks are counted

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 5.3; the phase 0 refactor eval (step 0.4); ADR-0071

## Context
The phase 0 refactor eval measured coupling the direct way. It asked for a restructuring that keeps behaviour,
and counted the existing tests the agent had to change. The pilot's exporter refactor changed its export tests
every time. The synthetic fee refactor changed none. A metric like the coupling ratio (ADR-0071) only infers
this from history, and history has few pure refactors. To keep the trend honest, the direct measurement has to
recur on the live targets, not once in an eval.

## Decision
1. **`afs-refactor-ticket propose` plans a refactor, chosen the same way every time:**
   - **the slice:** among slices with finished Migrator work, the one whose latest refactor ticket is oldest;
     a slice never refactored comes first, then by name;
   - **the module:** in the slice's planned code, the one with the most module-level private functions, at
     least two; ties go to the longer module. Migrations and `__init__.py` are left out.
2. **The ticket is the phase 0 case.**
   - Move those helpers into a new module in the same package, as public functions named for what they do,
     with no aliases.
   - Change an existing test only if the move breaks it, and say why in the return.
   - Every gate runs as usual, the spec included.
   - It is added to the slice's plan as text at the end of `tickets:`, with `refactor: true`, its package and
     the slice's tests as its files. The plan's other lines and comments are kept. The plan `.md` gets the
     issue text.
3. **A monthly AFS refactor workflow** (also on demand, for a named slice) opens a PR with the planned ticket.
   The operator merges it, and the dispatcher publishes and dispatches it like any Migrator ticket. A workflow
   can't assign Copilot, and shouldn't.
4. **The measurement is on the dashboard.** For a slice's latest finished refactor ticket, `afs-dashboard
   health` counts the existing slice tests that the commit landing its return modified. Added tests don't
   count. The Test health table shows it as "Last refactor: N test(s) changed".

## Consequences
- On today's targets, the first picks are the pilot's `admin-live-map` (`admin_map.py`: `_cargo_map_data`,
  `_location_data`) and the synthetic `fees-payments` (`views.py`: `_fee_amount`, `_gateway_result`,
  `_fee_or_404`). The synthetic pick is exactly the refactor written by hand for phase 0.
- One refactor ticket per month per target is real Migrator work, and it costs a session. In return it keeps
  the slices' private helpers few, and it measures what refactor resistance actually is.
- The choice is mechanical, so it can pick a module whose helpers don't make a good module. The Migrator can
  hand off with why, and the operator can skip the PR.
