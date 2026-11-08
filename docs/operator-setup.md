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
| 4 | **Workflow runs on Copilot PRs don't wait for approval** | Settings → Copilot → Cloud agent ("Coding agent" on some accounts) → Actions workflow approval: turn off **Require approval for workflow runs** | CI must check every agent push | Runs show "action required"; someone has to push or approve before checks run |
| 5 | **Public repo or Actions budget** | Settings → Billing (account or org) | Copilot sessions and CI consume Actions minutes on private repos | Jobs "not started because recent account payments have failed or your spending limit needs to be increased" |
| 6 | `SOURCE_READ_TOKEN` secret, **private sources only**: a fine-grained PAT with Contents: Read-only on the source repo only | Settings → Secrets and variables → Actions, **and** Settings → Environments → `copilot` | Remote sessions and workflows check out the pinned source | `.source/` missing; `afs-setup-check` stops |
| 7 | A user token for the **dispatcher** (L0 or you): `gh` logged in as a user with write access | Where the Program Orchestrator runs | Assigning issues to Copilot with a custom agent, opening quirk and gap issues, blocking edges, merges. Remote sessions cannot do these | Tickets are never dispatched; quirk drafts stay in PRs (CI fails on them) |
| 8 | **Copilot firewall lets setup steps pull the compose images** (ADR-0016): if blocked, add the registry (e.g. `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com`) to the allowlist | Settings → Copilot → Coding agent → Firewall | Setup steps start the target's test services with `afs-services up` | `afs-setup-check` reports `services DOWN`; agents stop instead of testing |
| 9 | **Graph first** (ADR-0020): after the setup PR merges, run **AFS understand (code graphs)** with `side=source` on `main`, review its PR (the graph gate and the list of entry points that reach data), and merge it | Actions → AFS understand → Run workflow | Analysis and planning query the graph; a graph that can't reach the data hides capabilities | Planner and Analyst stop at setup; CI fails on slice anchors that reach no data |
| 10 | *(Optional, cost tracking)* **`BILLING_READ_TOKEN` secret** for the account that **pays** for Copilot, named in profile `costs.billing` (see below) | Settings → Secrets and variables → Actions | The daily **AFS costs** workflow records billed AI credits and Actions minutes and attributes them to sessions (ADR-0021) | The workflow only warns; session records still hold tokens, but no billed credits |
| 11 | **Who signs off slices** (ADR-0031): profile `signoff.approvers`, the GitHub logins whose approving review on the coordinator's PR is the human sign-off. Open that PR from the Copilot coding agent (or any login that isn't an approver): GitHub doesn't let a PR's author approve it | `.migration/profile.yaml` | `human_check: passed` is only a claim; the approver's review on the exact head commit is the sign-off | **AFS human sign-off** fails on the PR and on `main` |

**Merge the setup PR first.** Copilot's setup steps (`copilot-setup-steps.yml`) run only from the default
branch, while hooks in `.github/hooks/` are read from the branch a session works on. A session based on an
unmerged setup branch therefore gets the RTK pre-tool hook without RTK, and every tool call fails. On the
synthetic target two Bootstrapper sessions ended with nothing done this way. Fix a setup PR from your own
clone; dispatch sessions once it is on the default branch.

## Slice completion and ticket reconciliation

Before a coordinator completes a slice or closes its epic, require the committed
`.migration/evidence/ticket-reconciliation/<epic>.yaml` report (ADR-0030). It must cover the slice epic's
related work/fix/verifier/bootstrap descendants, with one evidence-backed disposition per issue:

- `completed`: closed as completed, with role return(s) and landing PR(s) whose merge commit or exact
  closed-unmerged head is in default-branch history. A return must identify the issue directly or through
  same-path, same-ticket/role history; its owning PR must be cited and contain the committed return.
  Existing unchanged pre-rule null-PR returns retain the validator's Git-history exemption, but still
  need an exact snapshot in a cited landed PR and a passing applicable role outcome. Never retrofit them.
- `superseded`: closed as not planned, with a replacement issue and the original failed role's PR/return
  preserved (for example, retain a blocked Bootstrapper return as Bootstrapper evidence);
- `retained-open`: still open, with specific outstanding work and its actual blocker.

```yaml
epic: 99
scope: slice-epic-descendants
issues:
  - number: 123
    disposition: completed
    pull_requests: [124]
    returns: [.migration/returns/T-123.afs-verifier.yaml]
  - number: 125
    disposition: superseded
    replacement: 123
    failure: {pull_request: 126, return: .migration/returns/T-125.afs-verifier.yaml}
  - number: 127
    disposition: retained-open
    outstanding: "Finish the data import."
    blocker: "Waiting for the operator-owned production snapshot."
```

The generated AFS map-fog workflow checks this report before the existing return-file check. If it is
missing or evidence cannot be verified, the workflow reopens the epic and does not create the fog re-walk
task. The checker never closes work issues or merges PRs: review the evidence and keep those actions under
human authority. Decision-map/research work and unrelated slices are outside the reconciliation scope.
Retained-open descendants remain open and still prevent epic closure under ADR-0024.

## Cost tracking: which billing account and token

Copilot usage is billed to whoever provides the seat, which isn't necessarily you. Set `costs.billing` in
the profile to that account:

| Copilot is billed to | `costs.billing` | `BILLING_READ_TOKEN` must be |
|---|---|---|
| Your personal plan | `{scope: user, account: <login>}` | a fine-grained PAT for your user with **Plan: read** |
| An organization (seat from the org) | `{scope: organization, account: <org>}` | a fine-grained PAT whose **resource owner is the org**, with organization **Administration: read**, created by an **org owner or billing manager**, in an org that allows fine-grained PATs |
| An enterprise | `{scope: enterprise, account: <enterprise-slug>}` | a token of an **enterprise owner or billing manager** with **Enterprise billing: read**, or a GitHub App installed on the enterprise with that permission |

Usage of a seat billed through an organization or enterprise does **not** appear in the user endpoint, so
the scope must match the payer. If you're unsure, look at Settings → Copilot ("Usage billed to"). The
organization and enterprise reports cover everyone on that account; `afs-costs` attributes only the days
with harness sessions, and says it's an estimate.

## What the code graph contains

Understand Anything (UA) builds the graph with an LLM. For data and routing it only uses explicit artifacts:

| Graph content | UA alone | Added by the harness enricher (ADR-0020) |
|---|---|---|
| `table` nodes | SQL DDL / migration files only | `java-ee`: JPA `@Entity`/`@Table` · `django`: `models.Model` (`db_table`) |
| `reads_from` / `writes_to` | never | `java-ee`: EntityManager queries, `find`, `persist`/`merge`/`remove` · `django`: `Model.objects.*`, `.save()`/`.delete()` |
| `endpoint` nodes | OpenAPI / Swagger specs only | `java-ee`: JAX-RS `@Path` + verbs · `django`: `urls.py` `path()`/`include()` |
| `page` nodes and `routes` | infrastructure routing config only | `java-ee`: JSF `*.xhtml`, EL `#{bean…}` → `@Named` bean, `ui:include`/templates · `django`: views → `render(template)` |
| `calls` between types and functions | sparse (LLM-chosen) | **Graphify** (ADR-0025, any language it parses): calls, instantiation and typed parameters · `java-ee`: CDI `@Inject`/`@EJB` wiring |
| interface → implementation | partial | **Graphify**: `implements`, and `inherits` from a `Protocol`/`ABC` base |
| asynchronous hops | never | `java-ee`: JMS producers → queue → `@MessageDriven` consumers; CDI `Event<T>.fire` → `cdi-event` → `@Observes` · `django`: `f.defer()`/`.delay()` → `task` → the task function |
| scheduled and batch entry points | never | `java-ee`: `@Schedule` → `timer`; `JobOperator.start("J")` → `batch-job J` → its XML `ref=""` beans · `django`: `management/commands/<name>.py` → `command` |
| push and script calls from pages | never | `java-ee`: `@ServerEndpoint` → `WS /path` · both: page scripts' `fetch(url)`, `new WebSocket(…"/path")` and htmx `hx-get`/`hx-post`… (`{% url 'ns:name' %}` or a literal path) → `routes` to the matching endpoint; `{% include %}`/`{% extends %}` → `contains` |

**The target graph analyses only `graph.target_paths`** (default `src`). Templates in a top-level
`templates/` folder are pages too: list that folder, or the graph can't see them. `check_graph_fresh.py`
reports every tracked Django template outside the analysed paths, and fails on it at acceptance. A
folder with templates that aren't application pages goes in `graph.target_exclude`.

A stack without an enricher has only the UA column. That is a **capability gap** ("graph data links") at
bootstrap, not something to discover at acceptance. Enricher-added nodes and edges are tagged
`afs-enriched:<rule>`. `graph-check.md` in each graph PR shows the gate and the entry points without a path
to data. Review them: templates and static pages are expected there; a screen that loads data is not.

## Recommended
- Branch protection on `main`: require the **AFS harness check** jobs (stack base, harness, return file,
  gates). The stack-base job blocks the other jobs when a stacked PR's base lacks the current default
  branch or its head lacks the current base. Merge the default branch into the work branch, then the
  updated work branch into its stacked heads and push; rerunning old checks does not refresh their
  merge commit.
- After the first push of the generated workflows, check that `Actions` lists them. A brand-new repo
  only picks up workflows once they are on the default branch.
