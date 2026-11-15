# ADR-0041: Agent changes are measured against an end-to-end eval

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-14
- Amends: ADR-0039 (the eval repository runs Copilot workflows without approval)
- Source: [agent-topology review](../reviews/agent-topology-review.md), finding 1; [plan](../reviews/agent-topology-plan.md), phase 1

## Context
Every change to the role agents so far was a response to an incident in a live run. None was compared
against a baseline. `harness_coverage.py` measures which paths ran, and the unit tests measure the tools,
but nothing measured whether an agent's *output* got better or worse. Anthropic's guidance on folding
subagents makes this the first step: a small end-to-end eval (about ten golden examples), graded against a
rubric, each task run more than once, comparing which tasks flipped and not only the total.

The pilot and synthetic runs already hold golden outcomes: accepted PRs, their characterization, and Verifier
verdicts whose findings were confirmed and fixed.

## Decision
1. **The eval.** `evals/cases/*.yaml` holds real tickets with known outcomes. Each case pins:
   - a source target and commit (and, for a Verifier case, the Migrator head the live Verifier judged);
   - the issue text that was dispatched;
   - the custom agent;
   - the expected outcome.

   Kinds:
   - **migrator:** Gates green, mutation on changed code at least the threshold, no new validation errors;
   - **verifier:** the verdict, and for a defect case a serious finding naming the real defect;
   - **bootstrap:** fields of the profile and checklist.

   Clean Verifier cases are included, so a configuration that rejects everything cannot pass.
2. **The runner.** `tools/afs-eval` has these commands:
   - `prepare` builds one branch per case in the eval repository: the historical commit, plus the harness
     under test installed by `bootstrap.py`, plus the case's normalization (only stale references the live run
     fixed later; never behavior), plus an `-s ours` merge of the eval repository's `main` for ancestry;
   - `dispatch` assigns each case to Copilot exactly as a live ticket is assigned;
   - `grade` scores the result, re-running validation itself and taking Gates from CI;
   - `report` lists every case and every flip against a baseline. It exits 1 when a `must_pass` case flips to
     fail.
3. **The bar.** A change to the role agents, their skills or the harness rules that steer them is not
   accepted until the eval has been run on it, each affected case at least twice, compared against a baseline
   taken with the same Copilot model. No `must_pass` case may flip to fail.
   - A topology change (folding or splitting a role) runs every case.
   - The result file under `evals/results/` is committed with the change.
4. **Skill loads are recorded.** The cost hook records the custom agent (`subagent.selected`) and every
   skill it loaded (`skill.invoked`, names and counts only) in the session's cost record. `afs-eval skills`
   and each eval report summarize them, so unused skills can be found and pruned (finding 9).
5. **The eval repository** (`martins-vds/ai-factory-eval`) is the one exception to ADR-0039's
   approval-on default. Copilot workflow runs there start without a person's approval. Otherwise a baseline of
   17 cases run twice would need 34 or more approvals. ADR-0039's mitigations hold:
   - the repository has no secrets: both sources are public, and `main` never moves, so stack refresh never
     runs;
   - default workflow permissions are read-only;
   - a ruleset requires a pull request on `main`;
   - CODEOWNERS covers `.github/` and `.migration/harness/`;
   - only the operator and the dispatcher assign work there.

   Nothing from the eval repository is ever merged into a target.

## Consequences
- Every topology decision in the agent-topology plan (phases 2–5) cites an eval result. "It worked on the
  incident" is no longer enough.
- Eval runs cost Copilot sessions: about 34 for a baseline, and 10–20 for a targeted comparison.
- Golden outcomes come from one historical run. The rubric checks behavior (gates, verdicts, named
  defects), never the exact diff, so an equally good solution passes.
- Historical commits are made valid under today's rules by normalization recorded in each case. A case
  whose normalization would change behavior is dropped rather than normalized.
- Old cases that the current harness can't install on cleanly are not used. Of the original candidates,
  pilot HR-04E and TC-14 were left out: their states carry return files that today's rules reject, and that
  can't be fixed without rewriting history.
