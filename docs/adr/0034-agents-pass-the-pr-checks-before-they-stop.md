# ADR-0034: Agents pass the PR checks before they stop, within a budget, then escalate by failure kind

- Status: Accepted (martins-vds, 2026-11-07: budget 2 blocks; every role with a return; the planner
  lists predictable files; drills, then enforce)
- Date: 2026-11-07

## Context
Agents learn that their work broke the contract only after they've stopped. CI fails on the PR, the operator
or the orchestrator notices, and a new session (or a comment that restarts the old one) fixes it. On the
pilot on 2026-11-07:

- **BK-05D (#343)** passed every gate but committed no return file. CI's "Agent PR commits its return
  file" caught it. It took an operator comment and another agent turn to add one file the agent could
  have written in seconds. AM-04C's first session (#323) left the same red check behind.
- **BK-05C (#347)** stopped, correctly, because its file list was too narrow. It needed an empty
  `__init__.py` and its own ledger entries, which only the operator may add to its scope.
- **DM-05C (#322 → #341)** ran four sessions below the mutation threshold (0.682 → 0.752). The
  survivor report gave a location, not the change, so no session could tell a missing test from an
  equivalent mutant. Fixing the tool (harness #104) took the next session to 0.966.

All three were caught by CI, but they are three kinds of failure, and only the first is fixed by trying
again. Current practice agrees on the loop and its limits:
- the agent can't declare completion until deterministic checks pass;
- iteration has a budget, and an agent repeating itself escalates;
- a command failing the same way twice is a stop signal, not a retry cue;
- the check is the harness's tools, never the agent reviewing its own work, because agents grade their
  own output too kindly.

Copilot already supports the mechanism. The harness registers an `agentStop` hook for session cost
(ADR-0021). In the cloud agent and the CLI, an `agentStop` hook that returns `decision: "block"` forces
another agent turn, with its `reason` as the prompt. That turn counts against the job's timeout.

## Decision
1. **One finish check, shared with CI.** `tools/afs-finish-check` runs the same scripts the PR checks run,
   over the session's branch, against the ticket's base:
   - a return file for this ticket and role exists and is valid (`check_return_contract.py`'s rules);
   - every changed file is in the ticket's file list (plus any operator scope extension on the issue);
   - each gate the return reports has a matching `afs-run` journal row;
   - `validate.py` passes.

   It **reads** the journal; it never re-runs the slow gates. A hook has a time limit (30 s by default),
   and mutation takes minutes. CI keeps running the gates. The finish check and CI call the same functions,
   so they can't drift apart. A test asserts it.
2. **A stop hook enforces it.** `.github/hooks/afs-finish.json` runs the finish check on `agentStop` for
   every role that commits a return. On failure it returns `decision: "block"` with a reason that names
   the failed check and the exact fix ("commit `.migration/returns/BK-05D.afs-specialist-migrator.yaml`
   with `issue:` 291 and the gates from your journal").
3. **Failures are classified, and each kind has an owner.**

   | Kind | Examples | Handled by |
   |---|---|---|
   | **Mechanical**: the fix is known and inside the ticket | no or invalid return file, a gate run but not journaled, a return that disagrees with the journal | the agent itself: the hook blocks and the agent fixes it |
   | **Scope**: the fix needs a file or a decision outside the ticket | a file not in the list, a ruling needed | escalate at once. The hook allows the stop, and the agent writes a handoff naming the file or question. An agent never extends its own scope. |
   | **Unreachable**: the gate fails and the agent has no new lead | mutation or CRAP stuck below threshold, a failing test it can't explain | the restart rule: a fresh session from the handoff. The same ticket failing again escalates to the operator (ADR-0008). Repeated failures are also a signal that a tool may be missing information. |

   The finish check decides the kind. The agent doesn't. There is **no standing scope allowance**, not
   even for an empty test-package `__init__.py` or the ticket's own capability ledger entries. The planner
   lists those in every ticket (deterministic plan checks, harness #98), so a complete list is the
   planner's job and anything outside it is a scope failure.
4. **A budget, with loop detection.** The hook keeps a per-session counter in `.migration/runs/`. It
   allows the stop:
   - after `self_heal.max_blocks` blocks (profile setting, default 2); or
   - when the same check fails the same way twice in a row.

   The agent then writes a handoff with state `blocked` and reason `self-check failed: <check>`, and
   it routes like any other handoff: Slice Coordinator, then the operator. A hook error never blocks: it
   allows the stop and records the error, as the cost hook does.
5. **Proven by drills, then enforced.** `afs-drill` gains two drills:
   - a session that leaves out its return file fixes it within the session;
   - a session that edits a file outside its list escalates without retrying.

   Blocking is switched on for a target only after both drills pass on it; until then bootstrap
   installs the hook disabled. From then on it covers every new ticket.

## Consequences
- The common mechanical miss is fixed inside the session, with no operator comment and no new session.
  CI stays the authority: a hook can be skipped (a local session without hooks, a hook error), and CI
  still catches it.
- Scope stays a human decision. The planner checks on harness #98 are the deterministic fix for the
  scope cases; this ADR only makes them escalate faster.
- An extra turn costs time and tokens against the job's timeout. The budget bounds it.
- **To confirm on the first pilot run:** the cloud agent writes a final "apply remaining changes" commit
  after the hooks. The first live run must confirm that work done in a blocked-then-continued turn is
  committed and pushed. If it isn't, the reason must tell the agent to commit and push itself.
- Local workers: the Copilot CLI reads the same `.github/hooks/` file. Claude Code's `Stop` hook uses
  the same `decision: "block"` contract but is configured in `.claude/settings.json`. Copilot also reads
  that file, so writing it could run the check twice per stop. Bootstrap doesn't write it until that is
  checked on a local worker; the script already accepts both payloads.
- **Operator scope extensions are machine-readable:** an `AFS-SCOPE: <path>` line in the issue (one per
  path) adds that path to the ticket's scope. The finish check reads it from the agent's prompt.
