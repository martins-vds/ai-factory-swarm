# AI Factory Swarm

A fleet of AI agents that rewrites applications from one stack to another — language A → language B,
or A → a newer A — with **high fidelity**, on codebases of any size.

> **Preserve observable behavior. Re-architect freely behind it. Surface every quirk to a human.**

## How it works, in one screen

1. **Bootstrap** — detect the source and target stacks and resolve the skills each role needs into a
   *migration profile*.
2. **Understand** — build a graph of the source with a third-party graph tool and inventory every
   capability in a *fidelity ledger*.
3. **Characterize** — record what the source actually does as characterization tests, before any
   migration.
4. **Plan** — chart open decisions on a Wayfinder map; break the work into vertical slices with
   dependency edges. A human approves the slice plan.
5. **Execute** — slice coordinators dispatch migrator and verifier agents (local or remote), one
   ticket and one PR at a time. Humans merge every PR and answer every quirk.
6. **Verify** — per-slice capability coverage, then a full bidirectional audit.
7. **Side-by-side and cutover** — the new app runs next to the legacy app on a copy of production
   data; test users verify it; a human approves cutover.

## Three repositories

| Repo | Role |
|------|------|
| **This repo (harness)** | Role agents, skills, profile templates, bootstrap |
| **Source** | Legacy code — read-only, frozen, pinned to a commit |
| **Target** | New code plus all migration state (profile, ledger, graphs, evidence, tickets) |

## Documentation

- [Architecture](docs/architecture.md) — the full design
- [Architecture decision records](docs/adr/)
- [Glossary](GLOSSARY.md)

## Status

Design phase (draft v0.1). The baseline is the Java → Django migration skill and role agents in
[code-migration-hackathon PR #6](https://github.com/martins-vds/code-migration-hackathon/pull/6);
this repo generalizes that work. Planning and execution build on
[Matt Pocock's skills](https://github.com/mattpocock/skills).
