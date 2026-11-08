# Synthetic target kit (ADR-0037)

A small legacy app built to make the harness produce the coverage paths a real pilot may never reach.
`scenarios.yaml` lists each scenario, the coverage path it is meant to produce, and what in `legacy/` (or
which operator act) produces it honestly. Nothing in a target's `.migration/` is written by hand: the
paths appear only when the normal role sessions, gates and operator decisions produce them.

- `legacy/`: the "Lending Library" legacy app. Java 17, standard library only (JDK HTTP server, in-memory
  store), so it builds and runs anywhere with `javac` + `java`, except the parts a scenario keeps from
  running on purpose.
- `seed.py`: writes `legacy/` into a new target repository and prints the `source.lock` to pin it.

The catalog test (`tests/test_synthetic.py`) fails when the harness can produce a return-file or ledger
value that no scenario targets and that isn't recorded as exercised by a real pilot
(`pilot_exercised` in `scenarios.yaml`).
