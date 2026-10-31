# Capability coverage (gate 7) and graph enrichment

With freedom to re-architect, a node-for-node diff of source and target graphs is mostly noise. Gate 7
asks a narrower question: **does every capability in scope have (a) a target counterpart and (b) passing
evidence at the equivalence boundary?**

## Graph enrichment (Analyst, Phase 2)
Understand Anything's graph may carry screens, entities and services as **tags and summaries** on
`file`/`class` nodes rather than as typed nodes, with few `calls` edges (spike M1-1, Java EE). Map them:

| Graph signal | Ledger `kind` / role |
|---|---|
| tags `view`, `ui`, page/template files (`.jsp`, `.jspx`, `.xhtml`, templates) | `ui` (screen) |
| tags `jpa-entity`, `data-model`, table/schema nodes, DDL | `data` |
| tags `service`, `api`, `business-logic` | service boundary (`behavioral`) |
| endpoint/route nodes, controllers, REST resources | `behavioral` entry point |
| scheduled/batch/listener classes, `triggers` edges | `behavioral` (jobs) |
| external clients, queues, `publishes`/`subscribes` edges | `integration` |
| framework wiring (e.g. JSF managed-bean config, DI config) | screen ↔ bean ↔ service chains |

Build screen → bean → service → entity chains from imports plus framework config. The **domain graph's
flows** (with their entry points) are the primary slice anchors; each flow step is a candidate ledger
capability.

## The five gap classes (at the boundary)
1. **Missing capability** — a ledger capability with no target counterpart.
2. **Misplaced responsibility** — counterpart exists but violates target ADRs (logic in a view, etc.).
3. **Broken flow** — an end-to-end path (screen → … → data) that no longer connects.
4. **Missing integration** — an external system or dependency the source used that the target does not.
5. **Untested path** — a counterpart exists but no passing evidence covers it.

## Procedure
1. For each ledger entry in scope: target components present? evidence present and passing?
2. Walk the domain-graph flows end to end on the target (tests or differential runs).
3. Classify every delta: preserved / legitimately transformed / **gap**. Gaps are fixed (new ticket) or
   become a human-approved divergence in the ledger. None is left silent.
