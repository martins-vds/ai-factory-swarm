# ADR-0030: Reconcile slice tickets before coordinator completion

- Status: Accepted; amended 2026-11-07 (killed sessions)
- Date: 2026-11-05

## Context

ADR-0029 prevents a ticket from closing as completed while a fixing PR into the default branch remains open.
It does not require the reverse: after work lands, wrapper, verifier, bootstrap and superseded-attempt
issues can remain open or lose a clear disposition. A slice epic can therefore look complete while its
related issue tree is stale.

## Decision

- Before coordinator completion or slice-epic closure, the coordinator commits
  `.migration/evidence/ticket-reconciliation/<epic>.yaml` on the default branch. The report names the
  exact scope `slice-epic-descendants` and lists every descendant work issue except decision-map and
  research issues, which are outside the slice.
- Each issue has exactly one disposition:
  - `completed`: the issue is closed as completed, lists landing PRs and committed role returns, and the
    checker confirms the merged PR's merge commit or a closed-unmerged PR's exact head is in default-branch
    ancestry. A return must identify this issue directly or through same-path, same-ticket/role committed
    history. A parent-ticket return may cover its direct child only when GitHub confirms the parent
    relationship, the relevant child-closing PR is cited and contains the exact return (or same-path,
    same-ticket/role history), and the current applicable role outcome passes. A superseding return that
    names a sibling must have the same verified direct parent. The current return must match its committed
    HEAD snapshot, and its own cited owning PR must contain that exact snapshot in default-branch history;
    historical attribution alone never proves the current result. Parent-ticket continuation separately
    requires a cited or GitHub-referenced PR whose body closes the direct child, whose landed snapshot
    contains the same-path, same-ticket/role return, and whose changed-file list confirms it changed that
    return file. The child-work PR may differ from the current owner PR. The current owner must prove the
    exact current passing snapshot; it need not close the parent when the child-work PR independently proves
    the child. A current return naming a sibling must still have a verified parent and an owner that closes
    that sibling. This supports a correction carried by a later PR without treating a closed PR as proof.
    Ordinary same-path supersession remains distinct: a
    historical return that directly identifies the reconciled issue may establish its attribution even if
    that issue is itself below the slice epic and the latest return names its own child issue. A required
    current owning PR must still have a verified landing containing the exact current return; historical
    identity alone does not establish that landing. Applicable
    outcomes are checked against their role
    contracts: Verifier returns must pass, Bootstrapper validation must explicitly pass (including
    pass-with-limitations), Migrator gates must show passing outcomes with no outstanding handoff (`none`
    means no handoff, and contract-permitted reasoned `n/a` is valid for non-applicable measured gates),
    Characterizer cases must all pass, and Auditor verdicts must be complete.
    The validator's existing unchanged pre-rule null-PR exemption remains valid only with its original
    Git-history proof and an exact return snapshot in a cited landed PR. Missing history or a later return
    edit requires the owning PR normally; this exemption never establishes a passing role outcome.
    **Amendment (2026-11-09, found by the pilot's BK-RECON):** Planner, Auditor and Coordinator returns carry
    no `pr:` field, and a continuation child (restarts #262 and #276 of BK-04, re-audit #477 of BK-05J) writes
    its parent ticket's return, which a later sibling may rewrite. Such a child is attributed when one of its
    own cited landed PRs closes it, changed the return file, and landed a snapshot of that return that names
    the parent issue and passes its role contract. That landed snapshot, not the later HEAD rewrite, is the
    evidence checked for outcome and containment.
  - `superseded`: the issue is closed as not planned, links a replacement issue, and preserves a closed,
    unmerged failed role PR plus that role's explicit failure return at the PR head. Supported outcomes
    include Verifier changes-required/blocked, Bootstrapper fail/blocked validation, Migrator failed gates
    or blocker handoff, Characterizer failing cases, and Auditor gaps-remain. The return must belong to the
    superseded issue and identify the same owning PR; for example, a Bootstrapper's blocked validation is
    preserved as Bootstrapper evidence, not rewritten as a Verifier result.
    **Amendment (2026-11-07, martins-vds: "Yes in the reconciliation rule"):** a session killed before it
    could write a return (on the pilot, a Coordinator stopped by the cloud agent's one-hour limit) can't
    meet that. Its failure may instead cite `failure.session_run`, the agent session's own Actions run id.
    The checker requires that run to be an agent session run on the failure PR's branch that ended
    cancelled, timed out or failed. The PR must have no return file; a session that wrote one is judged by it.
    **Amendment (2026-11-09, found by the pilot's BK-RECON):** a session that stopped and handed off instead
    of writing a failed return (pilot BK-ACCEPT #470: Copilot's firewall blocked it; restarted as #473) may
    cite `failure.handoff`: a `.migration/handoffs/<ticket>.md` file that the failure PR changed and that,
    at the PR head, holds a `## Handoff` section with `### Blockers`. A handoff is a stop with reasons, not
    a pass, so it is accepted only as failure evidence, never as completion evidence.
  - `retained-open`: the issue remains open and states the outstanding work and actual blocker. It is not
    represented as completed or automatically closed.
- The AFS map fog workflow checks this report before the existing ADR-0024 return-file check. A missing,
  incomplete, invalid, or unverifiable report fails the workflow, reopens the epic with the problems, and
  prevents the fog re-walk. The check is limited to descendants of that slice epic; unrelated slices and
  decision-map/research issues are not treated as stale.
- The checker reports and verifies evidence only; it never closes work issues or authorizes a merge or
  acceptance. The coordinator reviews evidence and performs any issue-closure actions with human authority.
  An open descendant still blocks epic closure under ADR-0024, even when its retained-open disposition is
  accurately recorded.
- Complete Git history and the GitHub API are required evidence. Missing API data, inaccessible return
  content, shallow history or unavailable commits fail explicitly; no success-shaped fallback is allowed.

## Consequences

- The coordinator must reconcile wrapper issues across the slice's issue tree, not only the issue named by
  the last PR's auto-closing reference.
- A closed-unmerged PR is accepted as landing evidence only when its exact head is part of default-branch
  history; PR closure and green checks alone are insufficient.
- Existing premature-closure reopening, slice return validation and fog re-walk semantics remain in force.
- The report is a bounded slice artifact, not a general-purpose issue-management service.

### Amendment (2026-11-08): the reconciliation file is checked in the coordinator's PR

On the pilot, the booking Slice Coordinator's PR (#474) merged green with a reconciliation file that
had 15 problems. The check only ran when the epic closed, after the merge, and it reopened #224. Some of
the problems were timing: the coordinator's own ticket was still open while it wrote the file, so no
disposition for it could pass both before and after the merge.

A new harness-check job, **Ticket reconciliation holds once merged**, runs on every pull request that
changes `.migration/evidence/ticket-reconciliation/<epic>.yaml`. It runs `ticket_guard.py
--reconcile-epic <epic> --as-if-merged <PR>` on the PR's merge commit: the issues the PR closes count as
closed as completed, and the PR counts as landed at HEAD. Everything else is checked exactly as at epic
close, so a wrong disposition fails the PR, not the epic. The job only reads (issues and pull requests),
never reopens anything, and the epic-close check stays as the backstop. A coordinator marks its own
ticket `completed` with its own PR.

## Amendment (2026-11-10, found by the synthetic target's LC-ACCEPT)
Under ADR-0040, a Verifier's PR merges into the migrator's branch, and that branch reaches the default branch
as one squash commit. The Verifier PR's own merge commit never enters the default branch, so reconciliation
reported "no verified landing" for every Verifier ticket. A PR merged into another PR's branch now lands
with that PR: the PR whose head was its base, merged after it, with a verified landing (recursively, for
deeper stacks). Containment and outcome checks then run against that landing commit, so content the later
squash didn't carry still fails.
