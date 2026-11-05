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
- **Ticket disposition first (ADR-0030).** Before checking return files, the AFS map fog workflow requires
  committed, evidence-backed dispositions for all in-scope descendants of the slice epic. Missing or
  invalid reconciliation reopens the epic and suppresses the fog re-walk. This does not replace the
  return-file check below or allow an open child to pass it.
- **`check_slice_returns.py`**, run by the AFS map fog workflow when a slice epic closes, before the fog
  re-walk:
  - every sub-issue of the epic must be closed;
  - every sub-issue closed as completed must have a return file whose `issue:` names it. A ticket
    closed as "not planned" needs none.
  - Current returns must be schema-valid, canonically attributed (`owner/repo#N`) and named
    `<ticket>.<role>.yaml`. If a later run supersedes a return's issue, a valid predecessor at the
    same path in committed **HEAD ancestry** may establish the completed ticket's attribution.
    Current and historical returns must match ticket, role and issue repository; the current return
    must still exist, be valid and match its committed HEAD version. Other refs, unreachable objects,
    deleted files and invalid returns are not proof. Merge-resolution revisions are included;
    local Git replacement refs cannot alter attribution or the rule-installation date.
  - Historical attribution is **not a passing verdict**. A predecessor may report `changes-required`;
    current acceptance and Auditor evidence remain separate requirements. The guard logs the historical
    path, full commit and canonical issue used, without rewriting the superseding return.
  - On failure, the epic is **reopened** with a comment listing each problem, and the re-walk ticket is
    not opened. Closing it again re-runs both steps.
- **Exemption by date, from git.** Tickets closed before the tool was first committed to the target repo
  are exempt, because the rule did not exist yet. The date is that commit's, so there is no list to edit
  by hand. Shallow history cannot establish this date. When a completed, non-exempt ticket lacks a
  current return, unavailable or shallow history fails explicitly (and still reopens the epic);
  fetch complete HEAD ancestry and retry. There is no success-shaped history fallback.
- **Manual run.** The workflow also takes `workflow_dispatch` with an epic number, for an epic that
  closed before the workflow existed. Re-runs are safe: the re-walk ticket is not duplicated if the map
  already has it, and an open epic gets no re-walk.

## Consequences
- An accepted slice has a return file for every ticket done under the rule, whoever did the work and
  wherever it ran.
- A human who finishes a ticket by hand commits a return file for it too. The contract's Durable outputs
  already ask for this; now it is enforced.
- The pilot's Track Cargo epic (#9) passes: its four tickets without return files closed before the rule.
- Issue #70, selected from harness coverage #42, repairs attribution after legitimate supersession;
  it does not change PR-attribution rules or authorize a harness merge or pilot rollout. Installation
  remains a separately reviewed, pinned normal bootstrap.
