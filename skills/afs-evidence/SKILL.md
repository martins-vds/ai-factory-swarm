---
name: afs-evidence
description: Run gates and produce auditable evidence — every gate command goes through afs-run, raw logs stay in .migration/runs/, a committed run journal records every run, and slice acceptance produces an evidence report. Use whenever you run a build, test, CRAP or mutation gate, or claim something passes.
---

# Evidence

A claim that something passes is only valid with **fresh output from this session**.

## Running a gate
```bash
.migration/harness/tools/afs-run --ticket <ticket-id> --name <gate> -- <command from profile.gates.*>
# e.g.
.migration/harness/tools/afs-run --ticket T-142 --name tests -- pytest -q
```
`afs-run` runs the command once, keeps the full log at `.migration/runs/<ticket>/<timestamp>-<gate>.log`,
appends a record to `.migration/runs/<ticket>/runs.jsonl`, prints a short summary (exit code, failure
lines with their line numbers in the log, tail on failure) and exits with the command's exit code.

- Read the summary; open the log only at the reported line numbers (`sed -n '120,160p' <log>`), never
  whole.
- Everyday commands (git, listing, quick checks) go through `rtk`, not `afs-run`.
- Raw logs are not committed (`.migration/runs/` is gitignored and disappears with your session).
  `afs-run` also appends a row per run to **`.migration/evidence/runs/<ticket>.md`** (time, gate, exit,
  seconds, command, log SHA-256, first highlight, **result**). Always pass your own `--ticket`: one journal per
  ticket keeps parallel PRs from touching the same file. **Commit that journal** with your work; it is what
  `evidence_logs` in your return file points to. Link the journal from the PR description; don't
  paste it.

## Results come from the gate tools, never from you (ADR-0017)
Harness gate tools (`afs-mutation`, `crap.py`, and each stack's adapter) print one line
`AFS-RESULT gate=<gate> key=value …`; `afs-run` records it in the journal's Result column. Never convert,
round or retype a tool's output yourself, and never print an `AFS-RESULT` line from anything else.
- A score in your return file (`mutation_changed`, `mutation_full`, `mutation_score`) is copied exactly
  from the last mutation run in your journal **made with the profile's gate command** (as given, or via
  `bash -c`). `validate.py` compares them; a run with other options (`--paths …`) doesn't count.
- When you finish (no handoff), every `gates` value is a number or `n/a: <reason>` (e.g. `n/a: no
  production code changed`). `null` means "not reached" and is allowed only with a handoff.

## Per-PR evidence (Migrator, Verifier)
The committed run journal plus the return file's `gates` map are the evidence; every gate from
`afs-migration-contract` → references/gates.md must appear in both. The PR description links to both; it
doesn't repeat their contents.

## Slice evidence report (Slice Coordinator, Auditor)
Write `.migration/evidence/<slice>/report.md` (committed):
```markdown
# Slice <slice> — acceptance evidence
- Tickets: <list>   · Commit: <sha>   · Date: <UTC>
## Gates
| Gate | Command | Exit | Notes |
## Characterization (tier A/B/C)
<suite run summary; differential results if tier A>
## Mutation (full run)
<score vs threshold; surviving mutants worth noting>
## Capability coverage (gate 7)
<every ledger entry of the slice: target components, evidence, status>
## Human check
<who checked, when, outcome, follow-up tickets>
```
