# ADR-0031: A slice's human sign-off is an approving PR review

- Status: Accepted (martins-vds, 2026-11-06: "Approving PR review")
- Date: 2026-11-06

## Context
ADR-0006 requires a human side-by-side check before a slice is accepted. A Slice Coordinator records it
as `human_check: passed` in its return file. On the pilot, the handling-registration sign-off reached
the record second-hand: a coordinator session asked the operator, then posted the answer as a comment
under the operator's own GitHub login. The comment was honest, but nothing in it shows who acted: any
agent session that holds the operator's login can write the same comment, or the same line in a return
file. A sign-off that an agent can produce is not evidence of a human check.

The options were:
1. **A signed commit**, with a key that only the approver holds. This is the strongest option, but
   only if the key needs a touch or a passphrase, and it adds setup for every approver.
2. **An approving PR review** by a named approver. It's GitHub's ordinary approval act and needs no
   setup. A session holding the approver's own login could still submit it.
3. Both.

The operator chose option 2.

## Decision
1. **The sign-off is the review.** A Slice Coordinator's return with `human_check: passed` counts only
   with an `APPROVED` review on its PR by a login in the profile's `signoff.approvers`, on the PR's
   current head commit. The approver's latest decisive review counts, so a later "changes requested"
   or a dismissal withdraws the approval. A push after the approval makes it stale, so the approval
   covers exactly what lands.
2. **Checked by a tool, in its own workflow.** `tools/check_signoff.py` runs from the generated
   `afs-signoff.yml`:
   - on PR events, and again whenever a review is submitted or dismissed;
   - on every push to the default branch. There it finds the PRs containing the commit that set
     `passed`, so a merge made with plain git still needs the approval.

   A change with no new sign-off passes. Earlier returns are not judged again.
3. **Agents never sign off.** The coordinator commits `passed` and asks an approver to approve. It
   never submits a review, relays an answer as a sign-off, or approves on anyone's behalf, even when it
   holds the approver's login.
4. **Who approves is configuration**: `signoff.approvers` in the profile. With nobody listed, a
   sign-off fails and names the setting.

## Consequences
- GitHub doesn't let a PR's author approve it, so the PR that records the sign-off must come from a
  login that isn't an approver: the Copilot coding agent, or another account. A coordinator that runs
  under the approver's login opens it through the coding agent.
- **Residual risk:** a session holding an approver's login could submit the review. The rule in 3
  forbids it, but GitHub can't tell the difference. If that risk matters, a signed commit (option 1)
  can be added later as a second requirement.
- A slice's sign-off is auditable from the PR: who approved, which commit, and when.
