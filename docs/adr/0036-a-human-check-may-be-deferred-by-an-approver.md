# ADR-0036: A slice's human check may be deferred, by an approver, with a tracked deadline

- Status: Proposed
- Date: 2026-11-07
- Amends: ADR-0031

## Context
ADR-0031 makes a slice's human sign-off an approver's approving review of the Slice Coordinator's PR,
after the side-by-side check. A slice's return has three states: `requested`, `passed` or `issues`.

On the pilot (2026-11-07) the data-migration slice was ready for its check, with the acceptance run passed
and the Auditor's verdict `complete`, but the operator couldn't do the check then. They asked to approve it
anyway "for the sake of keeping progressing". The harness had two options, and both were wrong:
- recording `passed` would claim a check nobody did: the quiet failure the harness exists to prevent;
- leaving it at `requested` keeps the record honest, but nothing says when the check is due or who owes
  it, so it can be forgotten.

"Accept now, check later" is a legitimate operator decision, not an error. It should be a state the harness
records, enforces and follows up, not something done by bending `passed`.

## Decision
1. **A fourth state: `human_check: deferred`.** A Slice Coordinator records it only when the operator
   says to defer, and with all of:
   - `human_check_issue`: an open issue for the check, assigned to an approver in `signoff.approvers`,
     listing exactly what to compare (the Coordinator's `human_check_comparison`);
   - `human_check_due`: a date, by default 7 days from the deferral, at most 30.
2. **Only an approver defers.** A deferral is a sign-off decision, so ADR-0031 applies to it as to
   `passed`: `check_signoff.py` requires an approving review, by an approver, on the PR's head commit,
   for a newly recorded `deferred`. An agent can't defer for anyone.
3. **What a deferral allows.** Slices that depend on this one may proceed. That is all.
4. **What it doesn't allow.**
   - The slice epic does not close: the ADR-0024 and ADR-0030 closure checks accept only `passed`.
   - The fog re-walk after the slice (ADR-0022) waits for the epic to close, as before.
   - The final verification counts a deferred slice as unaccepted.
5. **Deadlines are followed up.** On every run, `check_signoff.py` lists each deferred slice with its
   issue and due date:
   - once a deferral is past due, every harness-check run warns, and the issue gets a comment once a day;
   - after 30 days past due, harness-check fails until the check is done or the deferral is renewed, with
     a new approved PR and a new date.
6. **Leaving the state.** The check is done the usual way: `passed` with an approving review closes the
   tracking issue; `issues` reopens the work, as in ADR-0031.

## Consequences
- The record says what happened: "accepted by the machine, the human check deferred by <approver> until
  <date>". Nobody can read it as a check that was done.
- The roadmap moves on without bending the sign-off rule, and the open check can't be forgotten: it has
  an owner, a date and a warning that gets louder.
- Agents still can't sign off, and now can't defer either.
- To build:
  - the return schema and the Coordinator's contract gain `deferred`, `human_check_issue` and `human_check_due`;
  - `check_signoff.py` handles approval, the deadline warnings and the 30-day failure;
  - the closure checks require `passed`;
  - tests and a drill (a deferral without an approval fails).
