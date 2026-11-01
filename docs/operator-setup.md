# Operator setup: the target repository

Things a human with admin rights on the **target repo** must do. Bootstrap cannot do them (they are
repository settings or secrets), and the swarm does not work fully without them. Bootstrap prints this
list, and the setup PR repeats it as a checklist.

## Required

| # | Setting | Where | Why | Symptom if missing |
|---|---|---|---|---|
| 1 | **Actions enabled**, "Allow all actions and reusable workflows" | Settings → Actions → General | CI, Copilot setup steps and the graph workflow are GitHub Actions | No workflow runs at all |
| 2 | Workflow permissions: **"Allow GitHub Actions to create and approve pull requests"** | Settings → Actions → General → Workflow permissions | `afs-understand.yml` opens its graph PR with `GITHUB_TOKEN` | Graph branch pushed, but no PR (`::notice::` in the run) |
| 3 | **Copilot coding agent enabled** for the repository | Settings → Copilot → Coding agent (or org policy) | Remote workers are Copilot coding-agent sessions with the `afs-*` custom agents | Assigning an issue to Copilot does nothing |
| 4 | **Workflow runs on Copilot PRs don't wait for approval** | Settings → Actions → General (approval for workflows from Copilot / outside collaborators), or org policy | CI must check every agent push | Runs show "action required"; someone has to push or approve before checks run |
| 5 | **Public repo or Actions budget** | Settings → Billing (account or org) | Copilot sessions and CI consume Actions minutes on private repos | Jobs "not started because recent account payments have failed or your spending limit needs to be increased" |
| 6 | `SOURCE_READ_TOKEN` secret, **private sources only**: a fine-grained PAT with Contents: Read-only on the source repo only | Settings → Secrets and variables → Actions, **and** Settings → Environments → `copilot` | Remote sessions and workflows check out the pinned source | `.source/` missing; `afs-setup-check` stops |
| 7 | A user token for the **dispatcher** (L0 or you): `gh` logged in as a user with write access | Where the Program Orchestrator runs | Assigning issues to Copilot with a custom agent, opening quirk and gap issues, blocking edges, merges. Remote sessions cannot do these | Tickets are never dispatched; quirk drafts stay in PRs (CI fails on them) |

## Recommended
- Branch protection on `main`: require the **AFS harness check** jobs (harness, return file, gates).
- After the first push of the generated workflows, check that `Actions` lists them. A brand-new repo
  only picks up workflows once they are on the default branch.
