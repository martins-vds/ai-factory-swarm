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

## Run files
`2026-11-21-fold-{accF,accU}-r{1,2,3}.json` (acceptance),
`2026-11-21-fold-undB-r{1,2,3}.json` (one session),
`2026-11-21-fold-undA-r{1,2,3}.json` and `-undAc-r{1,2,3}.json` (the Analyst, then the Characterizer on its
PR; the chained file grades both sessions' work together).
