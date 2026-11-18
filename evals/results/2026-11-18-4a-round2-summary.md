# Phase 4a, round 2: Migrator cases that start clean (2026-11-18)

Round 1 (`2026-11-18-4a-summary.md`) was inconclusive because no defect reached a merge candidate. This round
ran the four steps its "Next" section named.

1. **BK-05F fresh** (`pilot-bk-05f-fresh`): from the parent of PR #394's first commit (`17e26a2`). The
   Migrator writes the route-selection views itself; the base has no defect and no handoff.
2. **BK-05G fresh** (`pilot-bk-05g-fresh`): from the same commit, with the operator's later scope extension
   for the not-routed table. It is prone to rule-placement and legacy-difference defects: it has three quirk
   rulings, and a use case (`CargoSpecification`) the views must go through. Its oracle forbids building a
   `RouteSpecification` or calling `is_satisfied_by` in a web adapter.
3. **LL-02 r2's whitespace finding is settled against the legacy.** `LoanResource.lend` and
   `LoanRepository.lend` store the member and ISBN as given, and ruling #39 only rejects blank values. So
   trimming valid values is an unruled divergence, and round 1's Verifier finding was real.
   - `oracle.forbid_stripped_args` now flags a stripped value passed to `lend` or `create`.
   - It also flags a Django form field that strips by default (a `CharField` without `strip=False`, or a
     `ModelForm` field generated from the model).
   - The live LL-02 (synthetic main) lends through a `ModelForm`, so it trims too.
4. **Re-run:** eight Migrator cases, two runs each:
   - BK-05F fresh replaces BK-05F;
   - the cases also include BK-05G fresh, BK-05G, DM-05F and LL-02 to LL-05.

   Runs:
   - **A:** `4ra` (Migrator), then `4rv` (chained Verifier).
   - **B:** `4rb` (`afs-migrator-selfverify`).
   - **Audit (new):** `4rx` is a Verifier on each finished B head. It is a measurement only, not part of
     configuration B. Without it, B's heads would be judged only by the oracle, which misses defect classes
     no tool checks yet. This round shows such a class (below).

## Results

| Case | A Migrator r1 / r2 | A Verifier r1 / r2 | B r1 / r2 | Audit of B r1 / r2 |
|---|---|---|---|---|
| BK-05F fresh | timed out / timed out (oracle: **defect**) | — / — | pass / timed out | timed out / — |
| BK-05G fresh | pass / fail | changes-required (false) / timed out | pass / pass | timed out / blocked, minor finding |
| BK-05G | fail / timed out | — / — | pass / timed out | pass / — |
| DM-05F | pass / pass | blocked / blocked | pass / pass | pass / pass |
| LL-02 | pass / pass (oracle: **defect**) | pass / **changes-required** | pass / pass | pass / pass |
| LL-03 | pass / fail | pass / — | fail (oracle: stale CSS) / pass | — / pass |
| LL-04 | pass / fail (oracle: stale CSS) | pass / — | pass / pass | pass / pass |
| LL-05 | pass / pass | pass / pass | pass / pass | pass / pass |

"Fail" means the Migrator's own Gates or return failed, so the head isn't a merge candidate. Oracle findings on
such heads don't count.

### Defects on merge candidates (green Gates, return committed)

- **A, LL-02 r2: a major defect, caught by A's Verifier.**
  - The Migrator edited htmx's response rules by matching `response.code === '4..'` and `'5..'`. htmx 2's
    default rule is spelled `'[45]..'`, so nothing matched. Error responses stayed unswapped, and the browser's
    not-found message never showed.
  - `check_ui.py` counted the word `responseHandling` as handling. It now fails on a match against a code
    htmx 2 doesn't define (fixed in this PR, with a test). With the fix, the oracle finds this defect on that
    head only.
  - The Verifier's second finding was that blank rejection lives only in the form. That is not a defect: the
    accepted live LL-02 puts it there too (ledger `target.components`: `LoanForm`).
- **B, BK-05G fresh r2: one minor divergence, found only by the audit.**
  - The deadline input has `min=today`. The legacy change-deadline dialog has no minimum; the inventory gives
    one only for the booking wizard's date page.
  - It is minor. Under ADR-0043, a minor finding doesn't change a Verifier's verdict, so A would let it
    through too.
- **Nothing else.** Every other merge candidate in both configurations is oracle-clean, and the audit passed
  every B head it finished.
- **BK-05F fresh does produce the rule-placement defect.**
  - A r2's Migrator put `route_specification.is_satisfied_by(...)` in `route_selection/views.py:88`.
  - That session timed out, so its head isn't a merge candidate.
  - B r1 finished BK-05F fresh cleanly, and the oracle found nothing.

### False or empty Verifier verdicts (A)

- **BK-05G fresh r1: a false `changes-required`.** It asked the destination use case to reject destinations
  the dialog doesn't offer. But the legacy `changeDestination` accepts any destination: the filtering is in
  the view bean (`inventory.md`, `ChangeDestination`). The code it named is BK-05A's
  `specification.py`, not BK-05G's.
- **DM-05F `blocked`, twice:**
  - r1 hit its time limit during mutation.
  - r2 found the profile's export command missing. That command belongs to DM-05D, which isn't built at this
    case's base, so it's a gap in the case, reported correctly as `inherited`.
- **One Verifier timed out (BK-05G fresh r2).** The audit had two timeouts and one block from its time limit.

### Cost (recorded sessions)

| | Sessions | Timed out | Minutes | Requests |
|---|---|---|---|---|
| A (Migrator + Verifier) | 26 (16 + 10) | 4 (3 + 1) | 640 (357 + 283) | 4,064 (2,601 + 1,463) |
| B | 16 | 2 | 395 | 3,113 |

- B used 38% fewer minutes and 23% fewer requests.
- Timed-out Migrator sessions record no cost, so both columns undercount, A's by one more session.
- The audit's sessions are a measurement, so they aren't counted in B's cost.

## Both rounds together

| | A | B |
|---|---|---|
| Major defects on merge candidates | 2 (LL-02 trimming, LL-02 htmx codes); both caught by A's Verifier | 0 (audit-confirmed in round 2) |
| Major defects that would have merged | 0 | 0 |
| False `changes-required` | 1 | n/a |
| Minutes | 1,071 | 728 |

Both major defects came from the plain Migrator in LL-02. Neither of B's two LL-02 heads in either round had one.

## Decision

**The plan's rule is met: B catches every real-defect case A catches, on both runs, and costs about a third
less. Proposed: fold the Verifier into the Migrator for Migrator tickets (ADR-0045).**

- The rule was set before the experiment. This time it isn't met vacuously: A's Verifier caught real major
  defects twice, and B's heads for the same case had none, which an independent audit confirmed.
- **Caveats:**
  - The numbers are small. The two defects are in one case, so this is a direction, not a rate.
  - The only defect B shipped is minor, and A would ship it too.
  - B's sessions run longer: two hit the hour limit, against A's three Migrator timeouts.
  - A's Verifier was unreliable on the pilot cases. It gave one false `changes-required`, two `blocked`
    verdicts and one timeout across 10 sessions.
- What the Verifier found that no tool checked (htmx codes, unruled legacy differences) feeds `check_ui` and
  the oracle. The htmx case is already a gate.
