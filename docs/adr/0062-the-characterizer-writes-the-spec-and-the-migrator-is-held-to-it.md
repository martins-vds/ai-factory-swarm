# ADR-0062: The Characterizer writes the spec, and the Migrator is held to it

- Status: Proposed (merging the harness PR that adds it accepts it; targets turn it on with `spec.required`
  after the phase 2 eval)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), steps 2.1 and 2.2; ADR-0061; Matteo Vaccari,
  [Tests as data](https://martinfowler.com/articles/tests-as-data.html)

## Context
ADR-0061 made a slice's customer tests data that a harness-owned runner executes, and proved the runner on
the synthetic target (synthetic #150). It left three questions open. This ADR answers the first two:
- who writes the spec;
- who may change it.

The third, the spec as a named gate, is step 2.3.

If the Migrator writes the spec, it is grading its own work. The article's point is that the customer's
tests must come from somewhere other than the code they check, and that their expected values need an
independent oracle. This harness already has both:
- a role that records what the legacy app does before any code exists, the Characterizer;
- the legacy app itself, through its recorded outputs.

## Decision
1. **The Characterizer writes the spec, before implementation.**
   - The Planner plans one `afs-characterizer` ticket per slice that lists `.migration/spec/<slice>/`, and
     blocks the slice's Migrator tickets on it.
   - The Characterizer writes each capability's rules in its ledger entry, then the cases
     (`skills/afs-migration-contract/references/spec.md`).
2. **Every expected value has a source.**
   - A case names its `oracle:`, the recorded legacy output its values come from. `afs-spec check` refuses
     an oracle path that doesn't exist.
   - A value the legacy app doesn't produce names the quirk ruling that sets it (`ruling:`).
   - With `spec.required`, a case with neither is refused.
3. **A capability that isn't built yet is pending, not failing.**
   - `afs-spec run` runs a capability's cases only once its ledger status is `in-progress` or `migrated`.
   - Before that they are reported as pending (`pending=<n>` in the result line, "not built yet" in the
     rendered spec). So the Characterizer's PR passes before the code exists.
   - The Migrator's PR, which sets `migrated`, must make them pass.
   - `--all` runs them anyway.
4. **The rendered spec shows each case's source.** `afs-spec render` prints each case's oracle or ruling,
   so the reviewer sees where every expected value came from.
5. **Only the Characterizer changes `.migration/spec/`.** Three layers enforce it:
   - **Plan:** `check_plan.py` refuses a spec path in any other role's ticket. With `spec.required`, it also
     refuses a Migrator ticket whose capability has neither a spec file nor a spec ticket before it.
   - **Finish check:** a session of any other role that changed `.migration/spec/` is sent back to restore
     it. A handoff naming the file doesn't excuse it, unlike other out-of-scope files: the spec is the
     contract, not scope.
   - **CI** (`check_return_contract.py`): an agent PR that changes `.migration/spec/` fails unless one of
     its return files is a Characterizer's. A human's PR isn't an agent PR, so the person who owns the
     migration can still correct a spec.
6. **A case the Migrator believes is wrong is a `spec dispute` handoff.**
   - The handoff names the case and gives the evidence: the legacy output, a `file:line`, or a ruling.
   - The human, or a Characterizer ticket, decides.
   - A rule the Migrator finds that no case proves goes in the ledger with `no_spec: found by <ticket>`. The
     rendered spec lists it among the rules no case proves yet.

## Consequences
- The code and its acceptance tests come from different sessions, and the values come from the legacy app.
  A Migrator can no longer make a test pass by changing what it expects.
- A slice gains one ticket. Its cost and its effect on pass rate are measured by step 2.4's eval before any
  target sets `spec.required`.
- The Characterizer's prompt grows by one step and one reference file. The eval repo's agents must be synced
  before the next eval (ADR-0058).
- Not covered: a Migrator could still weaken the code's own unit tests. Phase 3's coupling guard and the
  mutation gate cover those.
- Rejected: letting the Migrator propose spec edits in its own PR for review. Every pilot review so far was
  of the agent's own reasoning, and the article's point is that the checker must be independent of the code.
