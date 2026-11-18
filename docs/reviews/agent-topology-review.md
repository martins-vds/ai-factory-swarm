# Review: agent topology against "when to fold subagents into the main loop"

Requested by martins-vds on 2026-11-14. This review checks the ten role agents against Anthropic's guidance in
[Building agents: When to fold subagents into your main agent loop](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop)
(2026-10-22). It uses evidence from the pilot (`ai-factory-pilot-target`) and synthetic
(`ai-factory-synthetic-target`) runs. The implementation plan is in
[agent-topology-plan.md](agent-topology-plan.md).

## The guidance in brief

- **Default to one loop.** One model and one context window, with skills and tools loaded on demand. In
  Anthropic's comparisons, this beat both a single-prompt design and a subagent design on quality, usually
  at lower cost and latency.
- **Keep a subagent only when one of these holds:**
  - context bloat measurably hurts a single loop;
  - tasks run in parallel, each in a fresh context that is thrown away afterwards;
  - one agent can't pick its tools well, or its instructions conflict.
- **Avoid Conway's law:** one agent per team or problem type.
- **Merge coupled specialists.** Merge specialists that chain on each other's output, touch the same data,
  or are usually called together. One that is almost always followed by a second is a merge candidate.
- **Put each kind of logic where it belongs:**
  - procedure and ordering go into skills;
  - hard limits (validation, approval gates) go into tools, which check preconditions and return an
    actionable instruction.
- **Measure first.** Start with a small end-to-end eval (about ten golden examples).
  - Fold one subagent at a time.
  - Run each task more than once.
  - Compare which tasks flipped, not just the total.
  - Keep a subagent only if the folded version scores worse.
- **Watch for these failure modes:**
  - lossy handoffs ("telephone game");
  - subagent sprawl;
  - the "Frankenprompt", where each incident adds a sentence until the rules conflict;
  - evals that only measure local subtasks;
  - nested-loop latency.

## Mapping to the AFS harness

There are no in-process subagents in AFS. A "subagent" here is a separate GitHub Copilot coding-agent
session that runs a role agent. The dispatcher (L0, local, with a user token) and the operator form the main
loop. That changes what "folding" means:

- **The split per ticket stays.** Tickets run in parallel, each in a fresh session that is discarded afterwards,
  and sessions have a bounded lifetime. That is the guidance's second reason to keep subagents.
- **The split by role is what this review questions.** Folding a role means one session per ticket, with
  the role's procedure moved into a skill and its hard rules into tools.
- **The dispatcher already calls sessions as tools with a typed result.** Each session commits a return file
  validated by `schemas/return.schema.json`. That is step 3 of the guidance ("subagents as tools").

What already matches the guidance:

- **Hard limits live in CI tools, not prose.** These include `validate.py`, `check_return_contract.py`,
  `check_verified_merge.py`, `ticket_guard.py`, `graph_gate.py` and `check_signoff.py`. Most of them
  check a precondition and print the action to take.
- **Skills load on demand** (ADR-0015).
- **Human gates are enforced by tools.** These are sign-off as an approving review (ADR-0031) and
  verify-before-merge (ADR-0040).

## Evidence base

The figures come from committed return files on `main` and their git history, as of 2026-11-14.

**Return files on `main`, by role:**

| Role | Pilot | Synthetic |
|---|---:|---:|
| afs-migrator | 25 | 4 |
| afs-specialist-migrator | 17 | 0 |
| afs-verifier | 20 | 4 |
| afs-auditor | 4 | 4 |
| afs-slice-coordinator | 4 | 1 |
| afs-bootstrapper | 8 | 5 |
| afs-analyst, afs-characterizer, afs-planner, afs-program-orchestrator | 4 each | 1 each (none for the orchestrator) |

**Verifier verdicts across every committed version (not just the final one):**

- **How often it stopped a ticket:** 13 of 24 verified tickets had at least one `changes-required` or
  `blocked` verdict before passing.
- **Behavior defects, all fixed before merge:**
  - AM-04C: HTTP 500 on polling;
  - BK-05A: missing booking change logs;
  - BK-05B: port candidate sampling differs from the source;
  - HR-04C: valid zero-padded years rejected;
  - HR-04E: completion time stored as a date, so noon events replay at midnight;
  - TC-14: status `AT_DESTINATION` where the golden says `CLAIMED`.
- **Architecture findings (gate 3):**
  - BK-05E: the view bypasses the application layer;
  - LL-02: use cases coupled to the Django clock and the ORM.
- **Regression:** LL-03 and LL-04 were blocked on a full-suite timeout. That timeout was the seed-data flush,
  later fixed project-wide (harness #155).
- **Evidence and ledger:** BK-05I had characterization evidence missing and a capability left `in-progress`.
- **Scope and housekeeping:** HR-04A (a stale link) and HR-04B (an out-of-scope file).
- **Tests added:** about 51 across the final returns.

## Findings

Each finding states the problem, the evidence, the guidance that applies, and the recommendation.
Priority follows the plan's order.

### 1. No end-to-end eval: no topology decision is measurable

**Problem.** The harness measures *which paths ran*: `harness_coverage.py` reports 107 of 108 paths
exercised. It measures tool correctness: 505 unit tests. Nothing measures *output quality per ticket*. We
cannot say whether a role split helps or hurts, or catch a regression that appears in only one of two runs.

**Evidence.**

- Every change to the role agents so far was driven by an incident in a live run. One example is the
  `django_db_serialized_rollback` rule after LL-03 and LL-04.
- No change was compared against a baseline.

**Guidance.** Build evals first: one shared end-to-end set (about ten golden examples), graded against a
rubric, each task run several times. Track whether the right skill or tool was used.

**Recommendation.** Build a golden-ticket eval from the synthetic and pilot runs. Each case is a ticket
whose correct outcome is already known: its accepted PR, characterization, scenarios and acceptance run.
Grade a fresh run against a rubric, run each case at least twice, and report the cases that flipped. This
comes before any change to the topology.

### 2. The Specialist Migrator is the Migrator plus skills

**Problem.** `afs-specialist-migrator` says "Everything in `afs-migrator` applies; this file adds what is
special":

- it has the same procedure (understand → tests first → implement → gates → ledger → PR);
- it has the same gates and the same rules;
- its return file is almost the same: it adds `specialty` and `specialty_evidence`.

Two prompts that must be kept in step is a source of drift. The mutation rule, for example, is written in
both files.

**Evidence.**

- It is used heavily: 17 pilot returns, all data or UI work.
- Its differences are entirely procedural, the data, UI and messaging paragraphs. That is skill material.
- The role name is wired into these tools: `check_plan.py`, `check_verified_merge.py`, `ticket_guard.py`,
  `afs-finish-check`, `schemas/plan-tickets.schema.json` and `tools/drills.json`.

**Guidance.** Merge specialists that chain on the same work or touch the same data. Specialty procedure
belongs in skills.

**Recommendation.** Fold it into `afs-migrator`. The ticket's `specialty` (data, UI or messaging) loads a
new `afs-specialty` skill with the three procedures, plus `profile.skills.specialists.<specialty>`. The return
contract gains optional `specialty` and `specialty_evidence`. Existing `afs-specialist-migrator` returns stay
valid as a legacy role, because history must not be rewritten.

### 3. The Slice Coordinator can't do its core job where it runs

**Problem.**

- The coordinator's procedure is mostly dispatch: claim, assign to Copilot, open quirk issues, dispatch
  Verifiers, re-dispatch handoffs. A remote session can do none of that: it has no user token
  (`agents/README.md` → *Where each role can run*).
- In both targets the dispatcher (L0) did every dispatch. The coordinator session only did the
  acceptance bookkeeping: the ledger, the acceptance report, the reconciliation file and `human_check`.
- Its prompt is the largest, at 8,614 of the 9,000-character limit.
  - Step 6 (ticket reconciliation) is one paragraph of accumulated incident rules: continuation children,
    pre-rule null-PR returns, closed-unmerged heads, carrier PRs.
  - The parallel-dispatch path check is copied word for word from the orchestrator.

**Evidence.**

- The synthetic coordinator returns (#109, #118, #128) contain no dispatch.
- `ticket_guard.py --reconcile-epic` already computes, as the check, the evidence behind every disposition
  the coordinator writes by hand into `<epic>.yaml`.
- Every reconciliation fix in this run went into that tool: continuation children, hand-offs and
  stacked landings (harness #158). The prompt only grew to describe the cases.

**Guidance.** Avoid a role that mirrors an org chart. Procedure goes into skills, mechanical work into tools.
The "Frankenprompt" is a named failure mode.

**Recommendation.**

- Retire the coordinator role:
  - dispatch and frontier tracking move into the Program Orchestrator's loop, where they already run;
  - slice acceptance becomes an `afs-slice-acceptance` skill.
- A new tool, `reconcile_epic.py`, writes the reconciliation file from the evidence that
  `ticket_guard.py` computes. A model never transcribes it. The human reviews it, as now.
- The slice's acceptance return, with `human_check` and sign-off, becomes a return the orchestrator writes.
  The plan settles its name in an ADR. Existing `afs-slice-coordinator` returns stay valid as legacy.

### 4. The Bootstrapper is a wrapper around a tool

**Problem.**

- The Bootstrapper's install step must run where `.github/` is writable. A Copilot session can't change
  `.github/agents/`, so the dispatcher runs it anyway.
- Its other steps are detection, a checklist and a profile. They are procedure, done once per migration
  with the operator present.
- At 8,019 characters it is the second-largest prompt.

**Evidence.**

- In both targets the install and every re-rollout were run by the dispatcher with `tools/bootstrap.py`.
- There are 13 bootstrapper returns across the two targets. Several were drills or re-runs for the setup PR.

**Guidance.** Code handles the mechanical work inside tools, and procedure becomes a skill.

**Recommendation.** Fold the Bootstrapper into the Program Orchestrator. Its procedure becomes an
`afs-bootstrap` skill: detect stacks, decide the tier, write the capability checklist, write the profile, add
test services. `bootstrap.py` stays the tool for the install. Existing returns stay valid as legacy.

### 5. The Verifier is a coupled pair worth keeping, but it is expensive

**Problem.**

- The Verifier always follows a Migrator: 24 of 24 tickets. The guidance would flag that as a merge
  candidate.
- It is also the role with the highest operating cost:
  - a second session per ticket;
  - another wait for the operator to approve its workflow runs (ADR-0039);
  - a stacked PR and a git merge into the work branch;
  - the verify-before-merge machinery (ADR-0040);
  - stack refreshes.
- That machinery caused the run's most serious near-miss: an attempted `merge-async` that would have
  merged an unverified PR to `main`.

**Evidence.**

- It changed the outcome in 13 of 24 tickets (see *Evidence base*). Six of those were behavior defects
  fixed before merge.
- It blocked on the seed-data flush (LL-03, LL-04) before that bug was understood.
- Its independence is the point: it is not given the builder's reasoning.

**Guidance.** Independent verification is an endorsed pattern: an optional goal or verifier check that runs
after the loop. Keep a subagent if the folded version scores worse.

**Recommendation.** **Keep the Verifier.** Spend the effort on its cost, not its existence:

- automate the stacked merge and stack refresh (finding 8);
- tune its prompt and skill set (findings 8 and 9).

Run one eval comparison anyway (Migrator alone vs Migrator + Verifier), to confirm the decision and to have a
baseline for future, more capable models. The evidence predicts the Verifier wins.

> Correction: an earlier draft of this review, given in chat, counted only each return's *final*
> version. It said the Verifier had caught no behavior defects and had missed the seed-data flush. The
> history above shows both claims were wrong.

### 6. Analyst → Characterizer → Planner is a lossy chain

**Problem.**

- These three run in sequence, once per migration (or once per new scope).
- Each reads the previous one's output from the ledger and graphs.
- The losses in this run sat at these boundaries.

**Evidence.**

- A plan scope was edited only in the issue, not in the plan file (LL-01: plan PR #71; LL-04: #107).
- Slice-spec anchors used JAX-RS names that no ticket updated when it built the Django routes (#77,
  #89, #99).
- The synthetic profile's `target_paths` lacked `templates/` (#76).
- The Verifier's prompt had to be patched to resolve quirk rulings from earlier slices. That knowledge never
  reached it through the ticket.

**Guidance.** Merge specialists that chain on each other's output and touch the same data. Handoffs between
agents split by problem type lose details.

**Recommendation.**

- First, move the specific losses into tools (`check_plan.py` checks):
  - anchors that don't resolve to the routes the slice's tickets build;
  - template folders outside `target_paths`;
  - tests broken by a removal.
- Then use the eval to try folding the Analyst and the Characterizer into one understanding session.
  Characterization needs runtime services and may need its own context, so measure before folding.
- Keep the Planner separate for now: its output is the human-approved plan, a natural gate.

### 7. Keep the Auditor

**Problem.** None. It is recorded here so the decision is explicit.

**Evidence.** The Auditor is read-only, runs after the work on the acceptance run's exact commit, and
re-proves every capability. It found the genuine `misplaced` gap (LC-AUDIT) that no ticket-level check
could see.

**Guidance.** A verifier or goal check after the loop is the recommended place for an independent check.

**Recommendation.** Keep it. Trim its prompt in the prompt audit (finding 8). Its graph-freshness and
acceptance-run preconditions are already tools.

### 8. Rules that live in prose should be tools; the prompts need an audit

**Problem.** Several hard rules exist only as prose. These are the ones an agent or the dispatcher can break:

- **Never `merge-async` a PR whose base is another PR's branch.** It lives in `agents/README.md`. I
  nearly broke it on synthetic #91, and GitHub refused only because #88 was a draft.
- **The verifier PR goes into the work branch with `git merge --no-ff`.** This is a manual multi-step
  procedure.
- **The stack refresh** (bring every open work branch up to date with `main`, then merge each into its
  stacked PR) is manual. It has two known defects:
  - second-level stacked PRs are not refreshed;
  - a base is re-merged into a child that was just merged (synthetic #123, fixed after the fact by harness
    #160).
- **The parallel-dispatch path check** is copied word for word into two agents and enforced by no tool.
- **Incident-driven sentences** have accumulated, for example coordinator step 6 and the README's *Where
  each role can run*.

**Evidence.** The incidents are listed above. The guidance's prompt audit flags instructions written for
older models: absolute phrasing, repeated warnings, procedures a capable model would infer.

**Guidance.** Hard limits go into tools, and tools enforce preconditions. Audit tool descriptions and skills
regularly. Use a prompt audit for instructions written for older models.

**Recommendation.**

- New dispatcher tools:
  - `afs-merge`: merges a work PR or a Verifier PR the safe way, and refuses a stacked `merge-async`;
  - stack-refresh fixes in `stack_refresh.py`, covering depth and already-merged children;
  - `check_dispatch_paths.py`: the parallel path check, run before a parallel dispatch and by CI on
    concurrent PRs.
- Then remove the replaced prose and audit every agent file. Each must stay under its character limit, with
  no rule repeated across files, and every rule that a tool enforces cited as that tool rather than
  restated.

### 9. Skills sprawl

**Problem.** `skills.lock.json` pins 48 skills.

- **Per role:** the Migrator lists 21, the Verifier and the Specialist 18 each, and the Characterizer 14.
- **Overlap:** `refactoring`, `refactoring-guru` and `clean-code`; `verification-before-completion` and
  `afs-evidence`; `code-review` and the gate-3 rule sets.
- **No usage data:** nothing records which skills a session actually loaded, so dead weight is invisible.

**Evidence.** Each role's Skills section lists one skill per line, with a "load only when" note, but nothing
measures whether the note is followed. `tests/test_agents.py` checks only that the agent's list equals the
lock's assignment.

**Guidance.**

- Tool choice degrades beyond roughly 30 to 50 definitions.
- Audit skills for trimming, deduplication and restructuring.
- Measure each skill's cost and usage, and drop dead weight.
- Track whether the agent loaded the right skill.

**Recommendation.**

- Record which skills a session loads, from session logs or the cost hook, into the run journal.
- Audit the lock with `skill-creator`, using that data and the eval. Merge overlapping skills and drop
  unused ones.
- Add a lock-level test that flags a skill assigned to a role but never loaded across the eval.

## Summary

| # | Finding | Recommendation |
|---|---|---|
| 1 | No end-to-end eval | Build a golden-ticket eval first |
| 2 | Specialist Migrator = Migrator + skills | Fold into `afs-migrator` with an `afs-specialty` skill |
| 3 | Slice Coordinator can't dispatch where it runs | Fold into the orchestrator; acceptance as a skill; reconciliation as a tool |
| 4 | Bootstrapper wraps a tool | Fold into the orchestrator as an `afs-bootstrap` skill |
| 5 | Verifier: coupled but valuable | Keep; reduce its cost; confirm with the eval |
| 6 | Analyst → Characterizer → Planner chain loses details | Planner checks as tools; measure an Analyst + Characterizer fold |
| 7 | Auditor | Keep |
| 8 | Hard rules in prose; Frankenprompt | Merge, stack-refresh and path-check tools; prompt audit |
| 9 | Skills sprawl | Record skill loads; audit and prune the lock |
