# The two unmeasured folds, measured (2026-11-21)

Three folds already had their own eval: the Specialist Migrator and the Verifier into the Migrator
(ADR-0042, ADR-0045), and the Bootstrapper into the Program Orchestrator (ADR-0046). This run measures the
other two, three runs per configuration, on harness `764f75b` with the eval repo's agents synced to it
(ADR-0058).

| Fold | Cases | Folded | Unfolded |
|---|---|---|---|
| Slice Coordinator → Program Orchestrator (ADR-0050) | `synthetic-lc-accept`, `-lf-accept`, `-li-accept` | Program Orchestrator with `afs-slice-acceptance` | the pre-fold `afs-slice-coordinator` (`evals/variants/`) |
| Analyst + Characterizer in one session (ADR-0051) | `synthetic-legacy-understand` | one `afs-understander` session | the Analyst, then the Characterizer on its PR |

## The agents in earlier evals were stale
Preparing this run showed that the eval repo's `main` had served harness `ca620b9`'s agents since
2026-11-18. Copilot reads custom agents from `main`, so phase 2b, phase 3d and phase 5 ran the old prompts.
ADR-0058 makes `prepare` refuse to run on that drift, and eval #1944 synced `main`. Phase 5's shortened
prompts (ADR-0053) are measured again separately.

## Slice acceptance: the fold holds once the return layout is enforced

| Case | Folded (r1, r2, r3) | Unfolded (r1, r2, r3) |
|---|---|---|
| synthetic-lc-accept | fail, fail, pass | fail, pass, fail |
| synthetic-lf-accept | fail, pass, pass | pass, pass, pass |
| synthetic-li-accept | pass, pass, fail | pass, pass, pass |
| **Runs passed** | **5 of 9** | **7 of 9** |
| By majority | 2 of 3 cases | 2 of 3 cases |
| Median minutes, requests | 3.9, 42 | 3.9, 37 |

Each run is graded on:
- the acceptance fields: the slice, `human_check: requested`, gates all green, and the archived run's
  mutation score;
- an evidence report that states the run's results;
- a ticket reconciliation with one final disposition for every descendant;
- changes only under `.migration/`.

Golden values come from the archived acceptance runs and the tracker's sub-issues. No run in either
configuration set `human_check: passed`.

**Failures that only the fold had:**
- **The wrong return layout, 2 of 9 folded runs.**
  - LF r1 wrote the retired coordinator's layout, with `slice`, `tickets` and `human_check` at the top
    level.
  - LC r2 put `human_check` outside its `acceptance` block.
  - `check_signoff.py` reads only the block, so on a live target neither return's human check would
    register. `validate.py` didn't refuse either one.
  - **ADR-0059 refuses that layout.** Run against all the folded returns, it catches exactly these two.
    The finish check runs `validate.py`, so a session would be sent back to fix it.
- **An honest open question, 1 of 9 (LI r3).** The orchestrator left `needs_review` on #104: its PR merged
  as a failed verification, and it is closed as completed. The live coordinator marked it completed. The
  skill requires every `needs_review` to be resolved, so this fails, but it is a judgment the tracker
  makes genuinely hard, not a layout slip.

**Failures in both configurations:**
- **LC's own ticket left open, 2 of 3 runs each.** Both roles marked the acceptance ticket #108
  `retained-open` "until the human check", where the procedure says your own ticket is `completed` with
  your PR. It's the same in both, so it doesn't count against the fold. It suggests the procedure needs an
  example.

**One grading change, applied to both configurations:** after wave 1, the report check accepts the
flow's name ("overdue" fees, a "repeated return") as well as its route. Wave 1's unfolded LF report
listed exactly what to compare without naming `/ui/fees`.

**Verdict:** after ADR-0059 removes the layout failures, the folded orchestrator passes 7 of 9, the same
as the coordinator. Keep the fold. Confirm by re-running the three acceptance cases with ADR-0059 in the
phase 5 re-run.

## One understand session doesn't hold at this scope

| Run | Two sessions: rules, values, minutes | One session: rules, values, minutes |
|---|---|---|
| r1 | 13/14, 5/6, 10.8 (3.5 + 7.3): **pass** | 12/14, 0/6, 3.4: fail |
| r2 | 13/14, 5/6, 9.1 (2.8 + 6.3): **pass** | 9/14, 0/6, 4.1: fail |
| r3 | 14/14, 6/6, 13.3 (3.9 + 9.4): **pass** | 8/14, 0/6, 2.8: fail |

The scope is the whole synthetic `legacy/` source: 7 Java files, 17 capabilities, tier A. That's about
twice phase 4b's member-billing case. The golden 14 rules and 6 values all match the live SY-04 and SY-05
output.

- **The one session never characterized.** It re-ran the existing 9-case suite (7 cases in r2) and
  claimed 13 capabilities at tier A, but added no new case or golden. The chained Characterizer extended
  the suite each time, as the live one did (25 cases).
- **It inventoried less as it went.** It wrote 12, then 9, then 8 of the 14 rules. It missed all three fee
  rules in r2 and r3.
- **In r3 it committed no Characterizer return at all,** with no handoff: the miss phase 4b saw.
- **It's cheaper only because it skips the work:** about 3 minutes against about 11.

**Verdict:** this confirms ADR-0051's first decision: fold only a small scope. The two observations
bracket where that ends: four files passed in phase 4b, and seven files with 17 capabilities fail here.
ADR-0051's second decision (a finish check that refuses a combined return without its characterization
part) would catch r3 but not the shortcut in r1 and r2. So for any scope larger than phase 4b's, the two
sessions stay.

## Correction: the runs mixed two models (added after ADR-0060)
Copilot chose the model per session. Re-grading the run files with the model each session ran gives:

| | `gpt-6-luna` | `mai-code-2-flash` |
|---|---|---|
| Acceptance, folded | 2 of 4 passed (LF r1: layout; LI r3: `needs_review`) | 3 of 5 (LC r1: own ticket; LC r2: layout) |
| Acceptance, unfolded | 6 of 6 | 1 of 3 (LC r1 and r3: own ticket) |
| Understand, both configurations | none | all 18 sessions |

- **The loan-circulation "own ticket" failures were all `mai-code-2-flash`,** in both configurations.
- **The layout failures were one on each model.**
- **On `gpt-6-luna`** the folded orchestrator passed 2 of 4 and the coordinator 6 of 6. With ADR-0059 the
  orchestrator would pass 3 of 4. These samples are too small to call the fold even.
- **The understand comparison** is clean within one model, but it measured `mai-code-2-flash` only.

The verdicts above stand as written for the mixed runs, but they aren't a measurement of either model.
Both folds are re-run with the model pinned to `gpt-6-luna`, the baseline's (ADR-0060).

## Pinned to `gpt-6-luna`: the result that counts (added after ADR-0060)
Three more runs per configuration, every session on `gpt-6-luna`, harness `2e64302` and later (ADR-0059 in
force):

| | Run 1 | Run 2 | Run 3 | Total | Median minutes |
|---|---|---|---|---|---|
| Acceptance, folded orchestrator | 3/3 | 3/3 | 3/3 | **9 of 9** | 5.5 |
| Acceptance, pre-fold coordinator | 2/3 | 3/3 | 3/3 | **8 of 9** | 4.8 |
| Understand, two sessions (rules, values, minutes) | pass (14, 6, 26) | pass (14, 6, 31) | pass (13, 6, 25) | **3 of 3** | |
| Understand, one session (rules, values, minutes) | pass (14, 6, 12) | pass (14, 6, 13) | fail (0, 0, 1) | **2 of 3** | |

- **Slice acceptance:** the folded orchestrator passed every run. No return had the old layout.
  - The coordinator's one miss was loan circulation in run 1: it wrote
    `gates: "all-green (acceptance run …)"` instead of `all-green`.
  - **The fold holds:** it is no worse than the coordinator, and slightly better here.
- **Understand on the whole `legacy/` source:** on `gpt-6-luna`, one session extended the
  characterization and recorded every golden value in two of three runs, in about half the time.
  - Its third run stopped at setup. My case text says "The source is `legacy/` at the pinned commit". The
    agent checked the in-repo `legacy/` folder against the lock, found it writable and not ignored, and
    handed off. The pinned source is `.source/legacy`.
  - That sentence is the case's fault. Both configurations got it, and the Analyst sessions read it
    correctly.
  - **On this model the fold doesn't fail at this scope.** The 0-of-3 result above was
    `mai-code-2-flash`. Two of three on one model is not enough to widen ADR-0051's scope rule. It is
    enough to say the earlier failure was the model's.

**Revised verdicts:**
- **ADR-0050 (the Slice Coordinator fold):** keep it. 9 of 9 on the pinned model, with ADR-0059.
- **ADR-0051 (one understand session):**
  - The large-scope failure belongs to `mai-code-2-flash`. On `gpt-6-luna` one session did the work in
    about half the time, 2 of 3.
  - Decision 1 (small scopes only) stays until a pinned run with the case text fixed shows it holds at
    this size. Decision 2's finish check would make a combined session's missing half impossible.

## Understand again: finish check on, case text fixed (2026-11-22)
Pinned to `gpt-6-luna`, three runs each. This time the finish check was on, as on the live targets (#225), and
the case named `.source/` as the source:

| Run | Two sessions (rules, values, minutes) | One session (rules, values, minutes) |
|---|---|---|
| r1 | pass (14, 6, 33) | did the work (14, 6, 24), but only the Analyst return |
| r2 | pass (13, 6, 32) | did the work (14, 6, 13), but only the Analyst return |
| r3 | pass (14, 6, 29) | thin ledger (7, 5, 22), only the Analyst return |

- **The finish check refused the combined session's second return** in every run: "A session writes only
  its own return". The understander is an eval variant, not a role the harness supports. On a live target
  it couldn't finish SY-05 in the same session. That's ADR-0051's decision 2, which isn't built.
- **On the work itself,** the one session matched the two in two runs of three and fell short in one (7 of
  14 rules), at 13–24 minutes against about 31.
- **Across both pinned evals,** one session did the work in 4 of 6 runs, and two sessions in 6 of 6.

**Verdict for ADR-0051:** keep two sessions at this scope. One session saves about a third of the time but
misses about one run in three, and adopting it would also take decision 2's combined return. Decision 1 (fold
only a scope like phase 4b's) stands.

DM-05D and DM-05F weren't measured. The Copilot installation's API quota stayed exhausted ("rate limit
exceeded for installation") even in a quiet window, so the snapshot fetch failed in setup. DM-05F's one
session that got a snapshot then failed CI, which couldn't fetch it either.

## Run files
`2026-11-21-fold-{accF,accU}-r{1,2,3}.json` (acceptance, mixed models), `2026-11-21-foldL-*-r{1,2,3}.json` (pinned to `gpt-6-luna`),
`2026-11-21-fold-undB-r{1,2,3}.json` (one session),
`2026-11-21-fold-undA-r{1,2,3}.json` and `-undAc-r{1,2,3}.json` (the Analyst, then the Characterizer on its
PR; the chained file grades both sessions' work together).
`2026-11-22-und2{A,Ac,Ac-r1b,B}-r*.json` (understand with the finish check on; r1's first chain didn't start), `2026-11-22-dm-q{1,2}.json`.
