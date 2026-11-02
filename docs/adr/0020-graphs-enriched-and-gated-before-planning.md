# ADR-0020: Code graphs are enriched deterministically and gated before planning

- Status: Accepted
- Date: 2026-11-02

## Context
The M5 final audit found that neither Track Cargo graph could trace the tracking flow to its data. The
cause is in the graph tool's design. Understand Anything creates `table` nodes only from SQL/migration
files, `endpoint` nodes only from OpenAPI specs and `routes` edges only from infrastructure routing
config, and no rule emits `reads_from`/`writes_to`. ORM entities (JPA, Django models) are plain classes.
It has framework hints for Django and Spring, but none for Java EE/JSF/JAX-RS. Its LLM-chosen `calls`
edges are sparse: 10 across 113 source classes.

The full source graph had been built before slicing, and its `graph-check.md` showed those zeros. But
`check_graph.py` was a findings report, not a gate, and its anchor search followed any edge in any
direction. Even an enriched graph produced meaningless paths that way (`track.xhtml → admin.xhtml ←
dashboard.xhtml → …`).

## Decision
1. **Deterministic enrichers** (`tools/enrich_graph.py`, standard library) run after Understand
   Anything in the afs-understand workflow, on the same folder it analysed. Each enricher adds what
   its stack's code states explicitly. `java-ee` covers JPA, EntityManager reads and writes, JAX-RS,
   JSF pages and EL bean references, Facelets composition, CDI injection, implements, and JMS producer →
   queue → consumer. `django` covers models, ORM reads and writes, `urls.py` (with includes and factory
   views), templates, imports, and calls through annotated parameters and attributes. Every added node and
   edge is tagged `afs-enriched:<rule>`. Re-running is idempotent.
2. **Directed data paths.** `check_graph.py --data-path` follows the flow as the code runs: routes,
   calls, contains, inherits, publishes, triggers, reads_from and writes_to forward, and implements
   backwards (interface → implementation). `TYPE=NAME` anchors match exactly. With `--gate`, a missing
   required type or path exits 1.
3. **The graph gate** (`tools/graph_gate.py`): for one side, the profile's `graph.require` types must be
   present, and every slice's `data_paths` anchors (`.migration/slices/<slice>.yaml`) must reach a table.
   It also lists every page and endpoint without a path, for review.
4. **Where it binds:**
   - **Bootstrap:** the profile must state the stack pack's `graph.enrich` and `graph.require`, or
     bootstrap fails. A stack without an enricher is a `gap` for the "graph data links" capability.
   - **Graph first:** after the setup PR, the full source graph is built and must pass
     `graph_gate.py --side source --require-graph` before analysis or planning (operator checklist,
     Program Orchestrator, Bootstrapper).
   - **Planning:** the Planner writes source and target anchors per slice. CI runs the source gate on
     every PR, so a plan whose anchors don't reach data fails at once.
   - **Acceptance:** CI runs the target gate on a PR that records `verdict: complete`. The Auditor
     runs both gates first and stops if either fails.

## Consequences
- "Does the tracking page reach the data?" has a deterministic, reviewable answer in both codebases.
- Enrichers are code: each new stack needs one, or an explicit gap. The operator docs list what
  Understand Anything extracts alone and what each enricher adds.
- Dynamic dispatch the code doesn't state (unannotated duck typing, reflection, string-built queries) stays
  invisible. The entry-point report shows the effect, and the fix is an enricher rule, not a workaround.
