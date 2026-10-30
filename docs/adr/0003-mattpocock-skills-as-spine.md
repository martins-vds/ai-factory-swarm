# ADR-0003: Matt Pocock's skills as the planning and execution spine

- Status: Accepted (trial)
- Date: 2026-10-30

## Context
The PR #6 repository mixes three overlapping planning/execution frameworks: Spec Kit, Superpowers
(`writing-plans`, `subagent-driven-development`, …) and assorted skills. Overlap makes agents
inconsistent about which process to follow.

[`mattpocock/skills`](https://github.com/mattpocock/skills) (MIT) covers the spine we need:
`wayfinder` (decision maps on the issue tracker), `to-tickets` (vertical slices with blocking
edges), `to-spec`, `implement`, `tdd`, `domain-modeling`, `codebase-design`,
`improve-codebase-architecture`, `diagnosing-bugs`, `research`, `code-review`, `pr`, and
`setup-matt-pocock-skills` (tracker + domain-doc configuration that works with any programmable
tracker).

## Decision
Use Matt Pocock's skills as the spine. Stack-specific and specialist skills (e.g. Django, Oracle →
PostgreSQL, browser testing) are added only through the migration profile.

## Consequences
- Domain language lives in `GLOSSARY.md` and decisions in `docs/adr/` of the target repo, the layout
  these skills expect.
- **Invocation constraint:** `wayfinder`, `to-tickets`, `to-spec`, `implement`, `implement-spec`,
  `grill-with-docs`, `improve-codebase-architecture`, `triage` and `setup-matt-pocock-skills` are
  marked `disable-model-invocation: true` (user-invoked only). Either a human triggers these at the
  L0 level, or the harness vendors adapted copies with attribution (MIT permits this). To decide
  before the role agents are written.
- Skills are pinned to a commit so behavior does not shift mid-migration.
