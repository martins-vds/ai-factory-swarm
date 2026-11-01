# Review: agent inputs and outputs that don't survive (M5)

Requested by martins-vds on 2026-11-01, after a return contract had to be copied from a PR comment
into a PR description by hand (pilot #38).

**The root cause:** the agent instructions assumed every agent could write to the tracker
(comments, issues, labels, PR descriptions, assignments). Remote Copilot coding-agent sessions can only
push commits to their own branch. Anything an agent was told to put in the tracker was therefore either
lost, or depended on a human to carry it over.

**Design rule adopted:** everything an agent must leave behind is a **committed file on its branch**,
in the same PR as the work. Tracker writes and dispatch belong to whoever holds a user token: L0 or the
operator. (See `afs-migration-contract` → *Durable outputs* and `agents/README.md` → *Where each role
can run*.)

## Fixed in this change

| # | Gap | Seen in | Fix |
|---|---|---|---|
| 1 | Return contract lived in the PR description. It is lost after merge, has no history, and a follow-up session cannot edit it. The CI check only tested that the keys existed | pilot #5, #38 | Committed `.migration/returns/<ticket>.<role>.yaml`. `schemas/return.schema.json` is generated from the agents' contract blocks (`tools/gen_return_schema.py`, drift-checked in CI) and validated by `validate.py`. CI requires an agent PR to change one, with an `issue:` that matches the PR's `Fixes #N` |
| 2 | Handoffs were issue comments, which remote sessions cannot post | TC-01 (#36): "handoff comment not posted" | `.migration/handoffs/<ticket>.md`, committed. A resuming session reads the last section |
| 3 | Gate evidence pointed to `.migration/runs/…` logs. Those are gitignored and vanish with the session, so the ledger and return contracts cited files nobody can open | TC-01, TC-02 `evidence_logs` | `afs-run` appends to a committed run journal, `.migration/evidence/runs/<ticket>.md` (time, gate, exit, seconds, command, log SHA-256, first highlight). `evidence_logs` points there |
| 4 | The per-PR evidence table lived in the PR description | `afs-evidence` | The run journal plus the return file's `gates` map are the evidence; the description is a summary |
| 5 | Quirk drafts could be merged without ever becoming issues | process gap | CI fails while `.migration/quirks/*.md` exists. The orchestrator opens the drafts as issues, links them and removes the files |
| 6 | CRAP was only self-reported | TC-01 contract | The generated CI gates job runs the profile's `crap` gate after the tests |
| 7 | A remote Slice Coordinator was told to dispatch by assigning issues, and agents to claim by assigning. Neither works without a user token | agent text | Dispatch, claims, labels and blocking edges belong to L0 or the operator. The coordinator runs locally or asks L0 |
| 8 | The Verifier is told to check "someone else's PR", but a remote session always starts its own branch | agent text | Dispatch it with `base_branch` set to the PR's head branch; its PR targets that branch |
| 9 | Graph reports showed a commit id that "differs from the pinned source" (the workflow's throwaway commit), and the Analyst reported it as a discrepancy | pilot #11 | `graph-check.md` starts with the pinned source and explains that commit id |

## Open, not fixed here

| # | Gap | Impact | Proposal |
|---|---|---|---|
| 10 | **The mutation gate is self-reported only.** The profile's `mutation_changed` uses a `{changed}` placeholder that no tool fills in, and mutmut 2.x's exit code doesn't enforce a score | The ≥ 0.8 threshold rests on the agent's word (TC-01 failed it; TC-02 reported 35/35) | Add an `afs-mutation` wrapper that computes changed paths, runs mutmut, parses the score and fails below the threshold. Run it in CI for changed domain code, and have the Verifier re-run it |
| 11 | Workflow runs on Copilot PRs wait for approval, so CI only runs after a human or L0 pushes; today that's an empty "Trigger CI" commit | Noisy history; checks are late | Repo setting (Actions → approval for Copilot), or L0 approves through the UI |
| 12 | `self-learning` saves generated skills to `.agents/skills/` with the VS Code `create_file` tool | In a Copilot session the skill lands where Copilot doesn't load it, and editing `.github/skills/` would trip the drift check | Owner's skill: due for the changes martins-vds wants to discuss. Suggestion: write proposals to `.migration/skills-proposed/` for a harness PR |
| 13 | `lessons-learned` maintains a shared `docs/lessons/_index.md` | Parallel agent PRs will conflict on the index | Owner's skill: cards only per PR; regenerate the index on `main` (L0 or CI) |
| 14 | Agents missed inputs that were present (the Planner reported the graphs absent) | Wrong open questions; wasted review | Tickets name exact paths (done since #19). Consider an `afs-setup-check` step that lists the inputs the ticket names and fails if one is missing |
| 15 | The graph workflow can't open its PR unless "Allow GitHub Actions to create pull requests" is on | L0 opens it by hand | Repo setting |
