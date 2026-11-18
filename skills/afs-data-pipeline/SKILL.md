---
name: afs-data-pipeline
description: Move relational data from a legacy database snapshot into the target schema with a repeatable pipeline, and prove it with deterministic reconciliation (row counts, checksums, referential integrity). Use for data-migration slices and tickets (ADR-0010, ADR-0032), when planning them, and whenever a snapshot is refreshed.
---

# Data pipeline: snapshot → target, reconciled

The data workstream (ADR-0010) delivers a **repeatable pipeline**. It takes a snapshot of the legacy
database, loads it into the target schema, and proves the result with reconciliation that a tool
computes (`data_reconcile.py`), not an agent. Every refresh of the snapshot is a cutover rehearsal.

This skill is engine-agnostic. It works for any relational source that can export CSV, and any target
the stack can load and export. Stack-specific parts (the loader, the export command) live in the target
repo and the profile.

## The pieces

| Piece | Where | Who |
|---|---|---|
| **Snapshot**: `<TABLE>.csv` per table + `manifest.json` | Made by the **AFS data snapshot** workflow from `profile.data.snapshot` commands, kept as its artifact; fetched into `profile.data.snapshot_dir` (default `.migration/data/snapshot/`, **gitignored**) by Copilot setup steps | The snapshot owner (`profile.data.snapshot_owner`) **dispatches** the workflow; agents never make a snapshot |
| **Mapping**: source → target tables, columns, transforms, references | `profile.data.mapping` (default `.migration/data/mapping.yaml`), committed | Data Specialist |
| **Loader**: snapshot → target, through the mapping | Target code (e.g. a management command), committed; run by `profile.data.load` | Data Specialist |
| **Export**: target tables → CSV, same conventions | `profile.data.export`, writes into `{out}` (gitignored `.migration/data/target-export/`) | Data Specialist |
| **Reconciliation** | `python .migration/harness/tools/data_reconcile.py reconcile …`, through `afs-run` | The tool |

**Production data is never committed.** Neither the snapshot nor the target export goes into git:
bootstrap gitignores both folders. What is committed is the manifest's counts and hashes, quoted in the
evidence report, plus the reconciliation report.

## Snapshot format
- One `<TABLE>.csv` per table, UTF-8, RFC 4180 quoting, **with a header row** of column names.
- NULL is a marker, `\N` by default (`manifest.json` → `null`), so NULL and the empty string stay
  different. An export that writes NULL as an empty field loses that difference. Fix the export, don't
  paper over it in the mapping.
- `manifest.json`:
  ```json
  {"source": {"engine": "derby", "database": "cargotracker"}, "taken_at": "2026-11-06T22:00:00Z",
   "taken_by": "martins-vds", "null": "\\N",
   "tables": {"CARGO": {"rows": 12, "sha256": "…"}, "LOCATION": {"rows": 13, "sha256": "…"}}}
  ```
- Check it before anything reads it: `data_reconcile.py snapshot <dir>` (each file present, row
  count and sha256 as stated). Export recipes per engine: `references/export-recipes.md`.
- **Any JDBC-reachable engine:** `data_snapshot.py export --jdbc-url … --driver group:artifact:version@sha256
  --out {out}` exports every table in this format, writes the manifest and checks it. A typical
  `profile.data.snapshot` starts the legacy runtime (or a copy of its database), stops it so the files
  are consistent, then runs that export:
  ```yaml
  data:
    snapshot_owner: ops-team
    snapshot_java: "8"
    snapshot:
      - "bash scripts/run-legacy.sh"          # start, optionally drive it, stop
      - "python .migration/harness/tools/data_snapshot.py export --jdbc-url 'jdbc:derby:/tmp/app-db' --driver org.apache.derby:derby:10.14.2.0@<sha256> --engine derby --out {out}"
  ```

## Mapping
```yaml
defaults: {timestamp_tz: UTC}          # zone of naive source timestamps
tables:                                # load order: parents before children
  - target: location
    source: LOCATION
    key: [unlocode]
    columns:
      id: ID
      unlocode: {from: UNLOCODE, as: trim}
      name: NAME
  - target: cargo
    source: CARGO
    key: [tracking_id]
    columns:
      id: ID
      tracking_id: TRACKING_ID
      origin_id: ORIGIN_ID
      routing_status: {from: ROUTING_STATUS, as: {map: {"0": NOT_ROUTED, "1": ROUTED}}}
      last_event_time: {from: LAST_EVENT_TIME, as: timestamp}
    refs: {origin_id: location.id}
```
- **Transforms:**
  - `identity` (the default), `trim`, `int`, `decimal`, `bool`, `timestamp` (compared in UTC, to the
    second), `date`, `null_if_empty`;
  - `{map: {source: target}}`. A source value the map doesn't list is an **error**, not a guess.
- **One source of truth.** The loader reads this file, and so does the reconciliation. A conversion
  that only the loader knows about is a mismatch waiting to happen; put it in the mapping.
- **Every** legacy table in scope is mapped or listed under `excluded:` with a reason, and a ledger
  entry (`kind: data`, `status: dropped` or `deferred`) records the decision.

## Procedure (Data Specialist, one data ticket)
1. **Snapshot.** Run `data_reconcile.py snapshot` through `afs-run`. A failure stops the ticket; ask
   the snapshot owner for a new export. Never "fix" snapshot files by hand.
2. **Mapping.** Add the ticket's tables. Characterize anything surprising in the data, e.g. orphan rows,
   values outside an enum, or text in a date column. Raise each as a quirk ticket (`afs-quirk-ticket`);
   never drop or coerce rows silently.
3. **Loader.** Write it test-first (`tdd`).
   - **Idempotent:** a re-run on the same snapshot gives the same target; a run is one transaction, or
     clears and reloads its tables.
   - **Parents first.**
   - **No business logic** beyond what the mapping states.
   - **Keep source keys** where the schema mirrors them (ADR-0003), so references survive.
4. **Export.** Make `profile.data.export` write each mapped target table as `<table>.csv`, header row,
   NULL as `\N`.
5. **Reconcile.** Run each step through `afs-run`: `data.load`, then `data.export`, then
   `data_reconcile.py reconcile --snapshot … --target … --mapping … --report
   .migration/evidence/data/<ticket>.md`. Every table must match on rows and checksum, with no dangling
   reference.
6. **Business invariants.** Write them as tests that run on the loaded data. For example, a cargo's
   derived delivery state equals what the legacy app shows for it, and every itinerary's legs connect.
   Characterize legacy stored procedures or reports the target replaces (`afs-evidence`).
7. **Ledger.**
   - One `kind: data` entry per table or table group, `verification: differential`.
   - Evidence: the reconciliation report, plus the invariant tests.
8. **Rehearsal.** The run is repeatable from a fresh snapshot with the same commands. Say so in the
   evidence, with the snapshot's `taken_at` and the manifest's counts.

## Rules
- Reconciliation results come from `data_reconcile.py` (ADR-0017), never from an agent's count.
- Masking runs on the snapshot before the loader, only if `profile.data.masking` is true.
- A mismatch is fixed in the mapping or the loader, then the whole sequence runs again. Never edit the
  target export to make it match.
- Large tables: the tool streams files but holds one table's rows in memory. Split a very large table by
  key range into several mapped parts if needed, and say so in the evidence.
