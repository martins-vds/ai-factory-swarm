# ADR-0053: Skills and prompts are audited after each milestone

- Status: Proposed (merging the harness PR that adds it accepts it, once the final eval shows no must-pass flip)
- Date: 2026-11-19
- Source: [agent-topology review](../reviews/agent-topology-review.md), findings 8 and 9;
  [plan](../reviews/agent-topology-plan.md), phase 5

## Context
Skills were added per role as needs came up and never removed. Prompts grew with incident paragraphs and
rules that tools now enforce. 415 eval sessions (235 Migrator, 180 Verifier) show which skills each role
actually loads:
- **Migrator:** 9 of its 25 skills were never loaded, including `refactoring`, `refactoring-guru`,
  `clean-code`, `pr` and `understand-anything`.
- **Verifier:** 2 of its 17 skills were never loaded.

## Decision
1. **Skills by usage.**
   - The Migrator lists 12 skills (from 25), and the Verifier 13 (from 17).
   - `refactoring`, `refactoring-guru`, `pr` and `receiving-code-review` leave the lock: no role loaded them.
   - `verification-before-completion` folds into `afs-evidence`'s "Before you claim done".
   - `afs-specialty` no longer sends Migrators to `db-seed` or `prototype`.
2. **A skill budget per role:** 12. `tests/test_agents.py` fails a role above it unless the test records why.
   Today three roles are recorded:
   - the Program Orchestrator, which absorbed two roles and has no session data yet;
   - the Characterizer, which has no session data;
   - the Verifier, whose four gate-3 rule sets are each loaded in 16–33% of its sessions.

   A stale exception fails too.
3. **A prompt budget:** 6,000 characters per agent file (from 9,000; the largest was 8,838). The audit's
   moves:
   - **Rules a tool enforces cite the tool.** Examples: the return's `pr`, the finish check's evidence and
     verdict rules, `afs-merge`, `check_dispatch_paths.py`.
   - **Detail moves to references.** The Verifier's review moved to `references/verification.md`, and test
     isolation to `references/gates.md`.
   - **Repeated return-file prose shrinks** to one line.

   Largest file before and after each role's audit:

   | Role | Before | After |
   |---|---|---|
   | Verifier | 8,838 | 4,576 |
   | Program Orchestrator | 7,805 | 5,842 |
   | Migrator | 7,504 | 5,698 |
   | Auditor | 4,927 | 4,122 |
4. **The hygiene rule:** after each milestone, an audit like this one, driven by
   `afs-eval report --skills` and the eval results. Any change to an agent or skill needs an eval run, with
   no must-pass flips.

## Consequences
- Smaller prompts and skill lists cost less context per session.
- Detail now lives in references the agent loads when its step needs them, so the eval is the check that
  nothing was lost.
