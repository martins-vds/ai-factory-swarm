# ADR-0030: Reconcile slice tickets before coordinator completion

- Status: Accepted
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
    history. Its owning PR must be among the cited landing PRs and contain the exact committed return.
    This supports a correction carried by a later PR without treating a closed PR as proof. Applicable
    outcomes are checked against their role contracts: Verifier returns must pass, Bootstrapper validation
    must explicitly pass (including pass-with-limitations), Migrator gates must show passing outcomes with
    no outstanding handoff, Characterizer cases must all pass, and Auditor verdicts must be complete.
    The validator's existing unchanged pre-rule null-PR exemption remains valid only with its original
    Git-history proof and an exact return snapshot in a cited landed PR. Missing history or a later return
    edit requires the owning PR normally; this exemption never establishes a passing role outcome.
  - `superseded`: the issue is closed as not planned, links a replacement issue, and preserves a closed,
    unmerged failed role PR plus that role's explicit failure return at the PR head. Supported outcomes
    include Verifier changes-required/blocked, Bootstrapper fail/blocked validation, Migrator failed gates
    or blocker handoff, Characterizer failing cases, and Auditor gaps-remain. The return must belong to the
    superseded issue and identify the same owning PR; for example, a Bootstrapper's blocked validation is
    preserved as Bootstrapper evidence, not rewritten as a Verifier result.
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
