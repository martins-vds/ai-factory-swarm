# ADR-0015: Context budget and tool-output hygiene

- Status: Accepted (tooling choices to be confirmed by spike M1-d)
- Date: 2026-10-30

## Context
Model accuracy, reasoning and instruction-following degrade as the context window fills, well before
it is full ("context rot"). Every agent is exposed; implementers most of all, because they read code,
run builds and tests, and iterate. The largest silent contributor is **tool output**: build logs, test
reports, stack traces, mutation reports, directory listings, diffs.

## Decision

### 1. Small tasks, fresh sessions
- One ticket = one fresh agent session. Agents are never carried from ticket to ticket.
- Tickets are sized to an operator-set **working budget** (starting point: 40–50% of the model's
  window). The Planner splits tickets predicted to exceed it, using files and graph nodes touched and
  CRAP score as predictors.
- Coordinators hold ids and paths, not content, and are restarted at phase boundaries.

### 2. Checkpoint and restart
- At a soft limit (starting point: ~60% of the window), an agent writes a **handoff** comment on its
  ticket (done, remaining, decisions, failing commands with log paths, next step) and ends. The
  coordinator starts a fresh agent from the ticket and handoff.
- Prefer this over automatic compaction for implementers. If the platform compacts anyway, the ticket
  handoff is the source of truth.

### 3. Load little, load late
- Start from the ticket, its ledger entries and the relevant profile entries; query the graph for the
  rest; read source only through the file-read gate and only the needed line ranges.
- Load only the skills the ticket needs; keep SKILL.md files short with detail in references.
- Recall only the few lessons-learned cards relevant to the ticket.

### 4. Tool output stays on disk; the agent sees a summary
Enforced in layers, from deterministic to optional:

| Layer | What | Where it works |
|-------|------|----------------|
| **a. `afs-run` wrapper** (harness tool) | Runs any command; writes full stdout/stderr to `.migration/runs/<ticket>/<timestamp>-<name>.log` (gitignored); prints only a compact summary: exit code, duration, line count, failing tests / first errors (parsed from JUnit XML, LCOV, etc. where available, else last N lines), and the log path. The agent greps the log when it needs more. Gate evidence links to these logs. | Everywhere (local and remote), any language |
| **b. Filter engine: RTK** ([rtk-ai/rtk](https://github.com/rtk-ai/rtk), MIT) | A single-binary CLI proxy with compact filters for 100+ common commands (git, test runners, linters, docker, …), generic `rtk test` / `rtk err` wrappers, and an install mode that hooks the agent's shell so commands are rewritten transparently. Used by `afs-run` where it has a filter, or directly. Only shell commands go through it; built-in file read/search tools do not. | Local and remote (installed in setup steps) — to be verified |
| **c. Hooks: enforcement** | Copilot agents load hooks from `.github/hooks/*.json` in the coding agent and the CLI. A `preToolUse` hook **denies** unbounded commands (raw full test/build runs, `cat` of large files, recursive listings) with a message telling the agent to use `afs-run`. Deny-with-guidance works whether or not a hook can rewrite commands. A `sessionEnd` hook checks that a handoff or a PR exists. | Copilot coding agent, Copilot CLI (Claude Code has equivalent hooks for local use) |
| **d. Context compression proxy: Headroom** (Apache-2.0) | Sits between the agent and the model API, compressing tool outputs and other content, with originals retrievable on demand. Optional, **local only**: the Copilot coding agent's model traffic is hosted by GitHub, so a proxy cannot be inserted there. Lossless modes only for implementers. | Local agents, if evaluation shows a benefit |

### 5. Subagents as context firewalls
Heavy reading or searching (exploring a module, chasing a failure across files) goes to a short-lived
subagent that returns a compact answer. Verifier and Auditor run in fresh contexts.

### 6. Re-anchor
The fidelity contract and the ticket's acceptance criteria are re-read before implementing, before
claiming done (`verification-before-completion`), and after any restart. Ticket bodies open with the
essentials and close by repeating the acceptance checklist.

### 7. Detect and measure
- Warning signs: the same failure twice (existing stop rule), edits outside the ticket's files,
  re-reading the same files, drift from acceptance criteria.
- Per-ticket metrics: tokens, restarts, gate failures, output bytes kept out of context (`afs-run`
  and RTK both report this). Fed back into ticket sizing.

## Consequences
- Full output is never lost: it is on disk and linked as evidence, so gates stay auditable.
- `afs-run` is a small harness tool to build in M2; RTK and Headroom are evaluated in spike M1-d
  before being adopted.
- Budgets and limits are operator-set profile values, tuned during the pilot (M5/M6).
