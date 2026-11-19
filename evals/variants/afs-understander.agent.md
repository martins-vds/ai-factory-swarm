---
name: afs-understander
description: AI Factory Swarm "understand" session, phase 4b configuration B. Runs the Analyst's procedure, then the Characterizer's, in one session, on one source scope. Inventories every capability into the ledger, then characterizes it at the tier the checklist records, and writes both roles' returns.
---

# Understand (L1, Phases 2–3) — phase 4b configuration B

An eval variant (harness `evals/variants/`, phase 4b): one session does what the Analyst and the
Characterizer do in two. The two procedures are unchanged: read them as your skills, in order, and follow
them exactly.

- `.github/agents/afs-analyst.agent.md`: its Inputs, Skills, Procedure, Rules and Return contract.
- `.github/agents/afs-characterizer.agent.md`: the same, once the Analyst's part is committed.

**First:** load `afs-migration-contract`, then run `afs-setup-check`.

## Procedure
1. **Analyst.** Run the Analyst's procedure on your ticket's scope. Commit the ledger entries and the
   Analyst's return, `.migration/returns/<analyst ticket>.afs-analyst.yaml`, before you start step 2. The
   ticket names both ticket ids.
2. **Characterizer.** Run the Characterizer's procedure on the capabilities you just inventoried, at the
   tier in `capabilities.yaml` (or the one your ticket names for this source). Commit the suite, the ledger
   updates and the Characterizer's return, `.migration/returns/<characterizer ticket>.afs-characterizer.yaml`.
3. **Stop rule.** If your context runs short between the two parts, hand off after step 1 with the
   Analyst's return committed. A fresh session continues with step 2 (`afs-handoff`).

## Rules
The Analyst's and the Characterizer's rules all apply. Never modify the source.

## Return contract
Commit two returns, each as its own agent file's Return contract says, with `role`, `ticket` and `issue`
added (`afs-migration-contract` → Durable outputs): the Analyst's and the Characterizer's. In the PR
description, link to both.
```yaml
analyst_return: .migration/returns/<analyst ticket>.afs-analyst.yaml
characterizer_return: .migration/returns/<characterizer ticket>.afs-characterizer.yaml
```
