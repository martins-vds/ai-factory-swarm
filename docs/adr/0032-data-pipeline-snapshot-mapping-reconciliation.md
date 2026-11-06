# ADR-0032: Data moves from a snapshot through one mapping, and reconciliation is computed

- Status: Accepted (martins-vds, 2026-11-06: "write a harness skill for moving relational data from a snapshot")
- Date: 2026-11-06
- Refines: ADR-0010

## Context
ADR-0010 makes data migration a workstream with a repeatable pipeline and reconciliation checks, but
the harness gave it no tool or skill. On the pilot, the `data-migration` capability was a gap: no
pinned skill covered Derby → PostgreSQL. The only data skills in the stack pack were Oracle-specific.
A skill per engine pair would multiply. And reconciliation counted by an agent would break ADR-0017:
gate results come from tools.

## Decision
1. **One engine-agnostic contract**, in the harness skill `afs-data-pipeline`:
   - **Snapshot:** one CSV per table with a header row, NULL as a marker (`\N`), and a manifest with
     row counts and sha256. The operator exports it (`profile.data.snapshot_owner`).
   - **Mapping file**, committed: target table ← source table, columns, declared transforms, keys and
     references. Tables are listed in load order.
   - **Stack-specific loader and export**, named in the profile (`data.load`, `data.export`). The loader
     reads the mapping, so conversions live in one place.
2. **Reconciliation is a tool.** `tools/data_reconcile.py`:
   - `snapshot` checks the snapshot's integrity;
   - `reconcile` compares the snapshot with the target's own export, through the mapping: row counts,
     a checksum of the mapped rows, the first differing keys, and referential integrity.

   It exits 1 on any mismatch and prints `AFS-RESULT gate=data-reconcile`. A value that a `map`
   transform doesn't list is an error, never a guess.
3. **Production data is never committed.** Bootstrap gitignores `.migration/data/snapshot/` and
   `.migration/data/target-export/`. The manifest's counts and the reconciliation report are the
   committed evidence.
4. **Roles.**
   - The Data Specialist Migrator builds the mapping, loader and export.
   - The Planner plans data slices with the skill.
   - The Verifier re-runs reconciliation itself.
   - The Auditor treats the reports and invariant tests as evidence.

## Consequences
- A new source engine needs an export that meets the snapshot format (the skill's export recipes), not
  a new skill. A new target stack needs a loader and an export command.
- The `data-migration` capability can be met by `afs-data-pipeline` (skill) and `data_reconcile.py`
  (tool) for any engine pair whose source can export the snapshot format.
- Business invariants and characterized legacy procedures or reports stay as tests in the target. The
  tool proves the data moved intact; the tests prove it still means the same.
- One table's rows are held in memory during comparison. A very large table is split by key range into
  several mapped parts.
