# ADR-0035: The acceptance target graph is built for the revision it checks

- Status: Accepted (martins-vds, 2026-11-07: "merge 113")
- Date: 2026-11-07
- Amends: ADR-0019 (enforcement, target side)

## Context
ADR-0019 makes graph freshness deterministic: a target graph is fresh when the tree hash of every
analysed path equals the current checkout's. It also makes a fresh, **committed** target graph a
precondition of acceptance:
- the dispatcher builds the graph and merges its PR;
- then the Auditor checks freshness against its checkout;
- CI rejects `verdict: complete` on a stale one.

On the pilot (2026-11-07) that was a manual loop, and it was in the way of normal work:
- the data-migration Auditor needed a fresh graph;
- the dispatcher started the rebuild, opened its PR by hand (Actions may not create PRs on that repo),
  and asked the operator to merge it;
- merging BK-05E made the graph stale again within minutes, so the loop ran a second time;
- the dispatcher then had to ask the operator not to merge code until the audit finished.

The source graph is different: the legacy code is pinned (`source.lock`), so it goes stale only on a
deliberate re-pin, which ADR-0019 already rebuilds automatically.

For the target graph, stale is the normal state during a migration: every merge that touches an analysed
path makes it stale. A rule that holds only while nobody merges is a rule people break. The harness
should make the correct thing the default, not depend on a pause.

What acceptance actually needs is not "the committed graph matches `main` now". It needs "the graph
the gate and the Auditor used describes exactly the code being accepted". Full mutation already works
this way: the **AFS acceptance gates** workflow runs it at one revision, and the Auditor verifies and
imports that run's artifact (`afs-evidence`'s durable Actions procedure).

## Decision
1. **The acceptance workflow builds the target graph itself.** The AFS acceptance gates workflow builds
   the target graph at the exact commit it checks: the same steps as afs-understand `side=target`
   (Understand Anything, Graphify, the stack enrichers and the data-mapping edges). The steps are shared,
   not copied. It then runs `graph_gate.py --side target --require-graph` on that graph. The graph, its
   `SNAPSHOT.txt` and the gate report go into the run's artifact, beside the full-mutation results. The
   graph is not committed.
2. **Freshness means one revision.** The Auditor audits one commit C:
   - the acceptance run checked C;
   - the graph in its artifact describes C (its tree hashes equal C's);
   - the Auditor's checkout has C's trees for the analysed paths.

   `check_graph_fresh.py` gains a mode that compares a graph's `SNAPSHOT.txt` against a named commit,
   not just `HEAD`. The Auditor's return records C and the acceptance run. Merges to `main` during the
   audit change nothing.
3. **CI checks the binding, not the current `main`.** A PR that adds an Auditor return with
   `verdict: complete` must cite an acceptance run that succeeded, whose graph describes the cited commit,
   and that commit must be an ancestor of the PR head. The audit is "as of C"; work merged after C is
   audited with the next slice or the final verification.
4. **The committed target graph is a reference.** `.migration/graphs/target/full/` stays for planners and
   people, rebuilt on demand or after a slice is accepted. Nothing blocks on it. A stale committed target
   graph is a warning everywhere, as it already is in CI.
5. **The source graph is unchanged.** It stays committed, rebuilt automatically when `source.lock`
   changes, only grows (ADR-0033), and must be fresh before planning and audit.

## Consequences
- No dispatcher step, hand-opened PR or "don't merge" pause stands between a slice's last merge and its
  audit. The dispatcher starts one acceptance run, and the Auditor starts from its result.
- The graph and the mutation score describe the same commit as the audit, by construction.
- Cost is unchanged: one target-graph build per acceptance, as ADR-0019 intended. A failed or
  interrupted build is a failed acceptance run, never a pass, like an interrupted mutation run.
- The acceptance run gets longer by one graph build, and it already runs outside agent sessions.
- To build: share the graph-build steps between afs-understand and afs-acceptance; add the commit mode
  to `check_graph_fresh.py`; bind the Auditor's return to the run and commit, and check that binding in CI;
  update the Auditor's procedure and `afs-evidence`; prove it with a drill that merges code during an
  audit and still gets a valid acceptance.

### Amendment (2026-11-08): sessions fetch acceptance evidence over git

The pilot's booking acceptance (run 42506832839) passed, but its Slice Coordinator couldn't import it:
`curl: (6) Could not resolve host: productionresultssa32.blob.core.windows.net`. GitHub serves each
artifact from one of many numbered storage hosts, and Copilot's firewall allows only some of them. The
data-migration run had landed on an allowed one by luck. Allowing all of `blob.core.windows.net` would
let a session send data to any Azure storage account.

The acceptance workflow now has a `publish` job. It runs after the gates on GitHub's runner, downloads
the run's artifact, and pushes its files as the tree of the branch `afs/acceptance/<run-id>-<attempt>`.
It is the only job with write access, and it checks out and runs no target code; the gate job stays
read-only. `afs-acceptance fetch --run-id --attempt --dest` copies that tree out, and `afs-acceptance
verify` checks it exactly as it checks an artifact. The artifact download remains the fallback for runs
without a branch. The branches stay as a record of what was imported.

### Amendment (2026-11-09): a re-audit cites a run already on main

The pilot's booking Auditor (BK-05J) first returned `gaps-remain`; acceptance then ran, and BK-ACCEPT
merged its verified result (#474). A re-audit returned `complete` but could not pass CI. The binding check
only accepted a run that the same PR adds, and the run was already on `main`. An accepting Auditor return
may now name an already committed result with `acceptance_run: .migration/evidence/acceptance-runs/<run>-<attempt>.json`.
The check verifies it exactly like an added one: it passed, its commit is in this change's history, and
its target graph describes that commit.
