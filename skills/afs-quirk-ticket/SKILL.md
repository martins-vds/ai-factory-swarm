---
name: afs-quirk-ticket
description: Raise a quirk ticket the moment you find source behavior that looks wrong, surprising or undefined (a bug, odd edge case, dead reference, swallowed error). A human decides whether to preserve or fix it. Use instead of silently preserving or silently fixing anything.
---

# Quirk tickets (ADR-0007)

**Raise it immediately**, when found — not at the end of the task. Never answer it yourself, never pick
an option in code before a human has answered.

## Examples of quirks
- An empty table shows "Page 1 of 0".
- A failing query is swallowed and looks the same as "no data".
- A page resets a bean that is declared nowhere.
- Rounding, time zone, encoding or null handling that differs from what users would expect.
- Dead code paths reachable only through odd inputs.

## Create the ticket
On the decision map (a sub-issue of the `wayfinder:map` issue), label `wayfinder:grilling`, assigned to
a human. Body:
```markdown
## Question
<What the source does, in one sentence.> Preserve, fix, or something else?

## Evidence
- Source: <graph node / file:line at the pinned SHA>
- Characterization: <recorded input → output, or the spec example (tier C)>
- Why it looks wrong: <expected vs actual>

## Impact
- Ledger capabilities: <ids>
- Blocks: <ticket links>

## Options
1. Preserve exactly (target reproduces the quirk; a test pins it)
2. Fix (target diverges; the divergence is recorded in the ledger with this ticket as approval)
3. Other
```

### Remote workers without issue access
If you cannot create issues from your session (e.g. a Copilot coding agent), write each ticket body
(the template above, title as the first `# ` line) to `.migration/quirks/<short-id>.md` in your PR and
list the paths under `quirk_tickets`. The coordinator opens them on the decision map, deletes the files
and adds the issue to `quirks` in each affected ledger entry (the file's *Impact* section lists them).

## Then
1. Add the ticket to `quirks` in every affected ledger entry (`afs-ledger`).
2. Add a native blocking edge from the quirk ticket to every ticket that depends on the answer.
3. Continue with work the quirk does not block — inventory, characterization and planning are never
   blocked by a quirk; only implementing its answer is. If your current ticket is the implementation
   and is blocked, hand off (`afs-handoff`) and stop.
4. When answered: implement exactly the chosen option, pin it with a test, and reference the ticket.
