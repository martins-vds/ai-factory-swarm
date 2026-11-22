# ADR-0063: The spec is a gate, and the mutants it misses are reported

- Status: Proposed (merging the harness PR that adds it accepts it; it applies on a target whose profile
  sets `gates.spec`)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 2.3; ADR-0061; ADR-0062; Matteo Vaccari,
  [Tests as data](https://martinfowler.com/articles/tests-as-data.html)

## Context
ADR-0062 has the Characterizer write the customer spec and holds the Migrator to it. On the synthetic target,
the spec ran as one more command of the `tests` gate. There it had two weaknesses.

**A spec that runs inside `tests` is invisible in the return.**
- A pass of the unit tests and a pass of the customer's cases read the same.
- Since ADR-0062, a capability not marked built is skipped as pending. So a Migrator could run the spec
  before setting `migrated` and report a pass in which its own cases never ran.

**The spec itself needs checking.** The article's point is that tests need validating too. Mutation
testing does that for the unit tests: the score says how much of the code they pin down. Nothing yet says
how much of the code the customer's own cases pin down.

## Decision
1. **`gates.spec` is its own gate** in the profile: `python .migration/harness/tools/afs-spec run`.
   - A Migrator ticket that builds a capability with a spec file reports it as `gates.spec: <exit>`.
   - The finish check treats it like the other exit gates: a failing gate needs a handoff, and a stale one
     is re-run.
   - CI's gates job runs it after `tests`, and the slice's acceptance run (`afs-acceptance`) runs it when the
     profile declares it.
2. **`validate.py` checks the spec gate against the journal** (`check_spec_gate`). For a finished Migrator
   return whose ticket builds a specced capability, when the profile has `gates.spec`, it requires that:
   - `gates.spec` is `0`;
   - the journal holds a run of that command;
   - its last run exited 0 with `failed=0`;
   - none of the ticket's own capabilities appear in the run's `pending_caps`. `afs-spec run` now names the
     capabilities it skipped in its result line, so a run made before the ledger said `migrated` doesn't
     count.

   Returns committed before the rule are exempt (`SPEC_GATE_RULE_V1`).
3. **`afs-mutation --spec` runs every mutant against the spec alone.**
   - It is a report, not a gate: the result line is `gate=spec-mutation`, the exit is 0 whatever the score,
     and survivors go to `.migration/evidence/mutants/<ticket>.spec.md`. It never replaces the ticket's
     unit-test survivors file.
   - Slice acceptance runs it with `--all` and records `spec_mutation_score` in the evidence report. Each
     survivor is behaviour the customer's cases don't pin down, for the human and the next Characterizer
     ticket.

## Consequences
- The return now separates "my tests pass" from "the customer's cases pass". The second can't be claimed
  with the customer's cases skipped.
- A low spec mutation score isn't a failure. It shows where the spec is thin, so the human reads it with the
  rendered spec instead of trusting a green check.
- Each spec mutant sets up the test database once. That is slow, which is one reason it runs once per slice,
  not per PR.
- A target moves its `afs-spec run` from `gates.tests` to `gates.spec` when it re-rolls the harness. The
  synthetic target is the first.
- Not decided: making the spec mutation score a threshold. That waits for scores from the step 2.4 eval and
  from the targets.
