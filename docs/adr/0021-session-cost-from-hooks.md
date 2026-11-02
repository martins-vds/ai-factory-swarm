# ADR-0021: Session cost recorded by a Copilot hook

- Status: Accepted (phase 1: tokens per session · phase 1.1: billed credits and attribution · phase 2: below)
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

**Spike result (M5 final audit, coding agent).** The hook ran at `sessionEnd`, and Copilot's final
"Apply remaining changes" commit picked up the record; a push from the hook itself is not needed and would
race with that commit. But at that point the log had no `session.shutdown` and no `assistant.usage`. The
only usage was output tokens per `assistant.message` (35,602 over 89 messages), and the model wasn't named.
Hooks also couldn't see the Copilot token variables, so remote detection uses the Actions runner's
environment.

**Correction (same day).** The Copilot CLI writes `session.shutdown`, with the authoritative per-model
input, cached and output tokens, about a second *after* `agentStop`; other tools that parse these logs
report the same. The hook read immediately. It now polls for that line (`--grace`, default 20 s) and
records `shutdown_wait_s`. When the line arrives, the record holds exact tokens per model, and phase 2's
rate table turns them into exact credits. The billing report remains the cross-check. Pricing trap:
`input_tokens` already includes `cache_read_tokens`, so cached tokens must be priced separately.

**Phase 1.1 (decided after the spike).**
- The hook keeps each session's time window and the field names per event type (`diagnostics.data_keys`),
  so usage fields show up if Copilot adds them. It no longer pushes.
- `tools/afs-costs fetch`, run daily by the AFS costs workflow with the operator's `BILLING_READ_TOKEN`,
  records GitHub's AI-credit and usage reports for the account in profile `costs.billing` under
  `.migration/costs/billing/<date>.json`. Billed figures are exact per day, model and user.
- `afs-costs report` shares each day's agent-SKU credits among that day's harness sessions in proportion
  to their output tokens, and labels the result an estimate. It also shows the day's totals and the
  target repo's Actions minutes.

**Phase 2 (still open):**
- a pinned model rate table, with exact credits per session, once session logs carry input tokens at hook time;
- Actions minutes per coding-agent run, from the Actions API;
- the graph workflow's SDK usage recorded the same way;
- a schema-checked record and a `costs` report by ticket, slice, agent and model;
- a periodic reconciliation against GitHub's billing usage;
- slice budgets, once the numbers are trusted.

## Consequences
- The cost of every harness-started session lands in the repo next to its ticket's outputs.
- Until phase 2, records hold tokens, not credits. If a surface's log lacks `session.shutdown`, its
  record says `partial`, which shows up in the spike rather than going unnoticed.
