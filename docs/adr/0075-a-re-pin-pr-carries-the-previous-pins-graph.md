# ADR-0075: A re-pin PR carries the previous pin's graph

- Status: Proposed (merging the harness PR that adds it accepts it)
- Date: 2026-11-23
- Source: synthetic target #166, the first re-pin of a live target's source (the legacy library gained holds);
  ADR-0019

## Context
ADR-0019 makes a stale source graph always an error, and rebuilds the source graph automatically when
`.migration/source.lock` changes on main. The rebuild can only run on main: a workflow token can't push to a
branch whose history changes workflow files that aren't on main yet. So the PR that moves the pin always carries
the graph of the previous pin. `check_graph_fresh.py` reported that as stale, and the PR could never pass. The
first re-pin, synthetic #166, failed for exactly that reason.

## Decision
When the change itself moves `source.lock` away from the base's pin (the base is `--acceptance-since`, the PR's
base, which CI already passes), a source graph built for exactly the base's pin is a warning that names the
re-pin, not an error.

Everything else stays an error:
- a source graph for any other pin;
- a stale graph checked without a base;
- a stale graph checked once the re-pin is on main;
- a stale graph when the same change records an acceptance.

## Consequences
- A re-pin merges through the ordinary setup PR. On main, afs-understand then rebuilds the graph and proposes
  it as a PR.
- Until that graph PR merges, main's source graph is stale, so every other PR fails the check. No work proceeds
  on a graph that describes the old source.
