# ADR-0043: Layering is a gate, and a Verifier's verdict follows evidence-backed findings

- Status: Proposed. It is accepted once the Verifier cases meet phase 3e's done condition (ADR-0041).
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
6. **The eval reports a gate-blocked Verifier apart.** Such a case still fails, but as `verifier-blocked`, the
   way timeouts are reported apart from wrong verdicts.

## Consequences
- A Migrator can't commit an import-level layering defect when its target has contracts. The Verifier's review
  is left with what a tool can't see, such as where a rule is enforced.
- Each target needs its contracts written once, from its ADRs. The pilot and the synthetic target get theirs
  in their own PRs.
- Verifier returns get longer: each serious finding carries a test or a run.
- A Verifier that suspects a defect but can't show it reports a minor finding, and the work can pass. That
  trade is deliberate: unproven serious findings failed clean work in b3c.
