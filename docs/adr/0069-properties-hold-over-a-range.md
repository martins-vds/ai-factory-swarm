# ADR-0069: Properties hold over a range

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 4.1; ADR-0061

## Context
The customer spec states behaviour as example rows: the fee at 0, 2, 3, 39, 40 and 165 days late. Rows pin the
exact values at the boundaries. They say nothing about the days between them, or about a date nobody thought
to write down. Some rules are invariants instead: a fee never exceeds $10, and a returned loan's fee never
changes. Those are best stated as properties, which must hold for every input in a range.

The plan proposed Hypothesis, pinned by the stack pack. Hypothesis is a Python library inside the target's
test code. The spec is data run by a harness-owned runner on every stack, so the Migrator can't change it.
Putting properties in the target's test code would undo both.

## Decision
1. **A spec case may have `forall:` instead of `examples`:**
   - each name draws from `int` or `number` ranges (with `places`), a `date` range, or a `one_of` list;
   - `{name}` fills the drawn value into `given`, `when` and `then`, the clock included.
2. **The runner picks inputs without randomness that changes between runs:**
   - each range's low and high ends, one step in from each, and its middle, with the other names at their low
     ends;
   - then random combinations seeded by the case's id, with no repeats;
   - 25 inputs by default, set with `run --samples`.

   The same spec tries the same inputs on every run.
3. **A failure is shrunk.** The runner binary-searches each range toward its start, and a list toward its
   first value, for the smallest input that still fails. It reports that input, then the assertion that
   failed. A property counts as one case in the results and in the rendered spec, which reads "for every
   today from 2026-01-16 to 2030-12-31".
4. **`then.number: {pattern, min, max}`** takes a number from the body (the pattern's first group) and checks
   its bounds. That is how a property usually states an invariant.
5. Hypothesis isn't used, so no stack needs a new dependency. What it would add, such as smarter strategies
   and a database of failing examples, can come later as an option of the runner.

## Consequences
- The synthetic fees spec gains two properties: L1's fee stays between $0 and $10 on every date from 2026 to
  2030, and L3's fee stays $4.75 whatever today is. They passed against the target in CI on a trial branch
  (`gate=spec cases=20 failed=0`).
- With the cap tightened to $9.75 as a check, CI failed with `fails for today=2026-02-25` (the 40th day late,
  when the fee first reaches $10.00) and `number: 10 is above 9.75`. The shrink lands on the boundary itself.
- Each property costs 25 requests, which is still well under a second for the synthetic fee spec.
