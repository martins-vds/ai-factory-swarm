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

The PR-event contract check compares finished returns changed against that PR's base with the event PR.
It uses the event's `base.sha` and `head.sha`, not the Actions synthetic merge checkout's `HEAD`, to
identify changed files, current return contents, and reachable history. It treats a return as inherited
only when the event-head history shows its content arrived unchanged from a merged second parent and no
later first-parent commit changed that path. Superseded-attribution evidence is limited to the same
return path; one return cannot attest another. If required event SHAs or merge ancestry are unavailable,
the check fails rather than assuming ownership or inheritance. These metadata checks do not prove that the
worker completed the work, that a PR exists or is merged, or that merging is authorized.

For rollout, an unchanged null-PR return whose last change predates the commit introducing this rule
remains historical and is not rewritten or treated as current work. A later edit to that return is
checked normally. Returns in `.migration/harness/legacy-returns.json` retain their existing exemption;
older returns not covered by either history rule or that list are not silently grandfathered. Detecting
the rule-introduction commit requires local Git history that contains it; if that history is unavailable,
the validator fails closed and the return needs attribution.

### Amendment (2026-11-08): a failing test run always kills the mutant

mutmut 2.x reads a mutant as killed only when the test command exits 1. A mutant that breaks an
import makes pytest exit 2 (collection error), and mutmut counted it as survived. On the pilot this
held BK-05H at 0.763 for two sessions: all nine survivors were `x = None` or `include('XX…XX')` in
`urls.py`, which existing tests already caught. The number came from a tool, but the tool misread the
tests' result.

`afs-mutation` now runs each mutant's narrowed tests in-process through `afs-mutation --pytest`, which
exits 1 for any failing run (pytest 2, 3, 4) and passes 0 and 5 through. A baseline that can't import
now fails as a mutmut error instead of passing silently. Scores recorded before this change may be
too low, never too high. A `--runner` the operator passes is still used as given.

## Amendment (2026-11-10, found when synthetic LL-03 merged)
A ticket's run journal is shared by every session that works the ticket: migrator, Verifier, fix, and
re-verification. A return's score must equal the **last mutation run of one session** in the journal as of
the return's last commit. Sessions are delimited by the `setup-probe` row that `afs-setup-check` writes
first. Before this, the score had to equal the journal's last mutation run. That held on the PR branch,
where the migrator's return was committed before the Verifier's rows, but a squash merge lands both in one
commit. LL-03's return (0.800) was then compared with the re-verification's last run (0.914), and `main`'s
Migration state check went red. A score from the middle of a session still fails.
