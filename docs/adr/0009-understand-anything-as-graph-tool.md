# ADR-0009: Understand Anything as the single graph tool, used directly

- Status: Accepted
- Date: 2026-10-30
- Supersedes: the earlier draft "third-party graph tool behind an adapter"

## Context
Agents need a graph of the source (and later the target) to inventory capabilities, plan slices,
resolve dependencies and check capability coverage. Two candidates were compared from their source
code (Understand Anything `4e6d329`, Graphify `0a8cd4e`, October 2026):

| | Understand Anything | Graphify |
|---|---|---|
| Build | LLM file-analyzer subagents in batches; tree-sitter for import resolution and symbol coverage | Deterministic tree-sitter; no LLM for code |
| Node types | 27, incl. endpoint, table, service, schema, pipeline, screen, domain, flow, step | Code symbols, plus doc/rationale nodes |
| Edge types | 38, incl. calls, imports, inherits, reads_from, writes_to, publishes, routes, triggers, tested_by | calls, imports, inherits, contains, uses, … with confidence labels |
| Business flows | Domain → flow → step with entry point/type and business rules | None (community clustering) |
| Updates | Incremental via git diff + structural fingerprints | Incremental via file-hash cache |
| Languages | ~40 configs; Spring and Django framework detectors | ~40, incl. COBOL, VB.NET, Delphi/Pascal, Fortran |
| Cost / determinism | LLM tokens; rebuilds can differ | Free; deterministic |

Understand Anything covers the structural core of Graphify and adds the semantic layer a migration
needs. Running both behind an adapter would be expensive to build and maintain.

## Decision
- Use **Understand Anything only**, directly through its commands (`/understand`,
  `/understand-domain`, `/understand-chat`, `/understand-explain`, `/understand-diff`). No adapter.
- Build the source graph and domain graph **once**, on a local checkout of the source at the pinned
  SHA, and commit the snapshot to the target's `.migration/graphs/source/`.
- Update target graphs incrementally per slice into `.migration/graphs/target/`.

### Amendment after spike M1-1 (2026-10-30)
- **Run through the Copilot SDK** in Actions with `GITHUB_TOKEN` and `copilot-requests: write`.
- **Skill patch.** Under Copilot, the main `understand` skill does not load because its `argument-hint`
  frontmatter is a YAML list; the harness pins Understand Anything and rewrites that line as a string
  (to be reported upstream).
- **Enrichment step.** For Java EE the graph carries screens, entities and services as **tags and
  summaries** on `file`/`class` nodes (0 `screen`/`table`/`service` nodes, 2 `calls` edges). The Analyst
  derives ledger kinds from tags and config (`jpa-entity` → data, `view`/`ui` → UI, `service` → service
  boundary, framework config such as JSF managed beans → screen↔bean wiring) and builds screen → bean →
  service → entity chains from imports plus config. The domain graph's flows (with UI entry points) are
  the primary slice anchors.
- **Budget.** The 31-file pilot slice took 61 premium requests and ~5 minutes; whole-codebase cost is
  estimated linearly from file count and approved by the operator before Phase 2.

## Consequences
- The source graph's LLM cost is paid once, and its content does not drift (the source is frozen).
- The ledger and slice plan draw directly on endpoints, screens, tables, flows and `tested_by` edges.
- The graph is the primary interface but not infallible: agents verify against source when graph and
  code disagree, and correct the graph (carried over from PR #6).
- If a source language is not supported (e.g. COBOL, VB6), revisit with Graphify as a **replacement**
  for that migration, never as a second tool.
