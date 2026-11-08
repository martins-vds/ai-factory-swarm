# Synthetic target kit (ADR-0037)

A small legacy app built to make the harness produce the coverage paths a real pilot may never reach.
`scenarios.yaml` lists each scenario, the coverage path it is meant to produce, and what in `legacy/` (or
which operator act) produces it honestly. Nothing in a target's `.migration/` is written by hand: the
paths appear only when the normal role sessions, gates and operator decisions produce them.

- `legacy/`: the "Lending Library" legacy app. Java 17, JAX-RS (Jersey on Grizzly) and JPA (Hibernate on
  in-memory H2), so the Java EE graph enricher sees its tables and endpoints as on a real Java EE source.
  `run.sh` builds it with Maven and starts it; fine payments fail by design.
- `legacy-smoke.yml`: the synthetic target's CI smoke test for the legacy app (copy it to
  `.github/workflows/`): build, start, and probe each scenario's behaviour.
- `seed.py`: writes `legacy/` into a new target repository and prints the `source.lock` to pin it.

The catalog test (`tests/test_synthetic.py`) fails when the harness can produce a return-file or ledger
value that no scenario targets and that isn't recorded as exercised by a real pilot
(`pilot_exercised` in `scenarios.yaml`).
