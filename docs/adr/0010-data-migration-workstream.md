# ADR-0010: Data migration as its own workstream

- Status: Accepted
- Date: 2026-10-30

## Context
Re-architecting the domain (ADR-0001) usually changes the data model. The side-by-side checks and
final UAT (ADR-0006) run on a copy of production data, which must be in the target's schema. At
cutover the real data must be moved too.

## Decision
- Data migration is a **workstream** with its own slices and tickets, carried out by the Data
  Specialist Migrator.
- Its deliverable is a **repeatable pipeline** from the legacy schema to the target schema.
- It is verified by reconciliation checks (row counts, checksums, referential integrity), business
  invariants, and characterization of legacy stored procedures and reports that the target replaces.
- Data slices block the application slices that depend on their data.
- The **operations team** provides production snapshots. The pipeline produces the target's copy;
  every refresh is a rehearsal of the cutover data move.
- **Masking is nice to have:** if a masking step is available it runs on the snapshot before the
  pipeline (`profile.data.masking`); it is not required.

## Consequences
- By cutover day the data pipeline has run many times against real data shapes.
- Data issues surface during slices, not at cutover.
- Without masking, access to the side-by-side environment must be restricted to people allowed to see
  production data.
