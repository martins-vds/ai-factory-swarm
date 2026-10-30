# ADR-0004: Two-level tracking in the target repo; Azure DevOps via MCP

- Status: Accepted
- Date: 2026-10-30

## Context
Large migrations need tracked work with dependencies. An epic → feature → story hierarchy was the
starting assumption, but the real goal is delivering a working application, not a particular
hierarchy. Wayfinder and to-tickets use two levels: a map with child tickets, and vertical-slice
tickets with native blocking edges.

## Decision
- **Level 1, decision map** (`wayfinder`): architecture, mappings, data strategy and quirk rulings.
- **Level 2, slice tickets** (`to-tickets`): build work, each ticket sized to one agent session, grouped
  under a slice parent via sub-issues, with native blocking edges.
- Tickets live in the **target repo's** issue tracker by default. An organization-level GitHub Project
  may aggregate views across repos.
- Azure DevOps is supported by writing a tracker doc backed by the Azure DevOps MCP server
  (`setup-matt-pocock-skills` "Other" option). Role agents use the tracker doc, never a specific API.

## Consequences
- PRs close their tickets natively; work history stays with the code.
- Decision tickets block only the build tickets they affect, so agents keep working elsewhere.
- A third level can be added later (e.g. grouping slices by bounded context) without changing roles.
