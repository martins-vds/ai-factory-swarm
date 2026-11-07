---
name: afs-evidence
description: Run gates and produce auditable evidence — every gate command goes through afs-run, raw logs stay in .migration/runs/, a committed run journal records every run, and slice acceptance produces an evidence report. Use whenever you run a build, test, CRAP or mutation gate, or claim something passes.
---

# Evidence

A claim that something passes requires **fresh output from this session**, or independently verified
durable Actions output for the same execution inputs as described below.

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

For differential checks, follow `afs-migration-contract`'s **Differential fidelity** checklist. Commit
case/field classifications in the linked evidence report, including input, source observation,
target observation, expected target behavior and the decision or independent evidence justifying it.
Keep approved divergences, comparison defects, unresolved quirks and implementation defects distinct.
Record remaining failures honestly; a corrected oracle is not evidence that production now passes.

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

## Durable slice gates outside the cloud worker
The generated **AFS acceptance gates** workflow runs independently of the shorter model-session
lifetime. It is manual, read-only on GitHub, and does not commit evidence, open a PR, accept a slice or
merge anything. Install it through a reviewed, pinned bootstrap rollout before dispatching it.

1. Select the reviewed branch/ref and dispatch `afs-acceptance.yml` with the acceptance ticket. Record
   the run URL, repository, resolved source SHA, run ID and attempt. Do not silently use a newer head.
   The job has a six-hour limit; its gate step has 330 minutes, leaving artifact-upload headroom.
2. `afs-acceptance run` records runtime/integrity/service and both-side graph preflights, then the
   profile's exact build, idiom, tests, CRAP and **mutation_full** command lists through `afs-run`.
   Ordinary PR checks still run changed-code mutation only.
3. Wait for the actual Actions run, not the agent's finish event. Download the matching
   `afs-acceptance-<sha>-<run-id>-<attempt>` artifact under gitignored `.migration/runs/`.
   Independently inspect that run using GitHub: correct repository, source SHA, attempt, workflow
   source and **successful** conclusion. Hashes prove file integrity, not who produced the artifact.
4. On the Auditor's checkout, verify the downloaded directory:
   ```bash
   python .migration/harness/tools/afs-acceptance verify .migration/runs/downloaded-artifact \
     --commit <executed-full-sha> --run-id <run-id> --attempt <attempt>
   ```
   Verification requires the same tracked execution inputs, profile, source lock and installed pin,
   all planned passing gates, unmodified complete raw logs/records, and numeric, nonempty `base=all`
   mutation accounting meeting the profile threshold. Missing, partial, N/A, failed, interrupted or
   mismatched evidence cannot pass. Report Markdown, returns, handoffs and cost records may advance;
   reserved acceptance-result archives may also advance; code, tests, JSON evidence fixtures, graph
   inputs and other execution inputs may not.
5. After verification, append the artifact's `journals/<ticket>.md` **data rows unchanged** to your
   committed `.migration/evidence/runs/<ticket>.md`; preserve all prior rows. Copy the machine
   `result.json` unchanged to `.migration/evidence/acceptance-runs/<run-id>-<attempt>.json` (a reserved
   report directory, never test-fixture storage) and link it with the original Actions run and artifact
   name. Cite any newly produced `mutants.md`; copy its contents unchanged if needed.
   The verified result also records `target_graph`: the target graph the run built for its own commit
   and gated (ADR-0035). That committed result is what lets CI accept `verdict: complete` after `main`
   has moved on. Keep raw logs out of git. Record the artifact's 30-day retention; retain a verified download until
   review is complete. Copy scores only from the actual mutation result, never calculate your own.

Cancellation checkpoints and partial logs are diagnostic evidence only. A hard-killed process can
leave `status: running`; it is still incomplete. No successful journal row is synthesized for a
killed gate. Failed setup may leave no artifact at all and is a blocker, not a successful empty run.
This lane does not add mutation-cache resume: if its own longer deadline is insufficient, preserve the
blocker and arrange a separately reviewed execution change rather than reporting partial shards.
The Auditor still performs independent capability/differential review and obtains the required
human flow sign-off before a complete verdict; a green workflow grants neither acceptance nor merge
approval.
