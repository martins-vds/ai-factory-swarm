# ADR-0012: Built-in skill menu, required-capability checklist, operator-resolved gaps

- Status: Accepted
- Date: 2026-10-30

## Context
PR #6 hard-coded a list of Java/Django/Oracle skills. A general harness needs (a) language-agnostic
skills every migration uses and (b) a way to find stack-specific skills. Some capabilities, such as
CRAP analysis or mutation testing for a less common language, may have no available skill at all.

## Decision
- The harness ships a **built-in skill menu** of language-agnostic skills, installed into every target
  and pinned: planning and tracking, domain and design, architecture principles, **refactoring**,
  build, review and debugging, research, and the code graph (architecture §6.1). Refactoring skills
  (Fowler refactoring, design patterns, clean code, working effectively with legacy code) are part of
  the menu, alongside `improve-codebase-architecture`, `codebase-design` and `domain-modeling`.
- The menu also takes the language-agnostic skills from the code-migration-hackathon skill set
  (architecture, verification, review, orchestration, containers, browser E2E, documentation,
  lessons learned, skill discovery and creation). Skills that compete with the spine, duplicate a menu
  skill, or are language-specific are excluded; the full list and reasons are in architecture §6.1.
- Only skills whose licenses allow redistribution are vendored into target repos. Proprietary skills
  (e.g. Anthropic's `pdf`, `docx`, `xlsx`) are used only where the agent platform already provides them.
- Bootstrap runs a **required-capability checklist** (architecture §6.2) for the source and target
  stacks: build/run, characterization harness, tests, coverage, complexity, CRAP, mutation testing,
  lint/format, stack idioms, data migration, UI end-to-end.
- Each capability is met from the menu, then via `find-skills`. **An unmet capability is an operator
  ticket that blocks Phase 2.** The operator finds a skill, writes one (e.g. with `skill-creator`),
  or records an approved waiver. Bootstrap is deliberately not fully automated.
- Results are recorded in the target's `.migration/capabilities.yaml`.

## Consequences
- Agents never improvise a missing capability mid-migration.
- Skills the operator writes for a gap can be contributed back to the harness menu or a stack pack.
- Third-party menu skills are evaluated before pinning (roadmap M2).
