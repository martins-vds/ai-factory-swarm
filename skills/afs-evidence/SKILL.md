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
  seconds, command, log SHA-256, first highlight). Always pass your own `--ticket`: one journal per
  ticket keeps parallel PRs from touching the same file. **Commit that journal** with your work; it is what
  `evidence_logs` in your return file points to. Quote decisive lines in the PR summary if useful.

## Per-PR evidence (Migrator, Verifier)
The committed run journal plus the return file's `gates` map are the evidence; every gate from
`afs-migration-contract` → references/gates.md must appear in both. The PR summary may repeat the key
lines for reviewers.

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
