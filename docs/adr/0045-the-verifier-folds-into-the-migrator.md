# ADR-0045: The Verifier folds into the Migrator for Migrator tickets (phase 4a, round 2)

- Status: Accepted (2026-11-18, operator decision)
- Date: 2026-11-18
- Supersedes: ADR-0044 (the Verifier stays; 4a was inconclusive)
- Amends: ADR-0040 (Migrator work merges only after its Verifier passes it)
- Source: [plan](../reviews/agent-topology-plan.md), phase 4a; [round 2 results](../../evals/results/2026-11-18-4a-round2-summary.md)

## Context
Phase 4a's first round found no defect on any merge candidate, so ADR-0044 kept the Verifier and asked for
cases that start clean. Round 2 ran eight Migrator cases twice in each configuration:
- **A:** the Migrator, then a Verifier session;
- **B:** `afs-migrator-selfverify`, a Migrator that verifies its own work.

The new cases are BK-05F and BK-05G rebuilt from before their first session. The LL-02 oracle now covers the
trimming that round 1's Verifier reported, settled against the legacy. An independent Verifier audited each
finished B head, as a measurement only.

Across both rounds:
- **A's Verifier caught two major defects** on green-Gates Migrator heads, both in LL-02: trimming stored
  values, and htmx response rules that matched codes htmx 2 doesn't define.
- **B had no major defect on any merge candidate.** The audit and the oracle confirm it in round 2.
- **B shipped one minor divergence** (`min=today` on the deadline input). Under ADR-0043, a minor finding
  doesn't change a Verifier's verdict, so A would have let it through too.
- **A's Verifier was unreliable on the pilot cases.** In round 2 it gave one false `changes-required`, two
  `blocked` verdicts and one timeout across 10 sessions.
- **B cost about 32% fewer minutes** across both rounds (728 against 1,071).

## Decision
1. **The plan's rule is met, not vacuously.** B catches every real-defect case A catches, on both runs: no
   major defect reaches a merge candidate in B.
2. **Fold for Migrator tickets.**
   - The Migrator's procedure gains the self-verification step from
     `evals/variants/afs-migrator-selfverify.agent.md` (step 6), plus a check of each behavior against the
     legacy source.
   - Its return lists every business rule with a use-case test (`rules`, `no_rules`), and `validate.py`
     holds it to that as it holds the Verifier (`MIGRATOR_SELF_VERIFY_RULE_V1`). A rule its use case
     doesn't enforce is its to move, not to report.
   - The Slice Coordinator stops dispatching a Verifier on Migrator work.
   - `check_verified_merge.py` no longer needs a Verifier return for an `afs-migrator` return. If an audit
     of the current work exists, it must pass.
   - The `afs-verifier` agent stays for audits the operator asks for and for evals.
3. **What only a reviewer found becomes a check.** `check_ui.py` now fails on response rules that match a code
   htmx 2 doesn't define. Each later reviewer-only finding class gets a tool check or an oracle where one can
   be written.

## Consequences
- A ticket costs one session instead of two, and the operator approves fewer workflow runs.
- **No second reviewer on a ticket.** Defects of a class no tool checks yet go unseen until slice acceptance
  and the operator's side-by-side check. An audit run (`afs-eval chain` on Migrator heads) can measure this
  again at any time.
- **The evidence is small:** two defects, both in one case. If a later eval or a live run shows a major
  defect merging that a Verifier would have caught, this decision is revisited.
- Self-verifying sessions run longer. Two B sessions hit the hour limit in round 2.
