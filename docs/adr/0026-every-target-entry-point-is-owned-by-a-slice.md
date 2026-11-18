# ADR-0026: Every target entry point is owned by a slice

- Status: Accepted
- Date: 2026-11-03
- Issue: #40

## Context
The pilot's target routed Django's built-in admin (`path('admin/', admin.site.urls)`, left over from
`startproject`) through two milestones. It is a front door the source never had, and it can edit data.
No ruling approved it, and no check noticed: the graph gate only asked whether the *declared* anchors
reach data, never whether something *undeclared* was exposed. It surfaced when a decision ticket (pilot
#92) happened to look at `urls.py`.

Slice specs also had no schema. A misspelt `data_paths` key would have been ignored without a word,
and the gate would have passed with nothing to check.

## Decision
1. **Ownership.** `graph_gate.py --side target` lists every target entry point: each `endpoint` node
   (HTTP routes, WebSocket endpoints) and each `command` node. Each one must be owned by a slice, in
   one of two ways:
   - reached by the directed flow from the slice's `data_paths.target` anchors (a page's htmx call or
     form post counts);
   - or listed in the slice spec's new `entry_points.target` (`endpoint=…`, `command=…`), for what the
     anchors can't reach: a frame whose URL is built in code, a seed command.

   An entry point no slice owns fails the gate at acceptance, and is a warning on other runs. A listed
   entry point that matches nothing is reported the same way, so stale lists don't pile up.
2. **Slice specs have a schema** (`schemas/slice.schema.json`, checked by `validate.py` in CI). Unknown
   keys are errors, and `entry_points` must be `TYPE=NAME`.
3. **The Planner lists `entry_points.target`** with the anchors, when it writes the slice spec.

## Consequences
- An unapproved front door can't be accepted. On the pilot, the check names exactly three entry
  points:
  - `/admin/` is the real problem, removed by pilot #109;
  - the Track Cargo map frame (`/tracking/map/`) and the `seed_sample_data` command are Track Cargo's own,
    and its spec lists them.
- Removing a route is the honest fix for something nobody approved. Listing it requires a slice to
  claim it, in a reviewed file.

## Amendment (2026-11-09, found by the synthetic target's LL-ACCEPT)
Accepting the catalog slice failed on other slices' `entry_points.target` (the About pages, the new-loan
form), which exist only once those slices are built. A slice's data paths were already exempt while its
implementation tickets are open (`check_plan.unbuilt`). Its declared entry points now are too: a listed
entry point that matches no node fails only once the slice is built. Ownership is unchanged: a built
entry point that no slice owns still fails at acceptance.
