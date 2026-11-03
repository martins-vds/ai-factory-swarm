# ADR-0022: Re-walking the decision map's fog after each slice is a ticket

- Status: Accepted
- Date: 2026-11-02

## Context
Wayfinder graduates fog when a ticket is resolved: "graduate any fog the answer has made specifiable".
In a migration, though, slices execute **outside** the decision map, and their work sharpens fog that
no ticket resolution touches. After the Track Cargo slice (M5), the map's *Not yet specified* still held
"interfaces beyond the UI" as plain text. The source survey and the enriched graph had since made seven
precise questions out of it: one piece of research and six decisions. Nothing prompted anyone to graduate
them. Migrations run for months, and a step that depends on a person remembering to revisit the map will
be missed.

## Decision
Fill the gap with wayfinder's own parts, and make the right thing the default:
1. **The rule lives in the map's Notes**, where wayfinder sessions read standing preferences: "Slices
   execute outside this map. After every slice acceptance, run a wayfinder work session …". The Program
   Orchestrator writes it when charting.
2. **Closing a slice epic opens a ticket.** The AFS map fog workflow (`tools/fog_rewalk.py`) runs when an
   issue closes. If the issue is a slice epic (label `afs:slice`, or named as `epic:` in a slice spec, so a
   forgotten label is covered), it opens a `wayfinder:task` child of the map: "Re-walk the fog after
   accepting <epic>". It is assigned to whoever closed the epic, and its checklist is the current
   *Not yet specified* list. Each item is resolved as "new ticket" or "still fog: why", and anything new
   the slice surfaced is added.
3. **Planning waits for it.** The Program Orchestrator dispatches no new slice planning while a re-walk
   task is open.

Graduation itself stays a wayfinder work session that a person drives: create the tickets, then wire
their edges; one session never resolves more than one ticket. The harness only guarantees that the
session is a ticket on the frontier rather than a memory.

## Consequences
- After every slice, the map's fog is either ticketed or explicitly reconfirmed, on the record.
- The first application (M5, done by hand): seven tickets graduated on the pilot's map. Asynchronous
  flows (research) block messaging semantics, which blocks the REST contract, real-time updates and the
  drop folder. Route finding and admin authentication are independent.
