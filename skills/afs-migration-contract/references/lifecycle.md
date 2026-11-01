# Lifecycle (summary)

Full design: AI Factory Swarm `docs/architecture.md` §5. Owners in brackets.

| Phase | What | Gate / output |
|---|---|---|
| 0 · Intake [Program Orchestrator] | Source repo + **pinned SHA**, target repo, back-end and front-end stacks, tracker, data stores, snapshot owner | `.migration/source.lock` |
| 1 · Bootstrap [Bootstrapper] | Detect stacks; run the capability checklist; record the characterization tier; build the profile; install pinned agents/skills/tools; scaffold the target | **Human:** resolve capability gaps; merge the setup PR |
| 2 · Understand [Analyst] | Code graph + domain graph of the source (once, committed); graph enrichment; capability inventory → ledger; source CRAP risk map (best effort) | Ledger seeded; risk map |
| 3 · Characterize [Characterizer] | Legacy-test inventory; characterization at the chosen tier; refresh risk map with coverage | Characterization suite; ledger evidence |
| 4 · Chart & plan [Program Orchestrator + Planner] | Decision map (`wayfinder`): architecture, mappings, data strategy, UI direction; vertical slices with blocking edges; design tickets for hot spots | **Human:** approve slice plan → `to-tickets` publishes |
| 5 · Execute [Slice Coordinators → Migrators / Verifiers] | One ticket = one fresh session = one PR, test-first | **Human:** merge each PR |
| 6 · Slice acceptance [Slice Coordinator + Auditor] | End-to-end characterization, differential checks, full mutation run, capability coverage, ledger reconciliation | **Human:** side-by-side check of the slice |
| 7 · Final verification [Auditor] | Bidirectional audit, A–G report | No unresolved gaps |
| 8 · Final UAT & cutover [Program Orchestrator] | Data pipeline on a fresh snapshot; whole-app UAT; review-only sign-offs | **Human:** cutover approval |

Any phase: a quirk → quirk ticket to a human (blocks only dependents); a stop rule → handoff + escalation.

## Work tracking
- **Decision map:** one `wayfinder:map` issue; decision tickets as sub-issues (`wayfinder:<type>`).
- **Slice tickets:** `ready-for-agent` issues under a slice parent, native blocking edges.
- **Frontier:** open, unblocked, unclaimed tickets. **Claim** by assigning before any work — the
  dispatcher (L0 or the operator) does this; assigning the Copilot coding agent is the claim.
- Quirk and capability-gap tickets are decision tickets assigned to a human.
