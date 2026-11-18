# ADR-0019: Code graphs carry their identity and are checked for freshness

- Status: Accepted; enforcement on the target side amended by ADR-0035
- Date: 2026-11-02

## Context
The M5 re-audit reported the source graph as stale. The graph's `project.gitCommitHash` (`a8cdf52…`)
did not match the pinned source (`f3beacf…`). In fact the graph was built from the pinned source: the
hash is the throwaway commit the workflow makes of the analysed folder. The pinned SHA was only in a
human-oriented `SNAPSHOT.txt`, so neither an agent nor a script could tell a fresh graph from a stale
one. Separately, no target graph had ever been built. The workflow only knew how to build source
graphs, and the Auditor's instruction to "refresh the target graph" was impossible to follow from a
remote session.

## Decision
1. **Identity.** The afs-understand workflow stamps every graph it builds:
   - `project.gitCommitHash` in the JSONs is the commit the graph describes. That is the pinned source
     SHA, or the target commit. The throwaway commit is kept as `analyzedCommit`.
   - `SNAPSHOT.txt` records `side` and `scope`, plus `source_sha` for a source graph, or
     `target_commit` and `tree.<path>` (the git tree hash of each analysed path) for a target graph.
2. **Target graphs.** The workflow takes `side=target` and analyses the profile's `graph.target_paths`
   (default `src`, without tests) at the current commit, into `.migration/graphs/target/full/`.
3. **Freshness check.** `tools/check_graph_fresh.py` decides deterministically, with git:
   - a source graph is fresh when its stamp equals `source.lock`;
   - a target graph is fresh when every recorded tree hash equals `git rev-parse HEAD:<path>`, so
     test-only changes don't make it stale;
   - graphs without a stamp count as stale.
4. **Enforcement.**
   - **CI (harness job):** a stale source graph always fails. A stale target graph is a warning, since
     code changes with every merge. A PR that adds an auditor return with `verdict: complete` also
     needs a fresh target graph.
   - **Auditor:** runs `check_graph_fresh.py --require source,target` first and stops if it fails.
   - **Slice Coordinator / dispatcher:** builds the target graph (and the source graph if stale), and
     merges it before dispatching acceptance.
   - **Automatic refresh:** the source graph is rebuilt whenever `source.lock` changes on `main`.

## Consequences
- "Is the graph stale?" has one deterministic answer, and an acceptance can't pass on a stale graph.
- Graphs built before this ADR are unstamped and must be rebuilt once.
- Target graphs cost Copilot premium requests, so they are built per acceptance rather than per merge.
- The workflow pushes the graph and opens its PR **before** checking it, and checks only the graph it
  built (`--only`). A failed check then leaves a PR to inspect instead of a lost, already-paid build.
- Graph builds run on `main`. A workflow token cannot push a branch whose history changes workflow files
  that are not on `main` yet, so a harness-upgrade branch must merge first.
