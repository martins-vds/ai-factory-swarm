# Data-migration re-run (DM-05D, DM-05F), 2026-11-22

Runs `2026-11-22-dm-r{1,2,3}`. Harness `80b353f` (the test-trust plan complete), model `gpt-6-luna`,
`--role-map afs-specialist-migrator=afs-migrator`. These are the two cases the phase 5 re-run couldn't measure:
the Copilot setup's data snapshot fetch was rate-limited.

| Case | r1 | r2 | r3 | Passed | Minutes |
|---|---|---|---|---|---|
| pilot-dm-05d (export a data snapshot) | ✅ | ✅ | ✅ | **3/3** | 32, 17, 35 |
| pilot-dm-05f (business invariants on loaded data) | ✅ | ❌ | ❌ | **1/3** | 9, 9, 9 |

- **The snapshot fetch got through.** It succeeded in every session that reached the step. The rate limit has
  cleared.
- **DM-05D needed a case fix** (harness #249). Its base predates the pilot's layering contracts, and ADR-0066
  now requires them. It now normalizes today's layering, idiom gate and UI checks, as DM-05F always has from
  the same base.
- **DM-05F r2 and r3 failed CI the same way.** The new invariant tests load the data snapshot from
  `.migration/data/snapshot/`, but CI has no snapshot (`no manifest.json`): production data is never committed,
  and only Copilot's setup fetches it. In the session the snapshot was there, so every local gate passed. r1
  passed because its tests copied a committed fixture snapshot (`tests/data_migration/fixtures/DM-05C`) into
  a temporary folder.
- **This is a harness gap, not a model one.** The session can't see the difference between its environment
  and CI's. A fix makes the finish check run the branch's changed tests with the snapshot hidden, as CI does,
  and send the session back when they need it.

## After the fix (ADR-0073, harness #250)
Runs `2026-11-22-dmf-r{1,2,3}`, DM-05F only. The harness is the #250 branch, the model `gpt-6-luna`.

| Case | r1 | r2 | r3 | Passed |
|---|---|---|---|---|
| pilot-dm-05f | ✅ | ✅ | ✅ | **3/3** (was 1/3) |

- CI's gates passed in all three runs. No test needed the fetched snapshot.
- The finish check's new test ran at every stop of every session: the changed tests ran with the snapshot hidden,
  and all passed. It never had to send a session back. The new rule in `afs-data-pipeline` likely steered the
  sessions to fixture snapshots from the start, and the check is the backstop.
- r1 was first graded failed because its return says `mutation_changed: n/a: no-mutable-code-changed`, the
  hyphenated reason `afs-mutation` itself prints. The grader accepted only the spaced form; the return contract
  accepts both. The grader now accepts both, alongside green gates as before.
