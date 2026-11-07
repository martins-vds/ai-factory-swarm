# AI Factory Swarm

A fleet of AI agents that rewrites applications from one stack to another — language A → language B,
or A → a newer A — with **high fidelity**, on codebases of any size.

> **Preserve observable behavior. Re-architect freely behind it. Surface every quirk to a human.**

## How it works, in one screen

1. **Bootstrap** — detect the source and target stacks, check that every required capability
   (tests, coverage, CRAP, mutation testing, …) has a skill or tool, and have the operator fill any
   gaps. Install pinned agents and skills into the target repo.
2. **Understand** — build a graph of the source in three layers: Understand Anything (an LLM: domains,
   flows, summaries), Graphify (deterministic parsing: calls, inheritance, interfaces) and the harness's
   framework enrichers (routes, tables, queues, schedules). A gate checks that every slice's entry points
   reach data. Then inventory every capability in a *fidelity ledger*, and rank risky code with a
   best-effort CRAP *risk map*.
3. **Characterize** — record what the source actually does as characterization tests, before any
   migration.
4. **Plan** — chart open decisions on a Wayfinder map; break the work, including data migration, into
   vertical slices with dependency edges. A human approves the slice plan.
5. **Execute** — slice coordinators dispatch migrator and verifier agents (local, or the Copilot
   coding agent), one ticket and one PR at a time. Gates include CRAP and mutation testing. Humans
   merge every PR and answer every quirk.
6. **Accept each slice** — automated differential checks, then a human side-by-side check.
7. **Final verification, UAT and cutover** — full audit, then test users verify the whole target next
   to the legacy app on a copy of production data; a human approves cutover.

## Three repositories

| Repo | Role |
|------|------|
| **This repo (harness)** | Role agents, skills and the built-in skill menu, templates, bootstrap |
| **Source** | Legacy code — read-only, frozen, pinned to a commit |
| **Target** | New code plus all migration state and the pinned agents |

## Documentation

- [Architecture](docs/architecture.md) — the full design
- [Roadmap](docs/roadmap.md) — milestones M0–M7
- [Operator setup](docs/operator-setup.md) — repo settings, what the code graph contains, costs
- [Architecture decision records](docs/adr/)
- [Glossary](GLOSSARY.md)

## Repository layout

| Path | What |
|------|------|
| [`docs/`](docs/) | Architecture, ADRs, roadmap, operator setup, spike findings |
| [`schemas/`](schemas/) | JSON Schemas for a target's `.migration/` state: `profile`, `capabilities`, ledger entries, slice specs, return files |
| [`templates/migration/`](templates/migration/) | Sample state from the pilot (validated in CI); also the pilot's bootstrap input |
| [`templates/target/`](templates/target/), [`templates/rtk/`](templates/rtk/) | What bootstrap writes into a target: instruction block, generated workflows, RTK 1.1.0 block and hook |
| [`examples/`](examples/) | Bootstrap inputs for real pilots (`cargotracker/`: the public M5 pilot) |
| [`stacks/`](stacks/) | Stack packs: pinned stack-specific skills (`java-to-django.json`) |
| [`skills.lock.json`](skills.lock.json) | The pinned built-in skill menu: source, commit, path, license, roles |
| [`skills/`](skills/) | Harness skills (`afs-migration-contract`, `afs-ledger`, `afs-evidence`, `afs-quirk-ticket`, `afs-handoff`, `afs-setup-check`, `afs-data-pipeline`) and vendored `afs-` copies (`afs-implement`, `afs-to-tickets`, `afs-wayfinder`) |
| [`patches/`](patches/) | Patches applied to pinned third-party skills and plugins |
| [`agents/`](agents/) | The ten role agents (`afs-*.agent.md`) |
| [`tools/`](tools/) | Bootstrap, gate wrappers and checks: see [Tools](#tools) |
| [`tests/`](tests/) | Tests for the schemas and tools |

```bash
tools/afs-run --ticket T-12 --name tests -- pytest -q    # gate run: full log kept, summary shown
python tools/validate.py path/to/.migration              # validate a target's migration state
python tools/check_lock.py [--remote]                    # check the pinned skill menu
python tools/vendor_skills.py [--check]                  # refresh / drift-check the afs- copies

# install the harness into a target clone (writes files; review, then open the setup PR).
# Then do the operator checklist in docs/operator-setup.md: repo settings bootstrap can't make.
python tools/bootstrap.py --target ../target-repo --profile profile.yaml --capabilities capabilities.yaml \
  --stack-pack stacks/java-to-django.json --create-gap-issues
```

Bootstrap serializes writes to a target with `.afs-bootstrap.lock` at the target root; a competing run
exits with status 2 and reports the owning PID. If a process is killed, first confirm that PID is no longer
running, then use the exact `rm -f -- .../.afs-bootstrap.lock` command printed by bootstrap and rerun it.
Bootstrap stages and validates the install before publishing. Publication swaps several managed paths
individually, not as one filesystem-atomic transaction: failures during publication roll back, and a later
run recovers an interrupted publication from its journal. Treat the target as unavailable until that
recovery run completes.
Nested symlinks in preserved team-owned directory trees are copied as symlinks, including dangling
links; their referents are not traversed. Staging requires the target filesystem and process permissions
to support creating symlinks. If that is unavailable, bootstrap fails before publishing and leaves live
managed paths intact.

## Tools

Every file in [`tools/`](tools/) is listed here (`tests/test_docs.py` checks it).

**Install and drift**

- `bootstrap.py`: install the harness into a target; writes the generated workflows
- `check_installed.py`: installed harness files are unchanged
- `check_lock.py`: the pinned skill menu
- `vendor_skills.py`: refresh or drift-check the `afs-` skill copies
- `gen_return_schema.py`: build `return.schema.json` from the agents' return contracts

**Gates (results come from the tools, ADR-0017)**

- `afs-run`: run a gate once, keep the full log, show a summary
- `afs-mutation`: mutation testing on changed code
- `crap.py`: CRAP from complexity and coverage
- `afs-services`: start and check the test services from the compose file
- `check_runtime.py`: runtimes match the profile
- `afs-acceptance`: run the acceptance gates outside an agent session
- `afs_trace.py`: every tool prints `AFS-TOOL <tool> exit=<code>` when it ends

**Code graph**

- `understand.py`: Understand Anything through the Copilot SDK
- `enrich_graph.py`: merge Graphify's language layer, then add framework meaning
- `graph_gate.py`: required node/edge types; every slice anchor reaches data; every entry point owned
- `check_graph.py`: what a graph contains, for review
- `check_graph_fresh.py`: graphs describe the code they claim to
- `preserve_graph.py`: the source graph only grows; a regeneration keeps earlier flows, and CI fails a PR that loses one
- `check_domain_coverage.py`: requested entry points have a connected domain flow
- `extract_slice.py`: cut a slice of the source for a targeted graph run

**Contracts and tracking**

- `validate.py`: validate a target's `.migration/` state
- `check_plan.py`: plan tickets are dispatch-ready: new ids, complete file lists, no shared file without a blocking edge (run by `validate.py`)
- `check_inputs.py`: every path a ticket names exists
- `check_return_contract.py`: an agent PR commits its return file
- `check_slice_returns.py`: a slice epic closes only with every return file
- `check_signoff.py`: a slice's human sign-off is an approver's review on the exact head commit
- `ticket_guard.py`: reopen a ticket closed before its work reached the default branch
- `check_stack_base.py`: a stacked PR's base contains the default branch
- `fog_rewalk.py`: re-walk the decision map's fog after a slice

**Costs and coverage**

- `afs-cost-hook`: Copilot hook: one cost record per agent session
- `afs-costs`: billed credits and Actions minutes per session
- `harness_coverage.py`: which harness paths a target has exercised
- `data_snapshot.py`: make a snapshot over JDBC (`java/JdbcSnapshot.java`), describe one, or fetch the newest (ADR-0032)
- `data_reconcile.py`: check a data snapshot, and reconcile it with the target's loaded data (ADR-0032)
- `afs-drill`: break one thing on a throwaway branch and confirm the right check catches it
- `drills.json`: the drills `afs-drill` runs (data: operations, trigger, expected check)

## Status

M0–M5 are done: design, spikes, harness skeleton, role agents, bootstrap, and the first pilot slices of
[Cargo Tracker](https://github.com/martins-vds/ai-factory-pilot-target) (track cargo, handling-event
registration) through acceptance. The pilot is now used to **validate the harness itself**: what it has
exercised is computed by `harness_coverage.py` (ADR-0027), and the open paths are listed on the
[roadmap](docs/roadmap.md#harness-validation). M6 (scale test) is next.

Planning and execution build on [Matt Pocock's skills](https://github.com/mattpocock/skills). The code
graph comes from [Understand Anything](https://github.com/Egonex-AI/Understand-Anything) and
[Graphify](https://github.com/Graphify-Labs/graphify), with the harness's own framework enrichers on top.
The baseline was the Java → Django migration skill and role agents in
[code-migration-hackathon PR #6](https://github.com/martins-vds/code-migration-hackathon/pull/6).
