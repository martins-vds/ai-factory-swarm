# Glossary

**Capability** — One thing the source application does that someone could notice: an endpoint, a
screen or flow, a business rule, a side effect, a scheduled job, an integration. The unit of the
fidelity ledger.

**Characterization test** — A test that records what the source currently does (inputs → observable
outputs) without judging whether it is correct, then replays those cases against the target.

**Cutover** — The single switch of users from the legacy application to the target. Preceded by the
side-by-side run.

**Decision map** — The Wayfinder map: one tracker issue (`wayfinder:map`) whose child tickets are
decisions to make (architecture, mappings, data strategy, quirk rulings).

**Equivalence boundary** — The set of interfaces where behavior is observable (APIs, UI, persisted
data, messages, files, external calls, job effects, errors, authorization). Source and target must
match here; everything behind it may differ. See ADR-0001.

**Evidence ladder** — The ranked kinds of proof that a capability was preserved: side-by-side
observation, characterization tests, transcribed legacy tests, graph capability coverage, review
only.

**Fidelity contract** — Preserve observable behavior; re-architect freely behind it; surface every
quirk to a human.

**Fidelity ledger** — The inventory of every source capability with its target counterpart, status,
verification rung, evidence and approvals. Stored as one file per capability in `.migration/ledger/`.

**Frontier** — Open, unblocked, unclaimed tickets: the work that can be picked up now.

**Harness** — This repository: the generic role agents, skills, profile templates and bootstrap that
run a migration.

**Migration profile** — `.migration/profile.yaml` in the target repo: everything stack-specific for one
migration (stacks, skills per capability, gate commands, graph tool, translation rules).

**Quirk** — Source behavior that looks wrong or surprising (a defect, odd edge case, undefined
behavior). Always escalated to a human as a question ticket. See ADR-0007.

**Review-only** — Ledger verification status for a capability that could not be characterized; it
needs a human tester's sign-off before cutover.

**Side-by-side run** — The period before cutover when the legacy application and the target run
concurrently, the target on a copy of production data, so test users can verify it.

**Slice** — A vertical, end-to-end path through every layer, anchored on an observable entry point,
that can be tested on its own. Broken into slice tickets sized for one agent session.

**Source** — The legacy application's repository; read-only, frozen and pinned to a commit SHA.

**Target** — The new application's repository; also holds all migration state.
