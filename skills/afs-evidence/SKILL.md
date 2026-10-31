---
name: afs-evidence
description: Run gates and produce auditable evidence — every gate command goes through afs-run, raw logs stay in .migration/runs/, and slice acceptance produces an evidence report. Use whenever you run a build, test, CRAP or mutation gate, or claim something passes.
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
- Gate logs are not committed (`.migration/runs/` is gitignored). Quote the relevant lines in the PR
  description or evidence report, with the gate name, exit code and log path.

## Per-PR evidence (Migrator, Verifier)
In the PR description, a table: gate · command · exit · key lines. All gates from
`afs-migration-contract` → references/gates.md must be present.

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
