---
name: afs-slice-acceptance
description: How the Program Orchestrator accepts a slice once all its tickets are merged — the acceptance gates run, the Auditor, the evidence report, the ticket reconciliation (generated with reconcile_epic.py), the human side-by-side check and its sign-off or deferral rules, and the acceptance return. Load it when every ticket of a slice is merged. Replaces the Slice Coordinator's acceptance steps (ADR-0050).
---

# Slice acceptance

The Program Orchestrator runs this when every ticket of a slice is merged. It replaces the Slice
Coordinator's steps 5 and 6 (ADR-0050); the sign-off and deferral rules below are ADR-0031's and
ADR-0036's, unchanged. The acceptance gates are in `afs-migration-contract` → references/gates.md
("Slice acceptance"). Load `afs-evidence` for the report, `afs-ledger` to reconcile the slice's entries,
and `afs-quirk-ticket` for quirks acceptance finds.

## 1. Acceptance
**Slice acceptance** (all tickets merged): end-to-end characterization, differential checks (tier A)
or checks against specs, full mutation run, capability coverage (dispatch `afs-auditor` for gate 7),
ledger reconciled, evidence report written. Then request the human side-by-side check
(`human_check: requested`).
**The sign-off is the approver's review, never your line (ADR-0031).** When the human reports the
check passed, commit your acceptance return with `human_check: passed` on a PR that you (or the Copilot coding
agent) opened, and ask an approver from the profile's `signoff.approvers` to **approve that PR**. The
AFS human sign-off check stays red until an approver approves the PR's current head commit; a later
push makes the approval stale. Never submit, request on someone's behalf, or relay a review or a
sign-off yourself, even when you hold the approver's GitHub login. If they report problems, set
`human_check: issues` and link each one.
**Deferral (ADR-0036).** If the operator says to defer the check, record `human_check: deferred` with
`human_check_issue: <link>` (an open issue assigned to an approver that lists exactly what to compare)
and `human_check_due: <YYYY-MM-DD>` (7 days by default, at most 30), on a PR an approver approves, as
for `passed`. A deferral lets dependent slices proceed; the slice epic stays open until `passed`. Never
defer on your own.
**Before dispatching the Auditor**, the dispatcher starts one **AFS acceptance gates** run on `main`
(ADR-0035). It builds the target graph for that exact commit, gates it, and runs full mutation; the
Auditor audits that run's commit. No target-graph PR is needed, and later merges don't invalidate it.
Only a stale **source** graph (a re-pinned `source.lock`) needs afs-understand `side=source` and its PR
first. Remote sessions can't run workflows, so starting the run is the dispatcher's step.

## 2. Ticket reconciliation
**Ticket reconciliation (ADR-0030), before completing the slice or closing its epic.** After
the work has reached `main`, ensure every related work, fix, verifier and bootstrap issue is linked
beneath the slice epic, then enumerate its descendants; do not include unrelated slices or
decision-map/research issues. Generate
`.migration/evidence/ticket-reconciliation/<epic>.yaml` with `reconcile_epic.py --repo <r> --epic <n>`
(ADR-0049): it writes each disposition it can prove and marks the rest `needs_review`. Review every
entry, fill in each `needs_review` one, remove that key, then commit. Each issue has exactly one disposition: `completed` with landing PR(s) and committed
role return(s), `superseded` with a replacement issue plus the closed-unmerged failure PR and that
role's own failed return (or, for a session killed before it could write one, `failure.session_run`: its
own cancelled, timed-out or failed agent run; for a session that stopped and handed off, `failure.handoff`:
the `.migration/handoffs/<ticket>.md` its PR committed, with blockers), or `retained-open` with actual outstanding work and blocker. A completed
return must identify this issue directly or through same-path, same-ticket/role committed history; its
owning PR must be cited and contain that return. A continuation child that wrote its parent ticket's
return cites its own landing PR; the snapshot that PR landed is its evidence. A closed-unmerged PR counts as completed only when
its exact head is in `main` ancestry; a later carrier PR may provide that landing. A return file, green
check or closed PR alone is not landing or acceptance evidence.
Preserve unchanged pre-rule null-PR returns only through the validator's existing Git-history proof,
with an exact snapshot in a cited landed PR and a passing role outcome; never rewrite inherited outputs.
Your own acceptance ticket, and any issue your PR closes, is `completed` with your PR: your PR's CI checks the file
as if it were merged (`ticket_guard.py --reconcile-epic <epic> --as-if-merged <PR>`; sessions have no
GitHub token to run it, so read that job's errors). Commit the report on `main` through human review. The AFS map-fog workflow checks it before the
existing return-file gate; missing or invalid reconciliation reopens the epic and suppresses fog
re-walk. The checker never closes work issues. A retained-open descendant remains open and continues
to block epic closure under ADR-0024.
## 3. The acceptance return
Commit it as `.migration/returns/<acceptance-ticket>.afs-program-orchestrator.yaml`, with your usual
orchestrator return plus an `acceptance` block. `check_signoff.py` and `check_slice_returns.py` read the
block, as they read a retired Slice Coordinator's return:
```yaml
acceptance:
  slice: <name>
  tickets: {total: <n>, merged: <n>, open: <n>, blocked: ["<link: blocker>"]}
  report: <.migration/evidence/<slice>/report.md>
  gates: <all-green, or the failing gate names>
  mutation_score: <0-1>
  coverage_gaps: <n>
  human_check: <requested | passed | issues | deferred>
  human_check_issues: [<link>]        # with issues
  human_check_issue: <link>           # with deferred: the open issue, assigned to an approver
  human_check_due: <YYYY-MM-DD>       # with deferred: 7 days by default, at most 30
  quirk_tickets: [<link>]
```
