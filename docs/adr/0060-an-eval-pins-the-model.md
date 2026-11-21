# ADR-0060: An eval pins the model its sessions run

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-21
- Source: the phase 5 re-run (`2026-11-21-p5r-r1`)

## Context
`afs-eval dispatch` assigned issues to Copilot without a model, so Copilot's automatic model selection
picked one for each session. The session logs show the choice (`assistant.usage: model=…`):
- **Up to 2026-11-19** every sampled session ran `gpt-6-luna`. That covers the phase-1 baseline and the
  phase 5 eval.
- **From 2026-11-20** sessions were split between `gpt-6-luna` and `mai-code-2-flash`:
  - in the fold eval, about half each;
  - in the phase 5 re-run's first run, 14 of 22 on `gpt-6-luna`.
- Nothing recorded which model ran. A comparison could not tell a harness change from a model change.

One failure shows what it costs. In the re-run's LL-01 session (`mai-code-2-flash`), the agent ran
`git reset --soft` on commits Copilot had already pushed. Copilot's final push was then rejected and
couldn't be rebased, and the session's handoff commit was lost. The row read as "no return".

## Decision
1. **`dispatch` and `chain` name the model** (`--model`), and Copilot's assignment carries it
   (`agent_assignment.model`). Letting Copilot choose takes an explicit `--auto-model`.
2. **`grade` records the model each session ran** from its job logs (`model`, plus `models` with turn
   counts).
3. **`compare` lists the models on each side** and flags a comparison where more than one ran.
4. **The default pin is the baseline's model, `gpt-6-luna`.** A different model is a variant, measured
   like any other.

## Consequences
- Every result from 2026-11-20 on is read per model. The fold eval and the phase 5 re-run are reported
  that way.
- A model's behaviour with the harness becomes something we can measure on purpose, instead of noise.
