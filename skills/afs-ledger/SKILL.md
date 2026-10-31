---
name: afs-ledger
description: Create, update and validate fidelity-ledger entries (.migration/ledger/*.yaml) — the inventory of every source capability and its fate. Use whenever you discover a capability, migrate one, attach evidence, defer/replace/drop one, or link a quirk.
---

# Fidelity ledger

One YAML file per source capability in `.migration/ledger/`, named `<id>.yaml`. Schema:
`.migration/harness/schemas/ledger-entry.schema.json`. Ledger changes ride **in the same PR** as the code
or evidence that justifies them.

## Entry
```yaml
id: currency.list-paging              # lowercase, dot/dash separated; equals the file name
kind: ui                              # structural | behavioral | ui | integration | data
title: Page through the currency table
source:
  graph_node: <node id from the code graph>
  flow: List and Page Currencies      # domain-graph flow, when there is one
  location: java/…/BasePagedTableModel.java:52-66   # path:lines at the pinned SHA
  risk: { crap: 42, complexity: 6, coverage: 0 }
boundary: "admin/currency.jspx pager: status text, page list, navigation"   # where it is observable
slice: currency-admin
tickets: [org/repo#123]
target:
  components: [admin.currency.paging]
status: pending                       # pending | in-progress | migrated | deferred | replaced | dropped
verification: characterized           # pending | differential | characterized | legacy-test | spec-derived | review-only
characterization_tier: B              # required for characterized / spec-derived
evidence: [path/to/test::name, .migration/evidence/<slice>/report.md]
quirks: [org/repo#130]
approval: { by: <human>, ref: org/repo#131, reason: … }   # required for deferred/replaced/dropped/review-only
```

## Rules (enforced by the schema)
- `migrated` needs `target.components` and at least one `evidence` item, and verification ≠ `pending`.
- `deferred`, `replaced`, `dropped` and `review-only` need a human `approval`. Never fill it yourself:
  link the ticket where a human decided.
- `characterized` / `spec-derived` need `characterization_tier`.
- One capability per file; ids are unique; never delete an entry — change its status.

## Workflow
1. **Discover** (Analyst, Characterizer, anyone): create the entry with `status: pending`.
2. **Characterize:** add evidence and tier; set `verification`.
3. **Migrate** (Migrator): set `target.components`, add the target test as evidence, `status: migrated`.
4. **Quirk:** add the quirk ticket to `quirks`; the entry stays blocked until the human answers.
5. **Validate before every commit:**
   ```bash
   python .migration/harness/tools/validate.py .migration
   ```
   A failing validation blocks the PR.
