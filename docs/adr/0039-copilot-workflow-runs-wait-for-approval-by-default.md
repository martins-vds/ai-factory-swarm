# ADR-0039: Workflow runs on Copilot PRs wait for a person's approval by default

- Status: Accepted (martins-vds, 2026-11-08: "I'd like to keep the approval on (secure defaults)")
- Date: 2026-11-08
- Amends: operator checklist item 4 (`docs/operator-setup.md`, `bootstrap.py`)

## Context
When the Copilot cloud agent pushes to a pull request, GitHub doesn't run the repository's Actions
workflows until someone with write access clicks **Approve and run workflows**. A repository setting can
turn that off. The operator checklist used to require turning it off, so every agent push would be
checked at once.

Turning approval off means:

- **Workflows from the agent's branch run with the repository's secrets.** For a pull request from a
  branch in the same repository, GitHub runs the workflow files *from that branch*. If a session adds or
  edits a workflow, that edit runs before anyone has read it, and it can read every Actions secret: on a
  target that's `AFS_STACK_TOKEN` (write access), and `SOURCE_READ_TOKEN` and `BILLING_READ_TOKEN`
  where they're set.
- **The agent can be steered.** A session follows what it reads: issue text, legacy code, documents,
  web pages. Text written to steer it (prompt injection) could ask it to add a step that sends a secret
  elsewhere.
- **The harness check detects, it doesn't prevent.** `check_installed.py` fails a PR that changes a
  harness-managed file, workflows included. With approval off, that check runs after the changed
  workflow has already run.

## Decision
**Approval stays on by default.** A person approves the workflow runs on every Copilot PR push. Bootstrap's
operator checklist and the operator guide name approval-on as the default, and turning it off as an
operator's choice per repository, taken with the mitigations below.

- **The dispatcher never approves workflow runs**, whether Claude, an L0 agent or a script. The click is
  the human review; automating it would remove the control while keeping the delay.
- **Before approving,** the person looks at what the push changed under `.github/` (workflows, hooks,
  agents, skills) and `.migration/harness/`. A harness-managed file should never change in an agent PR,
  so any change there is a reason to stop, not approve.

## Consequences
- **A Copilot PR's checks start only after a person approves.** Until then they show "action required".
  The dispatcher reports which PRs are waiting, rather than reading the wait as a failure.
- **Each new push needs another approval.** A session that pushes several times needs several clicks to
  have CI check its final state.
- **Self-healing isn't affected.** The stop hook (`afs-finish-check`, ADR-0034) runs inside the agent's
  own session, so a session still repairs its return file and scope before it ends. Only the PR's CI
  waits.
- **Merges wait for the checks.** The dispatcher merges only green PRs that the operator has named, so
  an unapproved PR is never merged.
- **Pushes that aren't Copilot's run at once.** That covers stack refresh (ADR-0038), harness rollouts
  and the dispatcher's own commits.

## Changing it
Per repository: **Settings → Copilot → Cloud agent** ("Coding agent" on some accounts) → **Actions
workflow approval** → **Require approval for workflow runs**. On is this ADR's default; off lets workflows
run without a person. For a single push, use **Approve and run workflows** in the PR's merge box. Record a
repository that runs with approval off, and why, in its operator notes.

## Mitigations (always, and required before turning approval off)
1. **One `AFS_STACK_TOKEN` per repository.** A fine-grained token for that repository only, with Contents
   and Pull requests read and write. A secret leaked from one target then can't write to another.
   Give it an expiry.
2. **Protect the default branch.** A ruleset on `main` requiring a pull request (and passing checks)
   means even a leaked write token can't change `main` directly. Stack refresh only pushes to PR
   branches, so it keeps working.
3. **Least privilege in workflows.** Harness workflows declare their `permissions`, read-only unless a job
   needs more (for example, the graph job opens a PR). Set the repository's default workflow permissions to read-only (Settings → Actions →
   General → Workflow permissions).
4. **Watch `.github/`.** A CODEOWNERS entry for `.github/` and `.migration/harness/` makes a change
   there need the owner's review before merge, and the harness check (`check_installed.py`) fails such a
   PR.
5. **Keep secrets few and narrow.** Only add `SOURCE_READ_TOKEN` (private sources) and
   `BILLING_READ_TOKEN` (cost tracking) where they're needed. Each should be read-only and scoped to one
   repository or account.
6. **Keep what the agent reads trustworthy.** Only people with write access can assign work to Copilot.
   Treat issue text from outside contributors, and web content an agent fetches, as untrusted.
