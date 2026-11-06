# Roadmap

Delivery plan for the harness described in [architecture.md](architecture.md). M0–M4 used the Java
application in [code-migration-hackathon](https://github.com/martins-vds/code-migration-hackathon)
(private). From M5 the pilot is public: [Eclipse Cargo Tracker](https://github.com/eclipse-ee4j/cargotracker)
(`javaee7` branch, Java EE 7, MIT) → Python/Django, with inputs in
[`examples/cargotracker/`](../examples/cargotracker/). The first M5 run on the private pilot is summarized
in its findings: quirks never block inventory; remote workers need the quirk-file fallback.
M5 also hardened the harness: ADRs 0016–0030 record what the pilot slices exposed.

| Milestone | Scope | Done when |
|-----------|-------|-----------|
| **M0 · Design** | Architecture, ADRs 0001–0015, glossary, this roadmap | Merged to `main` ✅ |
| **M1 · Spikes** | (a) Run Understand Anything (`/understand`, `/understand-domain`) on the pilot source; confirm the node/edge types the ledger needs appear (endpoints, screens, tables, flows, `tested_by`) and measure time and cost. (b) Assign a test issue to the Copilot coding agent with a custom agent and a read-only source checkout in setup steps. (c) Run CRAP and PIT mutation testing on the pilot source and a Python target stub. (d) Output hygiene: run RTK on the pilot's Maven/pytest output and confirm how its Copilot `preToolUse` hook behaves in the Copilot coding agent (rewrite or deny-with-suggestion). | Done: [findings](spikes/m1/findings.md) (spikes 1–5) ✅ |
| **M2 · Harness skeleton** | Repo layout; the `afs-run` gate wrapper; JSON Schemas for `profile.yaml`, `capabilities.yaml` and ledger entries; evaluate and pin the built-in skill menu (mattpocock/skills, hackathon-sourced skills, ciembor/agent-rules-books candidates), confirm each license allows redistribution, and resolve overlaps (e.g. `architecture-patterns` vs ciembor's architecture rules); vendor `afs-` copies of user-invoked skills | Schemas validate samples in CI; menu pinned in `skills.lock.json`; vendored copies drift-checked ✅ |
| **M3 · Role agents** | The ten role agents as `.agent.md` files, generalized from PR #6, plus harness skills (migration contract, ledger/evidence writers, quirk ticket, lessons learned) | All ten agents with return contracts; skill lists enforced against `skills.lock.json` by `tests/test_agents.py` ✅ |
| **M4 · Bootstrap + reference profile** | Bootstrap with the capability checklist and gap tickets; Java → Django reference profile reusing PR #6's stack skills | Done: `tools/bootstrap.py` + `stacks/java-to-django.json`; pilot [setup PR](https://github.com/martins-vds/ai-factory-pilot-target/pull/6) with the data-migration gap as [#5](https://github.com/martins-vds/ai-factory-pilot-target/issues/5) ✅ |
| **M5 · Pilot slice** | One vertical slice of the pilot app through every phase: graph, risk map, characterization, plan, execute, acceptance (all gates + differential check + human side-by-side check) | Done: two slices accepted on the [pilot](https://github.com/martins-vds/ai-factory-pilot-target). Track Cargo ([#9](https://github.com/martins-vds/ai-factory-pilot-target/issues/9), [report](https://github.com/martins-vds/ai-factory-pilot-target/blob/main/.migration/evidence/track-cargo/report.md)) and handling-event registration ([#113](https://github.com/martins-vds/ai-factory-pilot-target/issues/113), [report](https://github.com/martins-vds/ai-factory-pilot-target/blob/main/.migration/evidence/handling-registration/acceptance.md)), with a messaging hop (JMS → PostgreSQL attempts + worker) ✅ |
| **M6 · Scale test** | Several slices in parallel, local and remote workers mixed, including a data-migration slice | No ledger conflicts; a killed worker is resumed from its ticket alone |
| **M7 · Second language pair** | e.g. C# → Python or .NET Framework → .NET 8 | Pilot slice green with **no changes to role agents**; only a new profile and stack skills |

## Order and dependencies

```mermaid
flowchart LR
  M0 --> M1 --> M2 --> M3 --> M4 --> M5 --> M6 --> M7
  M1 -. findings .-> M2
```

M1 is deliberately first: its three spikes test the assumptions the rest of the design depends on
(the graph's content, remote dispatch, and CRAP/mutation tooling).

## Harness validation

The pilot's main job after M5 is to exercise every harness path, so that a gap shows up on the pilot and
not on a real migration. The list of paths is **computed, not kept here** (ADR-0027):

```bash
python .migration/harness/tools/harness_coverage.py --repo <owner>/<target> --out .migration/coverage.md
```

A path counts once it was seen both passing and failing. Snapshot on the pilot, 2026-11-06: **62 of 95**.
The 33 open paths fall into four groups, and each needs a different kind of work:

| Group | Open paths | How they get exercised |
|-------|-----------|------------------------|
| Tools only ever seen passing | `afs-cost-hook`, `afs-costs`, `afs-services`, `check_*`, `enrich_graph.py`, `extract_slice.py`, `fog_rewalk.py`, `understand.py` | Deliberate negative tests on the pilot: a PR that should fail each check, opened and closed |
| Return-file values no slice produced | Auditor `gaps.class: misplaced`; Bootstrapper `characterization_tier: B`/`C`; Orchestrator `dispatched.status: blocked`; Coordinator `human_check: requested`/`issues`; Specialist `specialty: ui` | The admin live-map slice (#202: UI specialist, human check with findings); a blocked dispatch |
| Ledger values no slice produced | `status: in-progress`/`deferred`; `verification: legacy-test`/`spec-derived`/`review-only`; tier `C` | A deferred capability; an entry verified from legacy tests or a spec |
| Workflows only seen succeeding; `wayfinder:prototype` label | `afs-acceptance.yml`, `afs-costs.yml`, `afs-ticket-guard.yml`, `copilot-setup-steps.yml` | Negative runs; a decision resolved by a prototype |

Paths the coverage tool can't see yet, and that belong to later milestones:
- **M6:** several slices in parallel; local and remote workers mixed (every pilot ticket so far ran on the
  Copilot coding agent); a data-migration slice (ADR-0010); a killed worker resumed from its ticket alone
  (restarts from a handoff were exercised: HR-04C, HR-04D).
- **Phases 7–8:** final verification, UAT and cutover (ADR-0006).
- **Azure DevOps** as the tracker (ADR-0004); everything so far used GitHub issues.
