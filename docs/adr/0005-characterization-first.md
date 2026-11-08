# ADR-0005: Characterization first, by tier; "review-only" as the signed fallback

- Status: Accepted (revised after M1 spikes)
- Date: 2026-10-30

## Context
Legacy systems often have few tests and may be hard to run. We cannot assume the source's own tests
are sufficient, or even runnable. Yet behavior at the equivalence boundary (ADR-0001) must be captured
before it can be preserved.

Spike M1-3 showed a harder case: the pilot's legacy build cannot run outside its organization (it needs
a proprietary WebLogic client and an internal repository manager). We also cannot count on a running
legacy environment: sometimes **all we have is the source code**.

## Decision
- Characterization is **mandatory** and happens before migration (lifecycle Phase 3).
- Behavior asserted by any existing legacy test must reappear as a test in the target, in the target's
  idiom; the target then adds more coverage on top.
- **The characterization tier is chosen in bootstrap** from what is available, for the whole migration
  and refined per capability:

| Tier | Available | How behavior is captured | Ledger `verification` |
|------|-----------|--------------------------|-----------------------|
| **A · Running environment** | A running legacy instance (ops-provided) | Record inputs → observable outputs at the equivalence boundary (HTTP, UI, batch input, DB state); replay against the target; enables automated differential checks | `characterized` (boundary) |
| **B · Runnable in isolation** | Source only, but code can be compiled and run without the full platform | Compile against public API artifacts (e.g. Java EE / Jakarta EE APIs) or stand-ins for proprietary provided-scope dependencies; write characterization tests at seams — services with fakes, entity logic, validators, calculations, import logic — in a scratch project that reads the source and never modifies it; database containers where a free engine fits | `characterized` (unit/component) |
| **C · Source only, not runnable** | Source only | The Characterizer derives behavioral specifications from the code: worked input → output examples, each citing file and line, plus the rules they encode. They become the target's acceptance tests (mutation gate still applies). Every ambiguity is a quirk ticket for a human. | `spec-derived` (needs human review) |

- Effort follows the source risk map (ADR-0013): hottest areas get the deepest tier available.
- Where coverage of the source can be collected (tiers A and B), the risk map is refreshed with it.
- A capability that cannot be characterized at any tier is `review-only` and needs a human tester's
  sign-off before cutover.

### Tier B recipe (proven in spike M1-5)
On the pilot (Java EE, build blocked by a proprietary WebLogic client), 312 legacy classes compiled and
13 characterization tests ran from source alone:
- compile only what tests reach (`javac -sourcepath … -implicit:class`, tests as roots);
- public artifacts for platform APIs, compile-only stand-ins for the few proprietary classes on the path;
- seams instead of containers (e.g. a mock `FacesContext` whose session is a map);
- the source's own resources, read-only; and its real source encoding (here Windows-1252).
Each characterization test records observed behavior next to the behavior predicted by reading the code,
so tiers B and C can be compared on the same capability.

## Consequences
- A dedicated Characterizer role builds and maintains the harness for the chosen tier.
- Bootstrap's capability checklist records the tier per migration and the reason (ADR-0012).
- Tier C evidence is weaker: it proves the target matches what was *read* from the code, not what the
  code *did*. The ledger records this, and such capabilities get human review in slice acceptance.
- Without tier A, the differential checks and side-by-side comparisons of ADR-0006 are replaced by
  checks against the characterization tests and specs plus human domain review.

### Amendment (2026-11-08): tier C only after the tier-B recipe was tried

On the synthetic target (ADR-0037), a Bootstrapper rated a member-billing source tier C. Its full Maven
build and `mvn test` failed on a vendor library from a private repository. It never tried compiling the
invoice arithmetic and its JUnit tests from source alone, which works: the harness CI proves it. The
instruction asked whether the blocking dependencies were "compile-only". The session read that as a Maven
scope, not as "can the tested code compile without them". Tier C evidence is the weakest the harness
accepts, so it must not be reached by skipping a step.

The Bootstrapper now tries the tier-B recipe whenever there is no running environment. A tier-C return
must carry `tier_b_attempt`: either `ran: <command> -> <result>` or `no code: <contents>`. `validate.py`
rejects a tier C without one.
