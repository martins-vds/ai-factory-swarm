# ADR-0015: Context budget and tool-output hygiene

- Status: Accepted (Copilot coding agent hook behavior to be confirmed by spike M1-d)
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
Enforced in three layers, from deterministic to enforcing:

| Layer | What | Where it works |
|-------|------|----------------|
| **a. `afs-run` wrapper** (harness tool) | Thin wrapper every agent uses to run commands. Routes through RTK (layer b) when it has a filter for the command, else through `rtk test` / `rtk err`; points RTK's full-output store at `.migration/runs/<ticket>/` (gitignored) so the raw log is a file that gate evidence can link to; prints the compact result plus the log path. | Everywhere (local and remote), any language |
| **b. Filter engine: RTK** ([rtk-ai/rtk](https://github.com/rtk-ai/rtk)) | Single-binary CLI proxy with compact filters for 100+ commands. **Maven and Gradle are supported** (`rtk mvn`, `./mvnw`, `mvnd`, `rtk gradlew`/`gradle`): Surefire/Failsafe passing blocks are dropped and only failing tests are kept with framework stack frames stripped; the project's own fixtures assert ≥90% savings for `mvn test` and ≥85% for `mvn install`. Raw output stays recoverable (`[full output: rtk recall <hash>]`, or files in tee mode). Only shell commands go through it; built-in file read/search tools do not. | Local and remote (binary installed in setup steps) |
| **c. Hooks: enforcement** | Copilot agents load hooks from `.github/hooks/*.json` (coding agent and CLI). `rtk init --copilot` writes `.github/hooks/rtk-rewrite.json`, a `preToolUse` hook that **rewrites** commands transparently in VS Code and **denies with a suggested `rtk` command** in the Copilot CLI (whose hook API cannot rewrite). The harness adds its own `preToolUse` rules that deny unbounded commands (raw full test/build runs, `cat` of large files, recursive listings) with guidance to use `afs-run`, and a `sessionEnd` hook that checks a handoff or PR exists. Deny-with-guidance works whether or not rewriting is available. | Copilot CLI, VS Code, Copilot coding agent (to be confirmed: RTK documents VS Code and the CLI only) |

**RTK facts** (verified from source at `6c2313a`, v0.49.0, 2026-10-30):
- License: the CLI crate is Apache-2.0, but the default build links `rtk-engine`, which is BUSL-1.1
  with a grant allowing free production use; it does not allow offering it to third parties as a paid
  or hosted product. If AI Factory Swarm is ever offered as a hosted service, build RTK with
  `--no-default-features` (the Apache-2.0 hook core) or get a license.
- RTK also installs `.github/copilot-instructions.md` guidance telling agents to prefix commands with
  `rtk`; the harness merges that into its own instructions instead of letting it overwrite them.
- Context compression proxies (e.g. Headroom) are **out of scope** for this project.

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
- Per-ticket metrics: tokens, restarts, gate failures, output bytes kept out of context (`rtk gain`
  reports this). Fed back into ticket sizing.

## Consequences
- Full output is never lost: it is on disk and linked as evidence, so gates stay auditable.
- `afs-run` is a thin harness tool over RTK, built in M2; spike M1-d measures RTK on pilot output and
  confirms hook behavior in the Copilot coding agent.
- Budgets and limits are operator-set profile values, tuned during the pilot (M5/M6).
