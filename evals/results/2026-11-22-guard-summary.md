# Coupling guard eval (test-trust plan, step 3.3), 2026-11-22

The question: does turning the coupling guard on as a blocking rule (`test_health.block: true`, ADR-0064) cost
pass rate?

Setup:
- Harness `bea1099` and model `gpt-6-luna`, pinned.
- Seven Migrator build cases: synthetic LL-01 to LL-05, and pilot BK-05F and BK-05G, with
  `--role-map afs-specialist-migrator=afs-migrator`.
- Two arms of three runs each:
  - **report**: runs `2026-11-22-gr-r{1,2,3}`, the guard on as merged, reporting only;
  - **block**: runs `2026-11-22-gb-r{1,2,3}`, the same branches with `--profile-set test_health.block=true`.

## Pass rate
| Case | Report | Block |
|---|---|---|
| synthetic-ll-01 | 2/3 | 3/3 |
| synthetic-ll-02 | 3/3 | 2/3 |
| synthetic-ll-03 | 2/3 | 3/3 |
| synthetic-ll-04 | 3/3 | 3/3 |
| synthetic-ll-05 | 3/3 | 3/3 |
| pilot-bk-05f | 2/3 | 2/3 |
| pilot-bk-05g | 1/3 | 2/3 (one session timed out) |
| **Total** | **16/21** | **18/21** |

Every failure is unrelated to the guard:
- handoffs with `mutation_changed: n/a: not run, handed off`;
- red CI gates (LL-01 r1, LL-03 r3 and BK-05G r2 in report; LL-02 r2 in block);
- sessions that changed only `.migration/` (BK-05G r1 and BK-05F r3 in report, BK-05F r3 in block);
- one BK-05G session that hit the one-hour limit (block r2).

## What the guard saw
**Zero findings in all 41 graded sessions**, in both arms. Nobody added a patch of the project's own code, a
private access, or an interaction assertion on the project's own code to a test, and nobody used
`# afs: allow-mock`.

I checked the measurement by hand on pilot BK-05F (report r1). The session added 68 test lines and none of
them patches or reaches into internals. Step 2.4's run `sf-r1` (LL-03 spec-first) shows the guard does fire
when there is something to find: it flagged 6 patches of `src.fees.views.payment_application`.

## What it shows
- **No pass-rate loss.** The block arm passed 18/21 against 16/21. The guard never fired, so the difference
  is noise, not an effect.
- **Today's Migrator rarely writes coupled tests on these cases.** The phase 3e prompts (test through the
  use case, rules in the right layer) and the ADR-0045 self-verification already steer it. The guard is a
  backstop for the run that slips, like `sf-r1`, not a constant corrective.
- **Blocking is safe to turn on per target.** It costs nothing when tests are written well, and it refuses
  the occasional coupled line with an exact fix, or makes the agent give a reason with `# afs: allow-mock`.

## Not graded
The 12 pilot sessions first failed to start because the case agent is the retired `afs-specialist-migrator`.
I re-dispatched them with the role map. The failed issues are closed as not planned, and the state files
hold the re-dispatched issues.
