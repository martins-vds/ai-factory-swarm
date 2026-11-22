# Spec-first eval (test-trust plan, step 2.4), 2026-11-22

Runs `2026-11-22-sf-r1`, `-r2` and `-r3`. Harness `91a1047` (ADR-0061 to ADR-0063), model `gpt-6-luna` pinned
(ADR-0060), eval agents synced (eval #2290, #2291). There were four cases per run, all on the synthetic
target's fees slice:

| Case | What it measures |
|---|---|
| `synthetic-fees-spec` | The Characterizer writes the fees spec (FS-01). It starts where fees is built and accepted but has no spec, so CI's spec gate runs every value against the accepted code. |
| `synthetic-ll-03-spec` | LL-03 (build fees), with the reviewed spec (synthetic #150) and its five rules in place first. |
| `synthetic-ll-03` | LL-03 as today: no spec. This is the baseline. |
| `synthetic-refactor-fee-views-spec` | The phase 0 refactor (REF-02), with the spec in place and CI's gates required. |

## Results
| Case | r1 | r2 | r3 | Passed |
|---|---|---|---|---|
| Characterizer writes the spec | ✅ | ✅ | ✅ | **3/3** |
| LL-03, spec first | ❌ browser test | ✅ | ✅ | **2/3** |
| LL-03, today | ❌ browser test | ❌ handed off (idiom) | ✅ | **1/3** |
| Refactor, spec in place | ✅ | ✅ | ✅ | **3/3** |

**The Characterizer's specs**, as metrics from `afs-eval grade`:

| Run | Spec files | Cases (rows expanded) | Rules proved | Cases citing an oracle | Minutes |
|---|---|---|---|---|---|
| r1 | 2 | 11 | 7 | 4 | 5.3 |
| r2 | 2 | 12 | 6 | 5 | 5.2 |
| r3 | 2 | 12 | 6 | 5 | 5.1 |

- Every spec covered both capabilities and wrote at least 4 rules for `fees.calculation`.
- Every case named its oracle, a recorded legacy output. `validate.py` enforces this with `spec.required`.
- Every spec changed only spec and ledger files.
- In CI, every spec ran against the accepted fees code with no failures (`gate=spec cases=11–12 failed=0`).
- None cited a quirk ruling. No fee value differs between the legacy app and the accepted target, so none was
  needed.

**LL-03 with the spec first, against today:**
- Every spec-first run left the spec unchanged. There were **no spec disputes** in 3 runs.
- The spec gate passed in every spec-first run, including r1, which failed only on a browser test.
- Both passing spec-first runs reported `gates.spec: 0`, backed by the journal: `validate.py`'s
  `check_spec_gate` found no error.
- Session time was similar: 26–38 min with the spec, 10–32 min without. Today's r2 was short because it handed
  off.

**Every LL-03 failure, in both arms, came from the Migrator's own tests, not the spec:**
- r1 baseline: `test_browser_renders_a_gateway_failure_after_payment`;
- r1 spec-first: `test_browser_displays_htmx_payment_failure`, a timeout;
- r2 baseline: a handoff with ruff and CRAP failures.

The two browser tests are the click-then-check pattern that LL-01 and LL-03 failed on before (plan step 4.5).

**Refactor resistance:**
- The refactor ran 3 of 3 with the spec in place.
- Every run left the spec unchanged, CI's spec gate passed after the restructuring, and no existing test was
  modified or deleted.
- This matches phase 0's synthetic result (HTTP-level tests needed no change). The spec adds the customer's
  own cases to that safety net at no extra cost.

## What it shows
- **A Characterizer can write the spec.** It takes about 5 minutes and roughly 70 requests, which is cheap
  next to a 25–35 minute Migrator session. Every value it wrote held against code a human had already accepted.
- **Writing the spec first didn't hurt the Migrator.** It passed 2 of 3, against 1 of 3 today. The sample is
  small, and the failures in both arms are the same browser-test flakiness, so this shows no regression rather
  than a gain.
- **The protection held.** No session tried to change a spec, and none needed a dispute.
- **Not measured here:** the spec mutation score (mutmut doesn't run in this environment, and CI doesn't run
  it per PR). It is first recorded at a real slice acceptance (ADR-0063).

## Not graded
"Concurrent work owns distinct files" failed on all three spec PRs because the GitHub API rate limit was
reached (`rate limit exceeded for installation`). The eval doesn't grade that job, and it doesn't depend on
the agent's work.
