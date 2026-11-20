# Verification: the Verifier's review in detail

The Verifier's agent file lists the steps; this is what each one means. The finish check
(`validate.py`, ADR-0043) holds a Verifier return to the rules marked **(checked)**.

## Gate 3: what the tools see, and what you check
- **Tools:** import-level layering (`check_layers.py`, profile `layering`), htmx error handling and the built
  CSS (`check_ui.py`, profile `ui_checks`) run in the idiom gate. A violation either reports fails the gate,
  which is a finding (`evidence: run: <name>`). A `known, not failing` line is an earlier ticket's debt: list
  it under `inherited` when this ticket's code relies on it.
- **Where each rule is enforced (checked).** For each capability the plan gives the ticket, list its business
  rules (an eligibility check, a limit, a state transition) under `rules`. Every rule its ledger entry records
  is there, with `ledger_rule: <its id>`; add any other rule you find in the code, a guard in a view above all.
  For each, write a test that calls the use case directly, with no view and no request, using input the rule
  must refuse. `enforced: true` when the use case refuses it; `enforced: false` when it accepts it (the rule
  sits in the wrong layer, often the view), and that failing test is a major finding's evidence. A capability
  with no business rule goes under `no_rules`, with the reason.
- **Every error path renders.** For every request the ticket's pages send, list the non-2xx responses its
  view can return (validation 4xx, not found, a failed downstream call 5xx), and check each shows the user
  what the plan says. htmx 2 swaps no 4xx or 5xx response unless the page configures it
  (`htmx.config.responseHandling`, an `htmx:beforeSwap` handler, or the response-targets extension). A test
  that asserts the configuration, or a browser test that triggers the error, shows it.

## Findings and the verdict (checked)
- **A serious finding carries evidence.** A `blocker` or `major` finding has `evidence:`: the id of a test you
  added that fails because of the defect (listed in `tests_added`), or `run: <name>`, a failing
  `afs-run --name <name>` in the ticket's journal. A claim you can't back this way is `minor`.
- **Inherited defects are reported apart.** A defect whose cause is outside this ticket's diff (code an
  earlier ticket wrote) is not a finding: list it under `inherited` with `where`, `what`, `origin` (the ticket,
  or `unknown`) and `evidence` (`run: <name>`; don't commit a failing test for it). It never changes the
  verdict; the dispatcher plans its fix. Example: a page unstyled because the static-files setting predates
  the ticket is inherited; a view this ticket wrote that skips the use case is a finding.
- **The verdict follows the findings.** `pass`: no blocker or major finding. `changes-required`: at least
  one. `blocked`: only when a gate couldn't run or finish (setup failed, a service was down, a mutation run
  was interrupted), with `blocked_reason: "<gate>: <why>"` (`setup`, `build`, `behavior`, `idiom`, `crap`,
  `mutation_changed` or `regression`). A defect you found is never `blocked`.
