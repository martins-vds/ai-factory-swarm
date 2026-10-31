# Characterization (ADR-0005)

Characterization records what the **source actually does** at the equivalence boundary, before any
migration, so the target can be held to it. It never judges whether the behavior is right — anything
that looks wrong becomes a quirk ticket.

## Tiers — use the best available (recorded in `capabilities.yaml` and per ledger entry)
| Tier | When | How | Ledger `verification` |
|---|---|---|---|
| **A** | A running legacy environment exists | Drive the source through its external interfaces (HTTP, UI, batch input, DB state); record inputs → outputs; replay against the target; enables automated differential checks | `characterized` (tier A) |
| **B** | Source only, but code runs in isolation | Compile and run legacy units in a scratch harness (recipe below) and characterize at seams | `characterized` (tier B) |
| **C** | Source only, cannot run | Derive specs from reading the code: worked input → output examples citing file:line, plus the rule they encode. Every ambiguity → quirk ticket | `spec-derived` (needs human review) |

Cases to cover for every capability: normal, empty / null / zero, boundary, and error paths. Put most
effort where the source risk map is hottest. Inventory legacy tests first: their asserted behavior must
reappear as target tests.

## Tier-B recipe (proven on the pilot, spike M1-5)
- **Never modify the source.** The harness lives in the target repo (or a scratch folder) and reads the
  source checkout read-only.
- **Compile only what tests reach:** e.g. Java `javac -sourcepath <source trees> -implicit:class` with the
  test classes as roots, so code with proprietary imports elsewhere is never compiled.
- **Public artifacts** for platform APIs (e.g. JSF, JPA, EJB from Maven Central); **compile-only
  stand-ins** for the few proprietary classes on the path. Record each stand-in in `capabilities.yaml`.
- **Seams, not containers:** replace framework lookups with test doubles (e.g. a mock `FacesContext` whose
  session is a map). See `working-effectively-with-legacy-code`.
- **Use the source's own resources** (bundles, config) read-only, and its **real encoding** (the pilot is
  Windows-1252; `profile.source.encoding`).
- Watch for: one missing library cascading into many errors; legacy generics that block naive test
  types; test launchers that silently find no tests.

## Record observed vs predicted
Each characterization test records what the code did next to what reading the code predicted. Matches
confirm understanding; differences are the most valuable findings (and often quirks). Keep the recorded
outputs as the golden master the target is tested against.
