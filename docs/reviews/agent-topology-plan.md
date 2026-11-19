# Plan: act on the agent-topology review

This plan addresses all nine findings in [agent-topology-review.md](agent-topology-review.md), in the review's
order. Measure first, change one thing at a time, and keep what holds up.

## Ground rules for every phase

- **One topology change per PR, then re-run the eval.** A phase that folds a role is not done until the eval
  shows no worse result. That means no flipped must-pass case and no lower total, with each case run at
  least twice.
- **Decisions become ADRs.** Each phase names the ADRs it adds or amends, using the next free numbers when it
  lands. ADR-0041 is next today.
- **History is never rewritten.** Return files of retired roles (`afs-specialist-migrator`,
  `afs-slice-coordinator`, `afs-bootstrapper`) stay valid forever. Tools read them as legacy roles; new
  plans and dispatches may not use them. `harness_coverage.py` treats legacy roles as satisfied by history
  and doesn't list them as open paths.
- **Every phase ends with a rollout** of the harness to the pilot and the synthetic target (`bootstrap.py`
  from the harness checkout), then a `harness_coverage.py --union` run. Coverage must not drop.
- **Constraints stay as they are.**
  - The operator merges every PR and approves every Copilot workflow run. The dispatcher never approves
    runs.
  - Character limits per agent file stay (`tests/test_agents.py`), and the unit suite stays green.
- **Don't change a topology mid-slice.** The synthetic monthly-report slice (LL-05) and the open
  side-by-side checks (circulation #109, fees #118, About #128, catalog) finish under the current
  topology before phase 3 retires the coordinator.

## Phase 1: build the eval (finding 1), and start recording skill loads (finding 9)

**Goal:** a repeatable, end-to-end measure of agent output quality, per case, with a recorded baseline for
the current topology.

### 1.1 Eval cases (`evals/cases/*.yaml` in the harness)

Each case pins a repository, a base commit, the ticket text as it was dispatched, the role to dispatch, and
the expected outcome. Every expected outcome comes from what really happened, never from invention:

| Kind | Cases | Source of truth |
|---|---|---|
| Migrator, plain | synthetic LL-01, LL-02, LL-03, LL-04, LL-05 | Accepted PRs, slice scenarios (`synthetic/scenarios.yaml`), acceptance runs |
| Migrator, data | 2 pilot `DM-05*` tickets | Accepted PRs, `data_reconcile.py` reports |
| Migrator, UI | 1 pilot UI ticket (from the specialist set) | Accepted PR, e2e evidence |
| Verifier, real defect | pilot BK-05A, HR-04E, TC-14, AM-04C; synthetic LL-02 (architecture) | The Migrator's head commit at the time of the `changes-required` verdict; the committed finding is the expected catch |
| Verifier, clean | 2 tickets whose first verdict was `pass` | No blocker or major finding expected |
| Bootstrap | synthetic setup commit | The merged profile and capability checklist |
| Slice acceptance | synthetic loan-catalog (epic #58) | The committed acceptance report and reconciliation file |

That makes about 17 cases. The guidance's minimum is ten. The Verifier cases are what make phase 4
measurable.

### 1.2 Rubric

The grading is automated wherever possible. Every case is graded on the first group, then on its own kind.

**Every case:**
- Every check on the case's PR passes, scope included (`afs-finish-check`).
- The return file is valid.

**Migrator cases:**
- The case's scenarios and the held-out characterization cases pass on the produced head.
- The mutation score on changed code is at least the threshold.
- The ledger entries validate and point at real components.
- The full suite passes in its default order.

**Verifier cases:**
- The verdict matches the expected one.
- For a defect case, a finding names the expected defect: same file or capability, and a severity of major
  or higher.
- For a clean case, there are no blocker or major findings.

**Bootstrap and acceptance cases:**
- A field-level comparison with the golden files: tier, capabilities, profile gates, and the dispositions in
  the reconciliation file.

**Judgment calls:** gate-3 idiom quality is a 1–5 rubric score from a fixed grader prompt, reported
separately and never mixed into the pass/fail total.

### 1.3 Runner: `tools/afs-eval`

- `afs-eval run --cases evals/cases --runs 2 --config <topology>`:
  - creates a branch per case and run in a dedicated eval repository, at the case's base commit;
  - opens the case issue and dispatches it through the assignees API, as live runs are dispatched;
  - waits for the PR, then grades it.
- `afs-eval report` writes `evals/results/<date>-<config>.md`, with:
  - one row per case per run;
  - the total;
  - **the cases that flipped** against the last baseline;
  - the skills each session loaded (see 1.4).
- Results are committed, so the comparison in each later phase cites a file.

### 1.4 Record skill loads (finding 9 starts here)

The cost hook (`afs-cost-hook`) or the session log records each skill a session loads. `afs-run` appends
those loads to the run journal as `skill` rows. Phase 5 needs this data, so it must be collected from the
baseline onwards.

### Operator decisions before phase 1 runs

- **The eval repository.** One new repository, `martins-vds/ai-factory-eval`, holding copies of the pilot
  and synthetic targets as separate branches.
- **Workflow approval in that repository.** Under ADR-0039 each Copilot push waits for your approval, which
  would be about 34 approvals for a baseline (17 cases × 2 runs). Either keep approval on, or turn it off for
  the eval repository only, recording that as an amendment to ADR-0039.
- **Budget.** A baseline is about 34 sessions, and each later comparison runs only the affected cases, at
  about 10–20 sessions each.

**Deliverables:** `evals/`, `tools/afs-eval` (with tests, listed in the README), the skill-load journal
rows, and an ADR for the end-to-end eval as the bar for agent changes. The baseline report for the current
topology is committed.

**Done when:** the baseline is committed, with every case run twice, and the report shows the per-case
variance between the two runs.

## Phase 1b: fix the gaps the eval found, then retake the baseline

*Added 2026-11-15 by the operator's decision after the first baseline (`evals/results/2026-11-15-base-r{1,2}`).*

The first baseline passed 6 of 16 cases, then 4 of 16, and two must-pass cases flipped between the runs.
Most failures weren't agent quality. The agents stopped correctly at harness gaps. A topology change measured
on that baseline would show nothing, so these fixes come before phase 2. They are listed in the order the
eval found them.

1. **The isolation fixture had no owner.** In LL-01 to LL-04 and the trial, a live-server test flushed the
   seed rows. The migrator rule says to fix that with a project-wide fixture in `tests/conftest.py`, but no
   ticket lists that file, so agents stopped and asked. Fix:
   - `target.shared_test_files` in the profile lists that setup, and any ticket may change those files
     (`afs-finish-check`);
   - the Bootstrapper scaffolds the fixture with the test runner;
   - the targets' profiles gain the key in their next rollout.
2. **`afs-mutation` crashed when tests read migration data (DM-05D).** Shard workspaces left out all of
   `.migration/`, so tests reading characterization data failed before any mutant ran. Fix: shard workspaces
   keep `.migration/`'s data and leave only its machinery behind.
3. **Planner checks moved up from phase 3b.** Phase 3b's checks move here: slice-spec anchors, template folders
   versus `target_paths`, tests broken by a removal, and plan-file drift. BK-05G's missing dashboard template
   is the same kind of gap. Phase 3b keeps only what depends on the coordinator fold. Eval cases pin their plans, so these checks don't change eval results: they run alongside the retaken baseline rather than before it.
4. **The mutation threshold stays 0.8.** All 36 live scores met it, and 5 landed between 0.80 and 0.85. The two
   eval misses (0.794, 0.790) are the same near-miss: live sessions closed that gap by strengthening tests,
   sometimes in a continuation session. No change.
5. **The eval itself was fixed along the way:**
   - `AFS_BASE` and `origin/main` point at each case's base (eval repo setup steps);
   - the grader handles sessions that end without retitling their PR, invalid YAML, reruns of Gates, and CI
     that hasn't finished.

**The bar for the new baseline:**
- two runs, dispatched one after the other so the Actions queue doesn't saturate;
- every must-pass case gives the same result in both runs;
- more than half the cases pass.

If that bar isn't met, the remaining failures get the same treatment (fix the harness gap, or record why the
case is ill-posed) before phase 2 starts.

## Phase 2: fold the Specialist Migrator and the Bootstrapper (findings 2 and 4)

These are two independent PRs, each followed by its own eval run.

### 2a: Specialist Migrator → `afs-migrator` + `afs-specialty` skill

1. **ADR** (consolidates the migrator roles). Amends ADR-0010 and ADR-0014: the data and UI procedures now
   live in a skill.
2. **New skill `skills/afs-specialty/`.** It moves the data, UI and messaging paragraphs out of the
   specialist agent. It also loads `profile.skills.specialists.<specialty>` from the ticket's `specialty`.
3. **Update `afs-migrator.agent.md`.**
   - Add `afs-specialty` and the specialist skills: `ui-ux-pro-max`, `prototype`, `db-seed` and
     `afs-data-pipeline`. Each loads only for its specialty.
   - Update `skills.lock.json` to match.
   - Add optional `specialty` and `specialty_evidence` to the return block, and regenerate the schema
     (`gen_return_schema.py`).
4. **Retire the role.**
   - Delete `afs-specialist-migrator.agent.md`.
   - Keep `afs-specialist-migrator` as a legacy role in `check_plan.py`, `check_verified_merge.py`,
     `ticket_guard.py` and `afs-finish-check`.
   - `schemas/plan-tickets.schema.json` and `check_plan.py` reject the legacy role in new plans, with the
     message "use afs-migrator with specialty: <x>".
   - Move `tools/drills.json` DRILL-01 and DRILL-02 to `afs-migrator` with `specialty`.
5. **Docs.** Update `agents/README.md`, `docs/architecture.md` §4 and the README.
6. **Eval.** Run the data and UI cases plus LL-03. No flips are allowed.

### 2b: Bootstrapper → Program Orchestrator + `afs-bootstrap` skill

1. **ADR** (bootstrap is a skill of the orchestrator).
2. **New skill `skills/afs-bootstrap/`.** It holds steps 1–4 and 6–8 of the current agent: detection, tier,
   checklist, profile, test services, scaffold, graph-first, validation. Step 5 (install) stays
   `tools/bootstrap.py`, which the skill tells the dispatcher to run.
3. **Move the tier-C proof.** `validate.py` currently requires `tier_b_attempt` on a bootstrapper *return*.
   It moves into `.migration/capabilities.yaml`, which every migration already has. `validate.py` checks it
   there, with legacy returns still accepted.
4. **Update the orchestrator.** Its Skills section gains `afs-bootstrap`, and the bootstrapper's skills
   (docker, compose, `find-skills`, `skill-creator`, `self-learning`) move into the skill's own
   references. Its intake step runs the skill instead of dispatching a role.
5. **Retire the role.** Delete `afs-bootstrapper.agent.md`. Keep it as a legacy role in `ticket_guard.py`
   (`setup_pr`) and `afs-finish-check`. Update the message in `bootstrap.py` that cites "afs-bootstrapper
   step 4".
6. **Docs and eval.** Update the docs, then run the bootstrap case.

**Done when:** both PRs are merged and rolled out, the eval shows no flips, and coverage hasn't dropped.

## Phase 3: fold the Slice Coordinator; dispatcher tools; planner checks (findings 3, 8 tools, 6 part 1)

Start only after the in-flight synthetic slices are accepted (see Ground rules). This phase has four PRs, in
this order: the tools first, so the fold has them to rely on.

### 3a: Dispatcher safety tools (finding 8)

1. **`tools/afs-merge`.**
   - `afs-merge verifier <verifier-PR>` merges a Verifier PR into its work branch with `git merge --no-ff`,
     after checking that the PR's base is a work branch.
   - `afs-merge work <PR>` merges a work PR into the default branch. It refuses if the PR's base is not the
     default branch, if `check_verified_merge.py` fails, or if any PR below it in the stack is unmerged.
   - It **never** calls `merge-async` on a stacked PR. Bottom-of-stack merges use `merge-async` only after
     every PR stacked on it is verified and merged.
2. **`tools/stack_refresh.py` fixes.**
   - Refresh stacked PRs at any depth, recursively, not only the first level.
   - Skip a child that is already merged, or whose head already contains the base. This fixes the re-merge
     after synthetic #123.
3. **`tools/check_dispatch_paths.py`.** This is the parallel-dispatch path check.
   - **Inputs:** the tickets to dispatch (plan files) and the open PRs.
   - **Failures:** a file owned by two concurrent tickets, or a new module that shares a dotted name with an
     existing one.
   - **Where it runs:** before every parallel dispatch, and as a CI job on agent PRs, against the other open
     PRs.
4. **ADR.** Amends ADR-0038 (stack refresh) and ADR-0040 (merges go through `afs-merge`).
5. **Retire the replaced prose.** Remove it from `agents/README.md` and both orchestrator and coordinator
   files, and cite the tools instead.

### 3b: Planner checks (finding 6, part 1)

**Status (2026-11-19): built (ADR-0048, proposed).**

These are added to `tools/check_plan.py`, each with a fixture from the run that showed the loss:

- **Anchors.** A slice's `data_paths.target` anchor must name a route that one of the slice's tickets builds
  (as in synthetic #77, #89, #99).
- **`target_paths`.** Template and static folders the tickets list must be under `target_paths` (#76).
- **Removals.** A ticket that removes a module must list the tests that import it, or carry a blocking edge
  to the ticket that owns those tests.
- **Plan file vs issue.** The plan file is the source of the ticket's scope. A check compares the
  dispatched issue's file list with the plan file and fails on drift (LL-01 #71, LL-04 #107).

### 3c: Reconciliation as a tool (finding 3)

- **`tools/reconcile_epic.py`.** It writes `.migration/evidence/ticket-reconciliation/<epic>.yaml` from
  the evidence `ticket_guard.py --reconcile-epic` already computes.
  - Every issue it can prove is written as `completed` or `superseded`.
  - An issue it can't prove is written as `retained-open` with a `needs_review:` note, for a human to
    decide.
  - The check and the writer share one implementation, so they can't disagree.
- **ADR-0030 is amended:** the file is generated and then reviewed, not written by hand.

### 3d: Slice Coordinator → Program Orchestrator + `afs-slice-acceptance` skill (finding 3)

1. **ADR** (one dispatcher loop). Amends ADR-0024, ADR-0030, ADR-0031 and ADR-0036. It decides one open
   question, the acceptance return. My recommendation:
   - the orchestrator commits `.migration/returns/<acceptance-ticket>.afs-program-orchestrator.yaml`;
   - it carries an `acceptance` block with `slice`, `report`, `gates`, `mutation_score`, `human_check`,
     `human_check_issues`, `human_check_issue` and `human_check_due`;
   - `check_signoff.py` and `check_slice_returns.py` read that block, and still accept legacy
     `afs-slice-coordinator` returns.
2. **New skill `skills/afs-slice-acceptance/`.** It holds the coordinator's step 5:
   - start the acceptance run;
   - dispatch the Auditor;
   - write the acceptance report;
   - run `reconcile_epic.py`;
   - request the human check;
   - the sign-off rules from ADR-0031 and ADR-0036, word for word.
3. **The orchestrator's loop gains the coordinator's frontier and dispatch steps (1–4):** claim, dispatch,
   the Verifier on each return, and "restart, don't stretch". It uses the 3a tools.
4. **Retire the role.**
   - Delete `afs-slice-coordinator.agent.md`, and update `tools/drills.json` (AFS-DRILL, DRILL-DEFER).
   - Remove `afs-slice-coordinator` from `SHARED_ID_ROLES` in `check_plan.py`, keeping it as a legacy role.
5. **Docs and eval.** Update the docs, then run the slice-acceptance case and one migrator case end to end
   through the new loop.

**Done when:** all four PRs are merged and rolled out, the next real slice acceptance on the synthetic target
runs through the orchestrator with a generated reconciliation file, the eval shows no flips, and coverage
hasn't dropped.

## Phase 3e: make the Verifier reliable before it's measured (finding 5)

**Status: done (2026-11-18).** The Verifier went from 1 of 6 cases (b3c) to 7 of 7 (v3j) by majority. ADR-0043 records
what it took: the layering and UI checks in the idiom gate, verdicts that follow evidence-backed findings,
inherited defects reported apart, and business rules recorded in the ledger and covered by the Verifier. See
`evals/results/2026-11-17-v3*-summary.md`.

*Added 2026-11-16 by the operator's decision after baseline b3c (`evals/results/2026-11-16-b3c-summary.md`).*

Phase 4a compares the Verifier against a Migrator-only topology. In baseline b3c the Verifier passed only one of
its six cases by majority, so that comparison would measure a weak Verifier, not the role. These steps come
first. Each one is measured on the Verifier cases, three runs each, by majority.

**What the baseline shows** (each Verifier return in b3c):

| Problem | Cases | Example |
|---|---|---|
| Misses import-level layering defects | LL-02 (r2, r3), BK-05F (all), BK-05E (r1, r2) | Use cases import Django's clock and ORM; a use case raises `Http404`; views call the repository |
| Grader missed a correct finding | BK-05E r3 | It found "views call CargoRepository directly; ADR-0001 requires an application service", but the keywords didn't match |
| Serious findings on clean cases, possibly real | LL-03 r1/r3, BK-05G r2/r3 | htmx 2.x doesn't swap 4xx/5xx responses; the URLconf omits booking routes; an interrupted mutation run |
| Verdict contradicts the findings | LL-04 r1 | `changes-required` with no major or blocker finding |

1. **Fix the grader first.**
   - Defect keywords name the defect and its ADR, not a gate's name. For example, BK-05E adds
     `application service`, `repository directly` and `ADR-0001`.
   - Regrade b3c with the new keywords. Grader fixes come before agent fixes, so agents aren't blamed for the
     grader's mistakes.
2. **Make layering a deterministic gate.** All three real misses are import-level violations, which a tool can
   find every time:
   - **The rule lives in the profile.** `gates.layering` holds the layer contracts the architecture ADRs
     state. For example: `application` may not import `django.http`, `django.utils.timezone` or
     `*.models`; views may not import repositories.
   - **A tool checks it.** `check_layers.py` (or import-linter, if the stack pack ships it) runs in the idiom
     gate, for every Migrator ticket and in CI.
   - **The Migrator can't create these defects in the first place.** The Verifier's gate-3 review then
     covers what a tool can't see.
3. **The verdict follows the findings, mechanically.** The finish check and `validate.py` reject a Verifier
   return whose verdict disagrees with its findings:
   - `pass` means no major or blocker finding;
   - `changes-required` means at least one major or blocker finding about the work;
   - `blocked` only when the Verifier couldn't verify (a gate didn't run). Its `blocked_reason` names the gate
     that didn't run.
4. **A serious finding carries evidence.** A major or blocker finding must cite:
   - a failing test the Verifier added (`tests_added`); or
   - a journal log (`.migration/runs/…`) showing the failure.

   Opinions without evidence are `minor`. This targets the clean-case findings: the htmx and URLconf claims
   either come with a failing test, or they're not serious.
5. **The operator reviews the clean cases' findings.** LL-03's htmx 4xx handling and BK-05G's missing booking
   routes may be real defects the live Verifier missed, like BK-05F's. Each confirmed one turns its case into
   a defect case (as with BK-05F, #173). Each rejected one stays clean and counts as a false positive.
6. **An interrupted run is `blocked`, not a defect.** A mutation run or browser suite that didn't finish
   (BK-05G r3) blocks with the gate named in `blocked_reason`. The eval reports such cases separately from
   wrong verdicts, as timeouts are.

**Done when:**
- every Verifier case passes by majority of three, or carries an operator ruling that explains why not;
- no clean case fails on a finding without evidence.

Then phase 4a runs against this Verifier.

## Phase 4: measured experiments (findings 5 and 6, part 2; finding 7 recorded)

These are experiments, not planned folds. Each runs on the eval, twice per case, and its result is recorded
in an ADR whether the fold is kept or rejected.

### 4a: The Verifier (finding 5)

- **Configurations:**
  - **A (current):** Migrator, then Verifier.
  - **B (folded):** Migrator alone, with an extra self-verification step in `afs-implement`: re-run every
    gate, review against gate 3, strengthen tests. CI still runs.
- **Cases:** the Verifier cases (real defects and clean ones) plus the plain migrator cases.
- **Metrics:**
  - defects that reached the merge candidate;
  - false `changes-required` verdicts;
  - sessions, wall-clock time and operator approvals per ticket.
- **Decision rule:** keep A unless B catches every real-defect case A catches, on both runs. The review's
  evidence predicts A.
- **ADR:** "The Verifier stays an independent session", with the numbers, or the fold.
- **Status (2026-11-18): inconclusive; the Verifier stays (ADR-0044).** Neither configuration let a defect reach a merge candidate. B cost 23% fewer minutes. Re-run once the cases start clean (`evals/results/2026-11-18-4a-summary.md`).
- **Status (2026-11-18, round 2): the rule is met; the Verifier folds (ADR-0045, accepted).** On clean-start cases, A's
  Verifier caught two major LL-02 defects (one per round); B had none on any merge candidate, confirmed by an
  independent audit, at about 32% fewer minutes (`evals/results/2026-11-18-4a-round2-summary.md`).
- **How it runs** (operator decisions, 2026-11-17: hidden oracle checks; two runs per case):
  - **Cases:** seven Migrator tickets: BK-05F, BK-05G, DM-05F, LL-02, LL-03, LL-04 and LL-05. They get today's
    layering, UI checks and self-healing, as live targets have them.
  - **A:** `afs-migrator` runs; then `afs-eval chain` starts an `afs-verifier` session on each finished
    Migrator PR, based on the PR's branch as on a live target.
  - **B:** the same tickets dispatched to `afs-migrator-selfverify` (`evals/variants/`). It is the Migrator
    with one more step: verify your own work as an independent reviewer would.
  - **Ground truth:** `afs-eval oracle` runs checks on each Migrator head that the agents never see:
    - the layering and UI tools with the case's profile;
    - the case's `oracle.forbid_calls`. BK-05F's forbids `is_satisfied_by` in any `interfaces/` module: the
      route-specification rule in the view, which BK-05F's base already contains.
  - **Defects that reach the merge candidate:**
    - in B, an oracle finding on a Migrator head with green Gates;
    - in A, the same, and the chained Verifier returned `pass`.
  - **A false `changes-required`** is A's Verifier asking for changes on a head the oracle finds clean, with
    green Gates.

### 4b: Analyst + Characterizer (finding 6, part 2)

- **Configurations:** separate sessions (current) against one "understand" session that runs both
  procedures as skills.
- **Case:** one new-scope case on the synthetic target. `synthetic/legacy-reports` or `legacy-billing` has
  no slices yet, so a fresh analysis has a known ledger to compare against once accepted.
- **Metrics:** ledger completeness against the golden ledger; characterization cases and prediction matches;
  session failures caused by context or lifetime.
- **Decision rule:** fold only if it is no worse on both runs and the session finished within its lifetime.
- **ADR:** the decision either way.

### 4c: The Auditor (finding 7)

The Auditor isn't folded. One ADR line records the decision to keep it, with the LC-AUDIT evidence, and
phase 5 trims its prompt.

**Done when:** both experiments are recorded and the chosen topology is rolled out.

## Phase 5: prompt audit and skills pruning (findings 8 audit, 9, 7 trim)

1. **Skill usage report.** `afs-eval report --skills` and a journal scan of the live targets report, per
   role:
   - the skills each session loaded, and how often;
   - skills assigned but never loaded.
2. **Skills audit** with `skill-creator`, driven by that report.
   - Merge overlapping skills: `refactoring`, `refactoring-guru` and `clean-code` into one target-redesign
     skill, and fold `verification-before-completion` into `afs-evidence`.
   - Drop skills that are never loaded, or move them to `profile.skills` as optional.
   - Update `skills.lock.json`, with a target of 12 or fewer listed skills per role.
3. **Lock test.** `tests/test_agents.py` gains a check: a role may not list more than the target number of
   skills without a recorded exception.
4. **Prompt audit** of every remaining agent file and `agents/README.md`.
   - Remove rules a tool now enforces, citing the tool instead.
   - Remove repeated warnings and phrasing aimed at older models.
   - Collapse incident paragraphs into the principle each one encodes.
   - Trim the Auditor's prompt.
   - Character budget: none above 6,000, against today's maximum of 8,614.
5. **Final eval** of the whole topology, compared with the phase-1 baseline. The report lists every flipped
   case, and no must-pass case may flip.
6. **ADR** for the skills and prompt hygiene rule: an audit after each milestone, and the eval required for
   any change to an agent or skill.

**Done when:** the final eval is no worse than the baseline on any must-pass case, the per-role skill and
character budgets hold, and the topology is rolled out.

## Expected end state

| Role (today) | After the plan |
|---|---|
| Program Orchestrator | The single dispatcher loop. Skills: `afs-bootstrap`, `afs-slice-acceptance`, plus its own. Tools: `afs-merge`, `check_dispatch_paths.py`, `reconcile_epic.py`, `stack_refresh.py` |
| Bootstrapper | Retired → `afs-bootstrap` skill + `bootstrap.py` |
| Analyst, Characterizer | Kept, or folded into one understanding session, per experiment 4b |
| Planner | Kept; new `check_plan.py` checks |
| Slice Coordinator | Retired → orchestrator loop + `afs-slice-acceptance` skill + `reconcile_epic.py` |
| Migrator | Kept; absorbs the specialist through `afs-specialty` |
| Specialist Migrator | Retired → `afs-specialty` skill |
| Verifier | Kept, unless experiment 4a says otherwise; cheaper to run thanks to `afs-merge` and the refresh fixes |
| Auditor | Kept; trimmed |

That takes us from ten roles to six or seven, every hard rule found in this run enforced by a tool, and every
future change to an agent measured against the eval.

## Findings → phases

| Finding | Phase |
|---|---|
| 1 No eval | 1, 1b (gaps the eval found) |
| 2 Specialist Migrator | 2a |
| 3 Slice Coordinator | 3c, 3d |
| 4 Bootstrapper | 2b |
| 5 Verifier | 3a (cost), 3e (reliability), 4a (experiment) |
| 6 Analyst → Characterizer → Planner | 3b (checks), 4b (experiment) |
| 7 Auditor | 4c (decision), 5 (trim) |
| 8 Prose rules, Frankenprompt | 3a (tools), 5 (audit) |
| 9 Skills sprawl | 1.4 (data), 5 (audit) |

## Risks

- **The eval cost and the approval load are real.** Phase 1's operator decisions control both. Without the
  eval, phases 2–5 would repeat the pattern the review warns against: changes driven by incidents, with no
  baseline.
- **Golden outcomes from one historical run may encode accidents.** The rubric checks behavior (scenarios,
  characterization, gates, findings), not the exact diff, so an equally valid implementation passes.
- **Retiring roles touches many tools.** The legacy-role rule (accept in history, reject in new plans) is
  tested in each tool's test file before the role is deleted.
- **Copilot model changes during the plan** will shift eval results. Each report records the model and date,
  and a phase compares only against a baseline taken with the same model.
