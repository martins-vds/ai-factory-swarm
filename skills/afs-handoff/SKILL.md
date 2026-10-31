---
name: afs-handoff
description: Checkpoint and hand off — write a handoff comment on the ticket and stop, so a fresh agent can resume. Use at the context soft limit, when a stop rule fires, when blocked by a decision, and at the end of every session that leaves work unfinished.
---

# Handoff (ADR-0015)

No agent pushes on with a full context. A fresh session that starts from a good handoff beats a tired
one that keeps going.

## When
- Your context use reaches the **soft limit** (`profile.context.soft_limit`, default 60%).
- A stop rule fires (`afs-migration-contract`): repeated failure, bad setup, graph/code disagreement,
  real limit, out-of-contract request.
- Your ticket is blocked by a decision (quirk, capability gap).
- You end a session with the ticket not done.

## How
1. Commit and push what is consistent (WIP commits are fine on the ticket branch; never leave the build
   broken on a shared branch).
2. Post this comment on the ticket:
```markdown
## Handoff — <role> · <UTC timestamp>
**State:** <in progress | blocked | needs human>  ·  **Branch / PR:** <link>  ·  **Last commit:** <sha>
### Done
- <facts, with evidence: gate · exit · log path>
### Remaining
- [ ] <next concrete step>
- [ ] …
### Decisions made
- <decision — why> (or "none")
### Blockers / questions
- <ticket links, stop rule that fired, what a human must do>
### Failing commands
- `<command>` → exit <n>, see `<log path>:<lines>`
### Next step for the next session
<one precise instruction>
```
3. Stop. Do not start anything else.

## Resuming
A new session reads the ticket body and the **latest** handoff comment only — not the whole thread —
then re-runs `afs-setup-check`, re-reads the acceptance criteria, and continues from "Next step".
