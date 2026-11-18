# Synthetic target kit (ADR-0037)

A small legacy app built to make the harness produce the coverage paths a real pilot may never reach.
`scenarios.yaml` lists each scenario, the coverage path it is meant to produce, and what in `legacy/` (or
which operator act) produces it honestly. Nothing in a target's `.migration/` is written by hand: the
paths appear only when the normal role sessions, gates and operator decisions produce them.

- `legacy/`: the "Lending Library" legacy app. Java 17, JAX-RS (Jersey on Grizzly) and JPA (Hibernate on
  in-memory H2), so the Java EE graph enricher sees its tables and endpoints as on a real Java EE source.
  `run.sh` builds it with Maven and starts it; fine payments fail by design.
- `legacy-billing/`: member billing (Maven). Its build needs a card-vault client from a vendor's private
  repository, so it can't be built or run; the invoice arithmetic and its JUnit tests don't touch the
  vendor client.
- `legacy-reports/`: the circulation reports. The server is gone; only the specification and saved output
  remain. No code.
- `legacy-smoke.yml`: the synthetic target's CI smoke test for the legacy app (copy it to
  `.github/workflows/`): build, start, and probe each scenario's behaviour.
- `seed.py`: writes one source (`--source`, default `legacy`) into the target repository and prints the
  `source.lock` lines to pin it.

**One source, one tier.** The characterization tier rates a whole source, so each source gets its own
Bootstrapper session. `legacy` is the target's pinned source and goes through every phase. `legacy-billing`
and `legacy-reports` each get a Bootstrapper session that assesses only that source and commits its return
under its own ticket id.

The catalog test (`tests/test_synthetic.py`) fails when the harness can produce a return-file or ledger
value that no scenario targets and that isn't recorded as exercised by a real pilot
(`pilot_exercised` in `scenarios.yaml`).

**Keep the target blind.** Nothing in the target repository (legacy code, docs, README, issues) may name a
scenario or its expected outcome. Agents decide from evidence; a hint makes the outcome worthless. The first
Bootstrapper run read a copied catalog and cited it as evidence for its tier, so the catalog stays here only.
