# ADR-0003: Matt Pocock's skills as the planning and execution spine

- Status: Accepted
- Date: 2026-10-30

## Context
The PR #6 repository mixes three overlapping planning/execution frameworks: Spec Kit, Superpowers
(`writing-plans`, `subagent-driven-development`, …) and assorted skills. Overlap makes agents
inconsistent about which process to follow.

[`mattpocock/skills`](https://github.com/mattpocock/skills) (MIT) covers the spine we need:
`wayfinder`, `to-tickets`, `to-spec`, `implement`, `tdd`, `domain-modeling`, `codebase-design`,
`improve-codebase-architecture`, `diagnosing-bugs`, `research`, `code-review`, `pr`, and
`setup-matt-pocock-skills` (tracker + domain-doc configuration for any programmable tracker).

Several of these (`wayfinder`, `to-tickets`, `to-spec`, `implement`, `implement-spec`,
`grill-with-docs`, `improve-codebase-architecture`, `triage`, `setup-matt-pocock-skills`) are marked
`disable-model-invocation: true`: only a human can start them. Remote agents have no human to type a
slash command.

## Decision
- Use Matt Pocock's skills as the spine. Other skills enter only through the built-in skill menu
  (ADR-0012) or the migration profile.
- **L0 (Program Orchestrator):** user-invoked skills stay human-triggered. The operator is present,
  and charting a Wayfinder map is a human interview by design.
- **L1 / L2 (coordinators and workers):** the harness vendors adapted copies of the skills they must
  run unattended (e.g. `to-tickets`, `implement`, `tdd`, Wayfinder's "work through the map" mode),
  with `disable-model-invocation` removed, an `afs-` prefix (e.g. `afs-to-tickets`), upstream commit
  pinned, and MIT attribution.

## Consequences
- Domain language lives in `GLOSSARY.md` and decisions in `docs/adr/` of the target repo, the layout
  these skills expect.
- Vendored copies must be re-synced deliberately when upstream changes; harness release notes record
  each upgrade.
- The prefix keeps vendored and upstream skills from being confused when both are installed.
