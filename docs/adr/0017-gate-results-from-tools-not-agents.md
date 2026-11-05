# ADR-0017: Gate results come from the tools, not from agents

- Status: Accepted
- Date: 2026-11-02

## Context
In M5, TC-15c ran the full mutation gate before and after its change through `afs-run`, but its journal
showed only exit codes. `afs-run` recorded the first error-like line, and a passing run's score is not an
error, so the number was printed and lost. The return schema allowed `null` for every value, so even a
finished return could leave its scores empty, and nothing tied a number in a return file to a run that
produced it. An agent could round, retype or invent a score and still pass validation.

Gate tools differ by stack (mutmut, PIT, Stryker, Infection, …) and so do their reports. If agents
converted reports into the harness's format, every conversion would be a chance to get the number wrong.

## Decision
1. **One result line, printed by harness tools.** Every harness gate tool prints
   `AFS-RESULT gate=<gate> key=value …`:
   - `afs-mutation`: `score`, `threshold`, `killed`, `survived`;
   - `crap.py`: `max`, `threshold`, `over`.

   A new stack's tool gets a **harness adapter** that reads the tool's native report and prints the same
   line, the way `afs-mutation` wraps mutmut. Where a tool can export the shared mutation-testing JSON
   report format (Stryker's), the adapter reads that. Agents never convert results.
2. **`afs-run` journals it.** The run journal gains a Result column holding the last `AFS-RESULT` line of
   the run. Older journals are upgraded in place on the next append.
3. **`validate.py` checks return files against the journal.**
   - A finished return (no handoff) has no `null` gate. A gate that doesn't apply says
     `n/a: <reason>`.
   - Every score (`mutation_changed`, `mutation_full`, `mutation_score`) equals the score of the last
     mutation run in the ticket's journal **whose command is a profile gate command**, as given or via
     `bash -c`. Result lines from any other command are ignored, so an `echo` can't forge one, and
     harness tools can't be edited (`check_installed`).
4. **Legacy.** Bootstrap lists the return files that existed before this rule once, in
   `.migration/harness/legacy-returns.json`. Later installs keep that list unchanged, and
   `check_installed` protects it, so a new return can never become exempt.

## Consequences
- Scores in return files are reproducible from the journal, and the journal from the log's SHA-256.
- The CI gate job remains the independent re-run for changed-code mutation. The slice-end full run is
  too slow for every PR, so the journal check is what keeps it honest.
- Adding a stack means adding an adapter in the harness (and naming it in the stack pack's gate
  commands), not instructing agents.

## PR attribution

The offline return validator also requires a meaningful PR reference on a finished return when its
generated role contract has a `pr` field. A `owner/repo#N` reference or canonical PR URL is sufficient;
the validator does not resolve it over the network. A handoff remains partial and may keep `pr: null`,
and roles without a `pr` contract are unaffected.

The PR-event contract check compares a finished return's reference with the event PR only among return
files changed against that PR's base. Returns inherited from a stacked base keep their original PR
identity. These metadata checks do not prove that the worker completed the work, that a PR exists or is
merged, or that merging is authorized.

For rollout, an unchanged null-PR return whose last change predates the commit introducing this rule
remains historical and is not rewritten or treated as current work. A later edit to that return is
checked normally. Returns in `.migration/harness/legacy-returns.json` retain their existing exemption;
older returns not covered by either history rule or that list are not silently grandfathered. Detecting
the rule-introduction commit requires local Git history that contains it; if that history is unavailable,
the validator fails closed and the return needs attribution.
