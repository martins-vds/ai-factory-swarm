# ADR-0054: An eval run measures the harness only when the session started with its tools

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-19
- Source: phase 5 final eval (p5-r1, p5-r2, p5s-r1, p5s-r2)

## Context
The phase 5 final eval dispatched 58 Copilot sessions. In 40 of them the target's setup step
"Install RTK 1.1.0" failed with `release not found`, in batches: the first 11 sessions of a burst
installed RTK, the rest of the burst did not, and a later burst (22:17 UTC) installed it again. The release
was there throughout (its tag never moved), so the API answer was most likely the shared
`github.token` quota of sessions running at once in one repository; it is not proven.

A failed setup step skips every later one. Those sessions started without RTK, Python, the harness tools,
test services or the data snapshot, and RTK's `PreToolUse` hook failed on every tool call. The agents
stopped and said so in draft PRs ("blocked by repository hook"), which is correct, but the grader scored
them as harness failures. Read at face value, the run said the harness had regressed on almost every
case.

The same run showed two eval-side defects:
- **LL-01 started on a validation error.** Prepare rewrote the plan (re-planning open tickets under the
  folded role) in the same commit that installed the harness. `predates_rule` exempts a file only when its
  commit comes before the rule's, so the anchors rule (ADR-0048) refused a plan it should have exempted.
  The agent handed the ticket off.
- **Prepare pushed it anyway.** It printed "1 validation error(s) before the agent starts" and dispatched.

## Decision
1. **RTK installs from the release's download URL, with retries, not through the API.** Both the setup
   steps and the harness check use `curl --retry 5 --retry-all-errors` against
   `github.com/<repo>/releases/download/v<version>/<asset>`. No token is needed for a public release.
2. **`afs-eval grade` reports `setup-failure`** when a target setup step failed in the session's first run
   (the jobs API names the step). Copilot's own wrapper steps don't count.
3. **A `setup-failure` or `not-dispatched` row is not a run.** `compare` counts neither toward a case's
   majority, so a case re-run in a later run file counts once per real session.
4. **Prepare commits normalized files before the harness.** A re-planned plan is older than the rules the
   new harness adds, as it is on a live target.
5. **Prepare refuses a case that starts with validation errors.** It pushes the rest and exits non-zero.
   A case about a broken tree passes `--allow-errors`.

## Consequences
- Infrastructure failures no longer read as harness regressions, and they no longer dilute a majority.
- The targets need the new setup steps; the next rollout carries them.
- If the RTK download itself is down, the session still starts without RTK; grade now says so instead of
  failing the case.
- Rejected: wrapping RTK's hook so it passes when RTK is missing. The harness check requires the hook to be
  exactly what `rtk init --copilot` writes, and a silent pass would hide a session running without RTK.
