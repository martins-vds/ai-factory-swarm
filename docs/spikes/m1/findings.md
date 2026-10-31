# M1 spike findings

Runs on GitHub-hosted runners in [ai-factory-pilot-target](https://github.com/martins-vds/ai-factory-pilot-target)
(branch `spikes/m1-run`, workflow `spikes-m1.yml`), 2026-10-30. Raw results are committed on that branch
under `spike-results/` (run 4 for spikes 1 and 3, run 5 for spike 4, run 8 for spike 5). Spike 2 ran as Copilot coding
agent sessions on issues #1 and #3 (reports in PRs #2 and #4). Source: code-migration-hackathon
`c2df760`, folder `java/`.

| Spike | Status | Headline |
|-------|--------|----------|
| 1 · Graph | ✅ ran | Works via the Copilot SDK with the Actions token, after a one-line skill fix. Business flows are excellent; screens and tables appear as tags, not typed nodes. |
| 2 · Remote agent | ✅ ran | Pinned, read-only source works in the Copilot coding agent; RTK's hook rewrites commands there transparently. The probe also surfaced a real quirk. |
| 3 · CRAP / mutation | ✅ ran | Source risk map in 6 s with no build. Legacy build cannot run outside the org. Mutation testing catches what coverage hides. |
| 4 · RTK | ✅ ran | 50–90% smaller output, failures stay diagnosable, full output recoverable. Apache-only edition available. |
| 5 · Tier-B characterization | ✅ ran | The legacy code compiles and runs in isolation from source alone: 312 classes, public artifacts plus 3 stand-ins, 13 characterization tests passing. |

---

## Spike 1 — Understand Anything via the GitHub Copilot SDK

**Setup.** Copilot SDK (Python) 1.0.28, Copilot CLI 1.0.105, Understand Anything 2.9.8 loaded as a plugin
directory. Target: the currency slice (31 files: 29 classes, `currency.jspx`, trimmed `admin-config.xml`).

**Auth: the Actions `GITHUB_TOKEN` works.** With `permissions: copilot-requests: write`, both the CLI and
the SDK answered using `GITHUB_TOKEN`, in a repository owned by a personal account. No personal access
token or extra secret is needed. *To confirm:* which account the usage was billed to.

**Skill-loading bug (fixed locally).** The first run loaded 8 of the plugin's 9 skills; the main
`understand` skill was missing. It is the only skill whose `argument-hint` frontmatter is a YAML list
(`["…"]`); the rest use a string. Rewriting it as a string made all 9 load. The harness must apply this
patch to its pinned copy, and it should be reported upstream.

**Cost and time** (default model, claude-sonnet-5.5):

| Command | Time | Model calls / premium requests | Input tokens (cache read) | Output | Subagents |
|---|---|---|---|---|---|
| `/understand` | 238 s | 51 | 2.25 M (1.97 M) | 39 K | file-analyzer ×4, architecture-analyzer, assemble-reviewer, tour-builder |
| `/understand-domain` | 49 s | 10 | 0.32 M (0.29 M) | 7 K | — (reused the graph) |

Rough extrapolation, assuming cost grows linearly with file count: the whole app (~1,400 files) would be
about 45× the slice, i.e. on the order of 2,000+ premium requests and a few hours. One-time, because the
source is frozen (ADR-0009), but it should be budgeted.

**What the graph contains** (111 nodes, 165 edges, 5 layers):

- **Domain graph: strong.** 3 domains (Currency Administration, Web Interaction Framework, Error
  Handling & Localization), 7 flows with UI entry points — *List and Page Currencies*, *Add Currency*,
  *Edit Currency*, *Delete Currency*, *Confirm Unsaved Changes*, *Navigate Table Pages*,
  *Report Localized Error* — and 29 steps. These map directly onto ledger capabilities and slice tickets.
- **Typed nodes: weak for Java EE.** 0 `screen`, `endpoint`, `table` or `service` nodes. The meaning is
  there, but as **tags and summaries**: `currency.jspx` is a `file` tagged `view, jsf, ui`; `Currency` is a
  `class` tagged `jpa-entity, data-model`; `CompanyService` is a `class` tagged `service`.
- **Edges: mostly structural.** `imports` 47, `contains` 40, but only 2 `calls`, and 0 `reads_from` /
  `writes_to` / `routes` / `tested_by`. A screen-to-table path cannot be traced from typed edges alone.

**Implications.**
- ADR-0009 holds: one tool, used directly. Its domain flows are the best available slice anchors.
- The Analyst needs an **enrichment step**: derive ledger kinds from tags and config (`jpa-entity` →
  data, `view`/`ui` → UI, `service` → service boundary, JSF managed-bean config → screen↔bean wiring) and
  build the screen → bean → service → entity chain from imports plus config. `check_graph.py` should
  learn to read tags.
- Pin Understand Anything and apply the frontmatter patch in the harness.

## Spike 2 — Remote worker with a read-only, pinned source

**Setup.** Issue assigned to the Copilot coding agent via the REST API (`copilot-swe-agent[bot]`; the API
did not let us pick the custom agent, so the issue pointed the default agent at the probe agent file).
`copilot-setup-steps.yml` checks the source out into `.source/` at the pinned SHA with a read-only token,
disables its push URL, makes it read-only, and installs `rtk-oss`.

| Check | Result |
|---|---|
| Source at the pinned SHA (`c2df760`) | ✅ PASS |
| Source readable (page and bean config inspected) | ✅ readable — and see the quirk below |
| Filesystem write blocked (`touch .source/PROBE` → Permission denied) | ✅ PASS |
| Push blocked (push URL disabled) | ✅ PASS |
| `.source/` never committed (ignored, absent from history) | ✅ PASS |
| **RTK hook in the coding agent** | ✅ **transparent rewrite**: plain `git status` / `git log -n 5` ran as `rtk git status` / `rtk git log -n 5` with compact output |

**Findings.**
- **Setup secrets must be in the `copilot` environment.** The first session started before the token
  existed; the checkout step failed and the session continued without the source (setup failures do not
  stop the agent). The harness should make the agent verify its setup before working.
- **Hooks come from the agent's branch, not `main`.** A session continuing an older PR branch did not see a
  hook added to `main` later. New tickets branch from `main`, so this only affects long-lived PRs.
- **RTK's hook file works as written** in the coding agent (PascalCase `PreToolUse`, `command` field) — the
  format mismatch with GitHub's documented `preToolUse`/`bash` schema is not a problem in practice. Note that
  `rtk init`'s instruction block was *not* installed, so the rewrite came from the hook alone.
- **Agent environment:** no `gh` login, the git remote is a local proxy (the platform creates the PR and
  comments for the agent), no `rg`. Context use for the probe: ~15–25% (agent's own estimate).
- **A real quirk, found unprompted.** `admin/currency.jspx` resets four beans when the tab is clicked; one,
  `searchCurrencyTableModel`, is declared nowhere in the codebase (likely a leftover from a removed search
  feature). Under ADR-0007 a migrator may not silently drop it — it is exactly the kind of item that becomes
  a quirk ticket for a human.

## Spike 5 — Tier-B characterization from source alone (ADR-0005)

**Question.** With no running legacy environment and a build that cannot run outside the organization, can
the source still be compiled and executed in isolation to capture real behavior?

**How.** A scratch harness in the pilot repo (`spike/tier-b/`) that never modifies the source:
- **Compile only what tests reach:** `javac -sourcepath <read-only source trees> -implicit:class` with the
  test classes as roots, so the many classes that import proprietary APIs are never compiled.
- **Public artifacts only** (Maven Central): JSF (Mojarra), JPA, EJB, Servlet and EL APIs, EclipseLink,
  Apache Trinidad (the open-source base of ADF Faces), Commons Lang 2.6, plus JUnit 5 and Mockito.
- **Stand-ins for proprietary classes:** 3 compile-only Oracle ADF Faces classes (`QueryEvent`,
  `DialogEvent`, `RichPopup`). No WebLogic, no internal repository manager.
- **Seam:** the table models read the user's locale from the JSF session in their constructor; a mock
  `FacesContext` with a plain map as session replaces the container. The source's own resource bundles
  are used read-only.

**Result (run 8).** **312 legacy classes compiled; 13 characterization tests, all passing**, covering the
paging behavior every admin table inherits (`BasePagedTableModel`) and entity identity (`BaseDomainEntity`
via `Currency`). Each test logs what the code did next to what reading the code predicted:
**57 of 57 predictions matched**, plus 2 observe-only cases.

**Lessons for the Characterizer (would apply to any tier-B setup):**
- **Encoding.** The source is Windows-1252 and the build declares no encoding; compiling as UTF-8 fails.
- **Missing public libraries surface as cascades.** One absent jar (Commons Lang) produced ~90 errors.
- **Legacy generics can block naive harnesses.** A table model typed by `String` does not compile because
  the legacy `selectRow(M)` and `selectRow(String)` overloads collide; use a dedicated row type.
- **Tooling details:** the JUnit console launcher does not expand `lib/*` classpath wildcards (tests are
  silently not found).

**Quirk candidates found (for ADR-0007 tickets):**
- An empty table shows **"Page 1 of 0"**.
- If the row count query throws, the exception is handled and the pager shows **"Page 1 of 0"**, the same as
  an empty table, so a database failure can look like "no data".

**Implications.** Tier B is practical for this app's logic layers (entities, paging, services with fakes),
so tier C (spec-derived) can be reserved for code that truly cannot run. In this simple code reading
predicted behavior perfectly; the value of tier B grows with the CRAP hot spots, where reading is least
reliable — the next characterization target should be one of them (e.g. `BaseEmployee.getPropertyValue`).

## Spike 3 — CRAP risk map and mutation testing

**Source risk map (no build needed).** lizard scanned the Java source in **6 s**: 10,845 methods, **699
(6.4%) above CRAP 30** with no coverage (CRAP = complexity ranking, as ADR-0013 expects).
- **Vendored code must be excluded.** Before excluding minified jQuery, it took the top 3 spots. The
  profile needs exclusion globs (vendored, minified, generated code).
- **Hot spots:** `BaseEmployee.get/setPropertyValue` (CCN 127 each), `RateTableBean.viewTypeChangeListener`
  (111), `RoleImportService.refreshSupervisors` (104), `QueryService.addStatusFilter` (99), and a cluster
  of import services (`EmployeeImportService`, `BonusImportService`, `GlobalRate*ImportService`). The
  import/batch area is the riskiest part of the app.
- **Currency slice:** 315 methods, only 5 above 30, the hottest being the shared
  `ExceptionHandler.handleException` (CCN 14). A low-risk slice: a good first pilot.

**Legacy build: cannot run outside the organization.** `stncommons` fails on
`com.oracle.wlserver:wlfullclient:12.2.1` (proprietary WebLogic client, not in Maven Central);
`toolkit-ejb` fails on an unreadable POM (internal parent/Nexus). So there is no source coverage.
- ADR-0013 is confirmed: the risk map must not depend on a build.
- New for ADR-0005: **characterization cannot assume the legacy app builds or runs.** Sometimes only
  the source exists, so characterization is chosen by tier (running environment / runnable in
  isolation / source-only specs). Note the missing WebLogic client is `provided` scope — needed to
  compile, not shipped — which suggests tier B (compile against public API artifacts) is feasible.

**Target gate on a Python stub** (mutmut 3.8.1, coverage 7.17):

| Measure | Result | Gate |
|---|---|---|
| Line coverage (`service.py`) | 94% | — |
| CRAP (max method) | 9 | ≤ 30 ✅ |
| Mutation score | 64 / 102 killed = **62.7%** | ≥ 80% ❌ |
| Mutation run time | 6 s | — |

High coverage with weak tests: exactly the case the mutation gate exists for (ADR-0011). Note: mutmut 3
renamed its config keys (`paths_to_mutate` → `source_paths`).

## Spike 4 — RTK output filtering

**Install.** RTK **1.1.0** from the GitHub release asset. Each release ships `rtk` (default, links the
BUSL engine), **`rtk-oss` (Apache-2.0 edition: same binary name, built without the engine)** and
`rtk-proxy`.

| Command | Raw bytes | RTK bytes | Saved | Notes |
|---|---:|---:|---:|---|
| `pytest` (passing) | 461 | 48 | 90% | one-line summary |
| `pytest` (1 failure) | 1,714 | 440 | 74% | test name, file:line and assertion kept |
| `git status` | 449 | 88 | 80% | |
| `git log -n 30` | 4,691 | 2,328 | 50% | |
| `mvn test` (dependency failure) | 3,442 | 1,676 | 51% | reactor summary + cause + resume hint kept |
| `mvn package` (dependency failure) | 3,520 | 1,790 | 49% | |
| `mvn compile` (POM error) | 1,543 | 1,543 | 0% | passed through unfiltered |

- **Recovery works.** Each trimmed result ended with `[full output: rtk recall <hash>]`, and recall returned
  the full output.
- **Not yet measured:** filtering of real Surefire test output, since the legacy build cannot run (RTK's own
  fixtures claim ≥90% there).
- **`rtk init --copilot` writes exactly two things:** `.github/hooks/rtk-rewrite.json` (one `PreToolUse`
  entry running `rtk hook copilot`) and a marked block in `.github/copilot-instructions.md`. This matches
  ADR-0015 §4a.
- **Coding agent: confirmed** (spike 2) — the hook rewrites commands transparently there too.

**Implication.** Pin `rtk-oss` for the public harness unless a measured feature gap appears. That avoids the
BUSL question entirely.

---

## Decision updates (applied)

| ADR | Change |
|---|---|
| 0009 | Add the Analyst enrichment step (tags + config → ledger kinds and screen/data chains); pin Understand Anything with the frontmatter patch; record the cost and time per file as a budgeting input. |
| 0005 | Revised: characterization by **tier** (tier B proven on the pilot in spike 5) — A running environment, B runnable in isolation (public API artifacts / stand-ins), C source-only specs (`spec-derived`); tier recorded by bootstrap. ADR-0006 gains the no-environment fallback. |
| 0013 | Exclusion globs for vendored, minified and generated code in the profile. |
| 0015 | Pin RTK's Apache-2.0 edition (`rtk-oss`); the hook is confirmed to rewrite transparently in the Copilot coding agent. |
| 0012 | The capability checklist records the characterization tier and what blocks the build. |
| 0008 | Setup secrets live in the `copilot` environment; agents verify their setup before working. Spike 1 showed `GITHUB_TOKEN` + `copilot-requests: write` works for SDK-driven agents in Actions: a second remote-dispatch path besides assigning issues to the coding agent. |
