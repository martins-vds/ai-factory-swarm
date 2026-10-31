# AI Factory Swarm

A fleet of AI agents that rewrites applications from one stack to another — language A → language B,
or A → a newer A — with **high fidelity**, on codebases of any size.

> **Preserve observable behavior. Re-architect freely behind it. Surface every quirk to a human.**

## How it works, in one screen

1. **Bootstrap** — detect the source and target stacks, check that every required capability
   (tests, coverage, CRAP, mutation testing, …) has a skill or tool, and have the operator fill any
   gaps. Install pinned agents and skills into the target repo.
2. **Understand** — build a graph of the source with Understand Anything, inventory every capability
   in a *fidelity ledger*, and rank risky code with a best-effort CRAP *risk map*.
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
- [Architecture decision records](docs/adr/)
- [Glossary](GLOSSARY.md)

## Repository layout

| Path | What |
|------|------|
| [`docs/`](docs/) | Architecture, ADRs, roadmap, spike findings |
| [`schemas/`](schemas/) | JSON Schemas for a target's `.migration/` state: `profile`, `capabilities`, ledger entries |
| [`templates/migration/`](templates/migration/) | Sample state from the pilot (validated in CI); also the pilot's bootstrap input |
| [`templates/target/`](templates/target/), [`templates/rtk/`](templates/rtk/) | What bootstrap writes into a target: instruction block, generated workflows, RTK 1.1.0 block and hook |
| [`examples/`](examples/) | Bootstrap inputs for real pilots (`cargotracker/`: the public M5 pilot) |
| [`stacks/`](stacks/) | Stack packs: pinned stack-specific skills (`java-to-django.json`) |
| [`skills.lock.json`](skills.lock.json) | The pinned built-in skill menu: source, commit, path, license, roles |
| [`skills/`](skills/) | Harness skills (`afs-migration-contract`, `afs-ledger`, `afs-evidence`, `afs-quirk-ticket`, `afs-handoff`, `afs-setup-check`) and vendored `afs-` copies |
| [`patches/`](patches/) | Patches applied to pinned third-party skills and plugins |
| [`agents/`](agents/) | The ten role agents (`afs-*.agent.md`) |
| [`tools/`](tools/) | `bootstrap.py`, `afs-run` (gate wrapper), `validate.py`, `crap.py`, `check_installed.py`, `check_lock.py`, `vendor_skills.py`, spike tools |
| [`tests/`](tests/) | Tests for the schemas and tools |

```bash
tools/afs-run --ticket T-12 --name tests -- pytest -q    # gate run: full log kept, summary shown
python tools/validate.py path/to/.migration              # validate a target's migration state
python tools/check_lock.py [--remote]                    # check the pinned skill menu
python tools/vendor_skills.py [--check]                  # refresh / drift-check the afs- copies

# install the harness into a target clone (writes files; review, then open the setup PR)
python tools/bootstrap.py --target ../target-repo --profile profile.yaml --capabilities capabilities.yaml \
  --stack-pack stacks/java-to-django.json --create-gap-issues
```

## Status

M0–M4 are done (design, spikes, harness skeleton, role agents, bootstrap); M5 (pilot slice) is next — see the
[roadmap](docs/roadmap.md) and [spike findings](docs/spikes/m1/findings.md). The baseline is the
Java → Django migration skill and role agents in
[code-migration-hackathon PR #6](https://github.com/martins-vds/code-migration-hackathon/pull/6).
Planning and execution build on [Matt Pocock's skills](https://github.com/mattpocock/skills); the code
graph comes from [Understand Anything](https://github.com/Egonex-AI/Understand-Anything).
