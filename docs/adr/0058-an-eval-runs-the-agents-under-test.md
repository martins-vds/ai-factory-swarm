# ADR-0058: An eval runs the agents under test

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-20
- Source: preparing the fold eval (ADR-0050, ADR-0051 follow-up)

## Context
Copilot reads custom agents from the eval repository's default branch, not from the case branch
(`evals/README.md`). Skills, tools and setup steps come from the case branch, which `prepare` builds from the
harness under test. Updating `main`'s agents is a manual step.

It was missed. `main` has served harness `ca620b9`'s agents since 2026-11-18. Every later run therefore used
those prompts, whatever harness the case branch carried:
- **Phase 3d** folded the Slice Coordinator into the orchestrator. No case covered it, so no result was
  affected.
- **Phase 2b's bootstrap runs and the phase 5 eval** ran the pre-fold orchestrator and the unshortened
  prompts. Phase 5's "no flip" covers the skill cuts, tools and setup fixes, but not ADR-0053's shorter
  prompts. The bootstrap case passed because its issue named the `afs-bootstrap` skill.

Nothing checked for the drift.

## Decision
1. **`afs-eval prepare` refuses to run while the eval repository's `main` serves other agents.** Every
   `agents/afs-*.agent.md` of the harness under test, and every variant in `evals/variants/`, must be on
   `main` under `.github/agents/`, byte for byte. Other files there (retired roles) may stay.
2. **A deliberate mismatch is named.** `--allow-agent-drift` prepares anyway, for a run that means to
   measure other agents.
3. **A variant is a file in `evals/variants/`.** The pre-fold Slice Coordinator joins the
   configuration-B Migrator and the understander there, so the guard covers it too.

## Consequences
- An eval can't silently measure stale prompts again.
- Syncing `main` remains a PR. The guard says what differs.
- Phase 5's shortened prompts still need a measurement. The must-pass set is re-run after `main` is
  synced.
