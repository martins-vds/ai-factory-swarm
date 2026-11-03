# ADR-0024: A slice epic closes only when every ticket under it left its return file

- Status: Accepted
- Date: 2026-11-03

## Context
Every agent run ends with a committed return file (`.migration/returns/<ticket>.<role>.yaml`). It is the
durable record of what the run did, and the dispatcher reads it. `check_return_contract.py` enforces
this, but only on agent pull requests. Work that never becomes an agent PR is not checked: an agent run
locally (the Program Orchestrator and Slice Coordinator usually are), or a ticket finished by hand.

On the pilot, four Track Cargo tickets have no return file: the Analyst, Characterizer, Planner and TC-01
tickets. All four merged before the PR check was installed, so nothing was wrong at the time. But nothing
would have caught the same gap later either: the epic closed, and the slice was accepted, without anyone
or anything counting.

The slice epic is where all of a slice's tickets meet, and closing it is the acceptance. That is the
moment to count.

## Decision
- **`check_slice_returns.py`**, run by the AFS map fog workflow when a slice epic closes, before the fog
  re-walk:
  - every sub-issue of the epic must be closed;
  - every sub-issue closed as completed must have a return file whose `issue:` names it. A ticket
    closed as "not planned" needs none.
  - On failure, the epic is **reopened** with a comment listing each problem, and the re-walk ticket is
    not opened. Closing it again re-runs both steps.
- **Exemption by date, from git.** Tickets closed before the tool was first committed to the target repo
  are exempt, because the rule did not exist yet. The date is that commit's, so there is no list to edit
  by hand.
- **Manual run.** The workflow also takes `workflow_dispatch` with an epic number, for an epic that
  closed before the workflow existed. Re-runs are safe: the re-walk ticket is not duplicated if the map
  already has it, and an open epic gets no re-walk.

## Consequences
- An accepted slice has a return file for every ticket done under the rule, whoever did the work and
  wherever it ran.
- A human who finishes a ticket by hand commits a return file for it too. The contract's Durable outputs
  already ask for this; now it is enforced.
- The pilot's Track Cargo epic (#9) passes: its four tickets without return files closed before the rule.
