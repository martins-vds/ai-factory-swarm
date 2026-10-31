---
name: afs-migration-contract
description: The binding rules for every AI Factory Swarm role agent during a high-fidelity migration — the fidelity contract, operating principles, stop rules and red flags. Load this first in every migration task, before any other skill.
---

# AI Factory Swarm — migration contract

> **Preserve observable behavior. Re-architect freely behind it. Surface every quirk to a human.**

Every role agent works under this contract. Role-specific procedure lives in your agent file; the
references below hold detail — read one only when your procedure points to it.

## The fidelity contract
- **Observable behavior** (API requests/responses, UI screens, fields, flows, validations and states,
  persisted data, messages, files, external calls, scheduled-job effects, errors, authorization) must
  match the source. Behind that boundary the target is idiomatic for its stack (DDD, clean
  architecture, DI, clean code). Structural similarity to the source is not a goal.
- **UI:** what users can *do* must match; how it *looks* follows the UI direction decided on the map.
- **Quirks and bugs** found in the source are never silently kept and never silently fixed: raise a
  quirk ticket the moment you find one (`afs-quirk-ticket`).
- **Lose nothing silently.** Every capability is migrated or recorded as deferred / replaced / dropped
  with a human approval, in the fidelity ledger (`afs-ledger`).

## Operating principles
1. **Orchestrate, never reimplement.** If a skill covers it, load and follow the skill.
2. **Understand → plan → approval → build.** Never write target code before the slice plan is approved.
3. **Graph first.** Query the code graph before opening files. Read source only when the graph cannot
   answer, read the minimum (line ranges), and say why. If code contradicts the graph, trust the code,
   flag the discrepancy, and get the graph corrected.
4. **The source is read-only.** Never modify it, never commit any of it to the target.
5. **Evidence over optimism.** A gate passes only on fresh output from `afs-run` in this session
   (`afs-evidence`). "Should pass" is not evidence.
6. **No hidden state.** New work, reorderings, deferrals and decisions go to the tracker or ledger the
   moment they happen. Another agent must be able to continue from the ticket alone.
7. **Stay in scope.** Do exactly your ticket. Record anything else you find as a new ticket.
8. **Follow the requested approach; never assume limits.** Do not sample, skip, batch or approximate to
   save effort. If a real limit blocks you (quota, tool cap, context), stop and say so with specifics.
9. **Keep context small.** Load only the skills your agent file lists. Run commands through `rtk` (or
   `afs-run` for gates); never paste large outputs. At the context soft limit, hand off (`afs-handoff`).
10. **Learn.** Recall relevant lessons before starting; record a lesson when something surprises you
    (`lessons-learned`).

## Stop and escalate
Stop, write a handoff, and escalate (do not keep trying) when:
- the same failure repeats after **two** honest attempts;
- setup is wrong — source missing, wrong SHA, writable, or tools missing (`afs-setup-check`);
- the graph and the code disagree on something your work depends on;
- a real limit blocks the requested approach;
- the ticket asks for something outside the contract or the approved plan.

## Red flags
| Thought | Reality |
|---|---|
| "I'll translate the file quickly" | Understand the capability first; the boundary is what matters. |
| "This quirk is obviously a bug, I'll fix it" | Raise a quirk ticket. A human decides. |
| "It's a minor feature / edge case, skip it" | Every capability is in the ledger, migrated or approved-deferred. |
| "Tests should pass" | Run the gate with `afs-run`. Evidence or it didn't happen. |
| "I'll update the ledger later" | Update it now, in the same PR as the code. |
| "It's easier to read the whole file" | Graph first; then the minimum lines. |
| "The output is long, I'll paste it" | Use `rtk` / `afs-run`; quote only what matters plus the log path. |
| "Close enough to the old UI" | Functional fidelity is mandatory; only the visual direction is free. |
| "I'll mock it, the real one is hard" | Characterize against the real behavior at the best available tier. |
| "I'll fix that other thing while I'm here" | Out of scope: open a ticket. |

## References (read on demand)
- [lifecycle.md](references/lifecycle.md) — phases 0–8, who owns what, human gates.
- [gates.md](references/gates.md) — the seven gates, per-PR and slice acceptance, project acceptance.
- [characterization.md](references/characterization.md) — tiers A/B/C and the tier-B recipe.
- [capability-coverage.md](references/capability-coverage.md) — gate 7 and graph enrichment.
- [final-verification.md](references/final-verification.md) — the final audit and its A–G report.
