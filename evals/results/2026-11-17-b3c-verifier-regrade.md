# b3c Verifier cases, regraded with the fixed keywords (phase 3e, step 1)

The six Verifier cases of b3c were regraded on 2026-11-17 with the keyword fixes in #175. These fixes are:
- BK-05E: `application service`, `repository directly`, `calls cargorepository` and `adr-0001`;
- LL-03 and LL-04 verify became clean cases.

The agents' returns are unchanged; only the grading changed.

| Case | r1 | r2 | r3 | Majority | Change from the b3c grade |
|---|---|---|---|---|---|
| synthetic LL-02 verify | P | F | F | fail | none |
| synthetic LL-03 verify (clean) | F | P | F | fail | none |
| synthetic LL-04 verify (clean) | F | P | P | pass | none |
| pilot BK-05G verify (clean) | P | F | F | fail | none |
| pilot BK-05E verify | F | timed out | **P** | fail | r3 now passes: its finding "views call CargoRepository directly; ADR-0001 requires an application service" matches |
| pilot BK-05F verify | F | F | F | fail | none |

**By majority: 1 of 6 pass, as before.** The grader cost BK-05E one run, not its majority, so the Verifier's
weakness is real.

The failures that remain, by kind, and the phase 3e step that targets each:
- **Missed import-level layering defects:** BK-05F (all runs), LL-02 (r2, r3) and BK-05E (r1). Targeted by step
  2, the layering gate.
- **Serious findings without evidence on clean work:** LL-03 (r1, r3) and BK-05G (r2, r3). Targeted by step 4
  (evidence) and step 5 (the operator's ruling).
- **Verdict contradicts findings:** LL-04 r1 (`changes-required` with no serious finding). Targeted by step 3.
- **Blocked on a finding instead of a gate:** BK-05G r2 and r3. Targeted by steps 3 and 6.

## Operator rulings (step 5, 2026-11-17)

- **LL-03 verify becomes a defect case.** htmx 2.0.11 doesn't swap 4xx or 5xx responses by default, so the fee
  page's error fragments never show. Graded that way, b3c gives:
  - r3 pass: `changes-required`, with the htmx finding as major;
  - r1 fail: `changes-required`, but on a ledger finding;
  - r2 fail: `pass`.

  The majority is still fail, so the total stays 1 of 6.
- **BK-05G verify stays clean.** The b3c blocker "the URLconf omits the booking routes" (r2) is a false
  positive.
