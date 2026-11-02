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
| 8 | **Copilot firewall lets setup steps pull the compose images** (ADR-0016): if blocked, add the registry (e.g. `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com`) to the allowlist | Settings → Copilot → Coding agent → Firewall | Setup steps start the target's test services with `afs-services up` | `afs-setup-check` reports `services DOWN`; agents stop instead of testing |

| 9 | **Graph first** (ADR-0020): after the setup PR merges, run **AFS understand (code graphs)** with `side=source` on `main`, review its PR (the graph gate and the list of entry points that reach data), and merge it | Actions → AFS understand → Run workflow | Analysis and planning query the graph; a graph that can't reach the data hides capabilities | Planner and Analyst stop at setup; CI fails on slice anchors that reach no data |

## What the code graph contains

Understand Anything (UA) builds the graph with an LLM. For data and routing it only uses explicit artifacts:

| Graph content | UA alone | Added by the harness enricher (ADR-0020) |
|---|---|---|
| `table` nodes | SQL DDL / migration files only | `java-ee`: JPA `@Entity`/`@Table` · `django`: `models.Model` (`db_table`) |
| `reads_from` / `writes_to` | never | `java-ee`: EntityManager queries, `find`, `persist`/`merge`/`remove` · `django`: `Model.objects.*`, `.save()`/`.delete()` |
| `endpoint` nodes | OpenAPI / Swagger specs only | `java-ee`: JAX-RS `@Path` + verbs · `django`: `urls.py` `path()`/`include()` |
| `page` nodes and `routes` | infrastructure routing config only | `java-ee`: JSF `*.xhtml`, EL `#{bean…}` → `@Named` bean, `ui:include`/templates · `django`: views → `render(template)` |
| `calls` between classes | sparse (LLM-chosen) | `java-ee`: `@Inject`/`@EJB` fields · `django`: imports, typed parameters and `self.` attributes |
| interface → implementation | partial | `implements` from `implements`/Protocol/ABC bases |
| asynchronous hops | never | `java-ee`: JMS producers → queue → `@MessageDriven` consumers |

A stack without an enricher has only the UA column. That is a **capability gap** ("graph data links") at
bootstrap, not something to discover at acceptance. Enricher-added nodes and edges are tagged
`afs-enriched:<rule>`. `graph-check.md` in each graph PR shows the gate and the entry points without a path
to data. Review them: templates and static pages are expected there; a screen that loads data is not.

## Recommended
- Branch protection on `main`: require the **AFS harness check** jobs (harness, return file, gates).
- After the first push of the generated workflows, check that `Actions` lists them. A brand-new repo
  only picks up workflows once they are on the default branch.
