# ADR-0025: Graphify is the language layer under the framework enrichers

- Status: Accepted
- Date: 2026-11-03
- Amends: ADR-0009
- Spike: #38 (findings and numbers on the issue)

## Context
The enrichers (ADR-0020, ADR-0023) encoded two kinds of knowledge. **Framework** knowledge is what a
framework's conventions mean (`@Path` is a route, `Model.objects` reads a table), and no parser can infer
it. **Language** knowledge is calls, inheritance and interfaces, which the enrichers resolved with
hand-written Java regexes and Python AST code. The second kind had to be re-implemented for every
language, so each new stack cost a call resolver as well as its framework rules.

Graphify parses about 40 languages with tree-sitter, offline and without an LLM, and tags each link
`EXTRACTED` or `INFERRED`. On the pilot (spike #38):
- It reproduced **all** of our language-level edges, 55 of 55 in Java and 61 of 61 in Python, each in
  the same direction.
- It added 241 correct Java calls we lacked (a sample of 10 was checked against the code).
- Two runs gave byte-identical output, in about 2 seconds.

## Decision
1. **Two layers.**
   - Graphify supplies the language layer: `enrich_graph.py --graphify graph.json` merges its `calls`,
     `uses`, `implements` and `inherits` links, between top-level types and functions, first.
   - The stack enrichers then add only framework meaning.
   - The hand-written language rules (`java-implements`, `java-extends`, `python-call`,
     `python-typed-call`, `python-class`) are deleted.
2. **The merge is language-agnostic.** A method counts as its type through Graphify's own `method` and
   `contains` links. Nodes are matched to existing ones by (file, name).
   - `uses` (instantiation, or a typed parameter, which is how Python code wires dependencies) merges as
     `calls`.
   - `references` (a type is merely mentioned) does not merge: it is not flow.
   - An `inherits` into a class built on `Protocol`/`ABC` becomes `implements`, so interfaces still lead
     to their implementations.
   - Every edge's description keeps Graphify's relation and confidence, so `INFERRED` stays visible.
3. **Dependency injection is framework knowledge.** `@Inject`/`@EJB` fields stay a `java-ee` rule
   (`cdi-inject`): injection wires a dependency even where no call is visible.
4. **Data is reached by reading or writing it.** The data-path gate no longer steps through
   `defines_schema`. With Graphify's richer calls, "calls an entity's method → the entity's table"
   produced false paths, e.g. a WebSocket pusher "reaching data". On the pilot, the old and new
   enrichment now give identical results: 20 of 29 source and 3 of 8 target entry points reach data,
   and every slice anchor reaches it through a repository read.
5. **Pinned like Understand Anything.**
   - Every package is hash-pinned in `tools/locks/graphify.lock` (Linux, Python 3.12 wheels), and the
     graph workflow installs it with `--require-hashes` in its own venv.
   - The merge refuses a `schema_version` it doesn't know, so an upgrade can't silently change graphs.
   - The graph records the Graphify version in `project.afsEnrichment.graphify`.

## Consequences
- Adding a stack costs its framework rules and their fixtures, not a call resolver.
- The test fixtures carry Graphify's output (`tests/fixtures/graph/*.graphify.json`), so tests run offline.
- **Upgrading Graphify:**
  1. Regenerate the lock (download the version with `pip download`, then `sha256` each wheel).
  2. Regenerate the fixture outputs (`graphify extract . --code-only` in each fixture folder).
  3. Add the new `schema_version` to `GRAPHIFY_SCHEMAS` only after reading its changes.
  4. Re-run the old-versus-new comparison on a pilot.
- The graph workflow fails if Graphify fails: a graph without its language layer would quietly lose paths.
