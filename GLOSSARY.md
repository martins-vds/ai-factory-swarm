# Glossary

**afs-run** — Harness wrapper for gate runs: runs the command through RTK, saves the raw log under
`.migration/runs/` for evidence, and gives the agent only the compact result. See ADR-0015.

**Built-in skill menu** — Language-agnostic skills shipped with the harness and installed into every
target: planning, domain and design, architecture, refactoring, build, review, debugging, research and
the code graph. See ADR-0012.

**Capability** — One thing the source application does that someone could notice: an endpoint, a
screen or flow, a business rule, a side effect, a scheduled job, an integration, a data structure.
The unit of the fidelity ledger.

**Capability gap** — A required capability (e.g. mutation testing for the target stack) with no skill
or tool available. Becomes an operator ticket that blocks migration until resolved.

**Characterization tier** — How behavior is captured, chosen in bootstrap from what is available:
A (running legacy environment), B (source runnable in isolation), C (source only: specs derived from
the code). See ADR-0005.

**Characterization test** — A test that records what the source currently does (inputs → observable
outputs) without judging whether it is correct, then replays those cases against the target.

**CRAP** — Change Risk Anti-Patterns: complexity² × (1 − coverage)³ + complexity, per method. High
values mark code that is both complex and poorly tested. A gate on the target; a risk signal on the
source. See ADR-0011, ADR-0013.

**Cutover** — The single switch of users from the legacy application to the target, after final UAT.

**Data migration workstream** — The slices and tickets that build and test the repeatable pipeline
moving legacy data into the target schema. See ADR-0010.

**Decision map** — The Wayfinder map: one tracker issue (`wayfinder:map`) whose child tickets are
decisions to make (architecture, mappings, data strategy, quirk rulings).

**Differential check** — Sending the same inputs to legacy and target from the same starting data and
comparing normalized outputs. Automated during slice acceptance where feasible.

**Equivalence boundary** — The set of interfaces where behavior is observable (APIs, UI, persisted
data, messages, files, external calls, job effects, errors, authorization). Source and target must
match here; everything behind it may differ. See ADR-0001.

**Evidence ladder** — Ranked kinds of proof that a capability was preserved: differential
observation, characterization tests, transcribed legacy tests, graph capability coverage, review only.

**Fidelity contract** — Preserve observable behavior; re-architect freely behind it; surface every
quirk to a human.

**Fidelity ledger** — The inventory of every source capability with its target counterpart, status,
verification rung, evidence and approvals. One file per capability in `.migration/ledger/`.

**Final UAT** — The last side-by-side period, when test users exercise the whole target next to the
running legacy application before cutover.

**Frontier** — Open, unblocked, unclaimed tickets: the work that can be picked up now.

**Handoff** — A ticket comment an agent writes before ending at its context soft limit: what is done,
what remains, decisions, failing commands with log paths, next step. A fresh agent resumes from it.

**Harness** — This repository: the generic role agents, skills, templates and bootstrap that run a
migration.

**Migration profile** — `.migration/profile.yaml` in the target repo: everything stack-specific for
one migration (stacks, skills, gate commands, thresholds, concurrency, data settings).

**Mutation score** — The share of deliberate small code changes (mutants) that the test suite catches.
Measures test strength. See ADR-0011.

**Quirk** — Source behavior that looks wrong or surprising (a defect, odd edge case, undefined
behavior). Always escalated to a human as a question ticket. See ADR-0007.

**Required-capability checklist** — The capabilities bootstrap must find for the source and target
stacks before migration starts. See ADR-0012.

**Review-only** — Ledger verification status for a capability that could not be characterized; it
needs a human tester's sign-off before cutover.

**Risk map** — A best-effort CRAP ranking of the source that guides characterization, planning and
refactoring. Never blocks. See ADR-0013.

**Spec-derived** — Ledger verification for behavior derived by reading the source (tier C) and encoded
as target tests; weaker than characterization and reviewed by a human.

**Slice** — A vertical, end-to-end path through every layer, anchored on an observable entry point,
that can be tested on its own. Broken into slice tickets sized for one agent session.

**Slice acceptance** — Closing a slice: end-to-end characterization, differential checks, full
mutation run, capability coverage, and a human side-by-side check.

**UI direction** — The Phase 4 decision on the target UI's look: keep the current look, or modernize
it with a chosen design system. What users can do in the UI must match the source either way. See
ADR-0014.

**Source** — The legacy application's repository; read-only, frozen and pinned to a commit SHA.

**Target** — The new application's repository; also holds all migration state and the pinned agents.
