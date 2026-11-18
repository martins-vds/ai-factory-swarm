# ADR-0043: Layering is a gate, and a Verifier's verdict follows evidence-backed findings

- Status: Accepted (2026-11-18). In eval run v3j, all seven Verifier cases pass by majority (21 sessions:
  six cases 3/3, LL-02 2/3); b3c passed 1 of 6
  ([summary](../../evals/results/2026-11-17-v3j-summary.md)). Caveat on decision 9: BK-05F verify passes on
  ledger rules a Migrator recorded, but only 1 of 3 BK-05F Migrators did the ticket and recorded them (m3j).
  The Migrator measurement (m3j) was still grading when this was accepted; a regression there reopens
  decision 9.
- Date: 2026-11-17
- Source: [plan](../reviews/agent-topology-plan.md), phase 3e; baseline b3c
  ([summary](../../evals/results/2026-11-16-b3c-summary.md))

## Context
In baseline b3c, the Verifier passed one of its six cases by majority. Its failures fell into two kinds.
- **It missed defects a tool can find.** All three real misses are imports that cross a layer:
  - a use case raising Django's `Http404` (BK-05F);
  - use cases calling the framework clock and the ORM (LL-02);
  - a view calling the repository instead of a use case (BK-05E).
- **Its verdicts weren't tied to evidence.**
  - It raised serious findings on clean work (LL-03, BK-05G) that no test showed.
  - It returned `changes-required` with no major finding (LL-04 r1).
  - It returned `blocked` for a defect it found (BK-05G).

A prompt can ask for care, but it can't make a review deterministic. A tool and a mechanical check can.

## Decision
1. **Layer contracts live in the profile, and a tool checks them.**
   - `layering:` in the profile holds the contracts the architecture ADRs state. Each contract names the files
     it covers and the modules they may not import.
   - `tools/check_layers.py` runs in the idiom gate, so every Migrator ticket, every Verifier and CI run it.
   - `validate.py` refuses a profile that has `layering` but doesn't run the tool.
   - The plan said `gates.layering`, but `gates` holds commands. The contracts are their own key, and the
     command goes in `gates.idiom`.
2. **Existing debt is named, not hidden.** `layering.known` lists violations that predate a contract, each with
   what will remove it. A known violation is reported but doesn't fail; a new one fails. A known entry that no
   longer occurs is reported, so it can be removed.
3. **The verdict follows the findings.** `validate.py` checks every finished Verifier return, so CI and the
   finish check both enforce it:
   - `pass` has no blocker or major finding;
   - `changes-required` has at least one;
   - `blocked` names, in `blocked_reason: "<gate>: <why>"`, the gate that couldn't run or finish. A defect
     is never `blocked`.
4. **A serious finding carries evidence.** A blocker or major finding has `evidence:`, one of:
   - a test the Verifier added (listed in `tests_added`) that fails because of the defect;
   - `run: <name>`, a failing run of that name in the ticket's journal.

   Without evidence, a finding is `minor`.
5. **History stays valid.** Verifier returns committed before this rule reached a target are exempt, by the
   same marker mechanism as the PR-reference rule.
6. **A defect from an earlier ticket is reported apart** (operator ruling, 2026-11-17).
   - Its cause lies outside the ticket's diff, in code an earlier ticket wrote that this work depends on.
   - It goes under `inherited` (`where`, `what`, `origin`, `evidence`), never under `findings`, and never
     changes the verdict. Its fix is planned as its own ticket.
   - Phase 3e's first measurement prompted this: every Verifier found LL-01's unserved stylesheet while
     verifying LL-04, and BK-05C's `Http404` while verifying BK-05F.
7. **Two UI defects are tools' jobs too** (`ui_checks` in the profile; `tools/check_ui.py` in the idiom gate,
   on the templates a branch changed):
   - a template that sends an htmx request needs error-response handling somewhere, because htmx swaps no 4xx
     or 5xx response by default;
   - when the stylesheet is committed pre-built, every Tailwind utility a changed template uses must be in it.

   Phase 3e's v3g found these defects (LL-03, BK-05G, LL-04) in one run of three; the tool finds them in
   every run. `validate.py` refuses `ui_checks` without the gate.
8. **The Verifier proves where each business rule is enforced** (operator decision, 2026-11-17).
   - A finished return lists `rules`, covering every capability the plan gives the ticket. Each rule names
     the use case and a test that calls it directly, with input the rule must refuse, and records whether
     the use case refuses it.
   - A capability with no business rule goes under `no_rules`, with the reason.
   - An unenforced rule needs a blocker or major finding citing that test.
   - `validate.py`, and so the finish check, refuses a return that misses a capability or cites a test that
     doesn't exist.
   - Eval v3h prompted this: every run missed BK-05F's eligibility rule in the view, though the prompt asked
     for exactly this test.
9. **Business rules live in the ledger** (operator decision, 2026-11-17, after eval v3i).
   - The Migrator records each capability's business rules under the ledger entry's `rules` (`id`, `rule`,
     `source`), wherever its code enforces them, a view included. A capability with none gets `no_rules`.
   - The Verifier's `rules` must cover every ledger rule (`ledger_rule: <id>`), so the list the Verifier
     checks is not one it chose itself.
   - `validate.py` checks both, after the `LEDGER_RULES_RULE_V1` marker.
   - Eval v3i prompted this: BK-05F's Verifiers listed only rules the use case enforced, because the
     misplaced rule was in no plan or ledger. The Characterizer may record rules too, once it has an eval
     case to measure the change.
10. **The eval reports a gate-blocked Verifier apart.** Such a case still fails, but as `verifier-blocked`, the
   way timeouts are reported apart from wrong verdicts.

## Consequences
- A Migrator can't commit an import-level layering defect when its target has contracts. The Verifier's review
  is left with what a tool can't see, such as where a rule is enforced.
- Each target needs its contracts written once, from its ADRs. The pilot and the synthetic target get theirs
  in their own PRs.
- Verifier returns get longer: each serious finding carries a test or a run.
- A Verifier that suspects a defect but can't show it reports a minor finding, and the work can pass. That
  trade is deliberate: unproven serious findings failed clean work in b3c.
