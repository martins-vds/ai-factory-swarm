# ADR-0066: A target with code declares its layers

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-22
- Source: [test-trust plan](../reviews/test-trust-plan.md), step 4.4; ADR-0043 (the layering gate)

## Context
ADR-0043 made the target's layers import contracts that `check_layers.py` enforces in the idiom gate. In eval
baseline b3c, the Verifier missed every import-level layering defect it was shown; the tool finds them every
time. But the contracts were optional. A target with no `layering:` passed the gate, so the architecture
held only where someone had remembered to write it down.

Both live targets declare contracts now. The pilot has three, one per layer. The synthetic target had only
one, from LL-02's verify ruling (#79), on the use cases. Its views and its persistence weren't covered, and
one real break went unnoticed: the loan list and detail pages query the ORM directly instead of the loan use
case.

## Decision
1. **Once the target has code, `layering.contracts` is required.** `validate.py`, and so CI and the finish
   check, refuses a profile with none when there is any Python module under the profile's `graph.target_paths`
   (default `src`), not counting migrations and `__init__.py`. A new target passes until its first slice
   lands. The rule from ADR-0043 still holds: the contracts must run in `gates.idiom`.
2. **The contracts come from the target's architecture ADRs**, and each names its source in `adr:`. A break that
   predates a contract is a `known` entry with what will remove it, not a weaker contract.
3. **The synthetic target gets two contracts, its first from the adapter side:**
   - web adapters and commands call use cases, not persistence;
   - persistence and gateways don't reach up into the web.

   One `known` entry records the loan pages' direct ORM queries. Forms are left out, because a Django
   `ModelForm` is tied to its model by design.

## Consequences
- Every target's architecture is checked by a tool from the first slice on, so a Verifier's review covers
  what the tool can't see.
- The synthetic target's `known` entry is debt with a name. Its fix is a Migrator ticket to plan.
- Not covered: a contract that is too loose. The contracts are reviewed with the ADRs they cite.
