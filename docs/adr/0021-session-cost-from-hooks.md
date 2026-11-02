# ADR-0021: Session cost recorded by a Copilot hook

- Status: Accepted (phase 1: tokens; phase 2: credits, Actions minutes, reports, reconciliation)
- Date: 2026-11-02

## Context
The operator wants the migration's cost, per ticket, slice, agent and model, for every session the
harness starts: remote coding-agent sessions, the Copilot CLI and VS Code. Since 2026-06-01 Copilot bills
in GitHub AI Credits (1 credit = $0.01), computed from input, output and cached tokens at each model's
published rate. Coding-agent sessions also consume Actions minutes.

Copilot hook payloads (`sessionStart`, `agentStop`, `sessionEnd`, …) carry no usage data. But
`agentStop` provides the session transcript path, and the Copilot CLI (which the coding agent runs)
logs each session to `~/.copilot/session-state/<sessionId>/events.jsonl`. Public parsers of that log
read per-model token usage from the `session.shutdown` event's `modelMetrics`. Our own Copilot SDK
runs (afs-understand) already record per-call usage events.

## Decision
**Phase 1 (this ADR).** `tools/afs-cost-hook`, installed by bootstrap as `.github/hooks/afs-cost.json`,
runs on `agentStop` and `sessionEnd`:
- It reads the session log: the payload's transcript path, else the session-state folder.
- It takes per-model tokens from `session.shutdown.modelMetrics`, else from `assistant.usage` events,
  else output-only from `assistant.message`, marking the source and whether it is partial.
- It writes `.migration/costs/<sessionId>.json`, with diagnostics of which events and fields the log
  actually had.
- In a remote session it commits and pushes the record at `sessionEnd`.
- It never fails a session.

Phase 1 is also the spike: the first real sessions show which source each surface actually provides.

**Phase 2 (after the spike):**
- a pinned model rate table, with credits per record;
- Actions minutes per coding-agent run, from the Actions API;
- the graph workflow's SDK usage recorded the same way;
- a schema-checked record and a `costs` report by ticket, slice, agent and model;
- a periodic reconciliation against GitHub's billing usage;
- slice budgets, once the numbers are trusted.

## Consequences
- The cost of every harness-started session lands in the repo next to its ticket's outputs.
- Until phase 2, records hold tokens, not credits. If a surface's log lacks `session.shutdown`, its
  record says `partial`, which shows up in the spike rather than going unnoticed.
