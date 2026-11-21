# End-to-end eval (ADR-0041)

These are real tickets from the pilot and synthetic runs, each with a known correct outcome. They are re-run on
fresh Copilot sessions against the harness under test, and the results are compared run by run.

## Cases

`cases/<id>.yaml`: one ticket each. `python tools/afs-eval list` prints them.

| Kind | What a pass needs |
|---|---|
| `migrator` | The agent's PR has green Gates in CI, its return's `mutation_changed` meets the profile threshold, and validation shows no error the case branch didn't already have |
| `verifier` (defect) | Verdict `changes-required`, and at least one finding at or above `severity_min` that names the real defect (a keyword in `any_of`, or a path prefix in `where`). Each defect was found by the live Verifier and fixed before merge |
| `verifier` (clean) | Verdict `pass`, with no blocker or major finding. These stop a configuration from passing by rejecting everything |
| `bootstrap` | The listed profile and checklist fields have their live values |
| `acceptance` | A slice acceptance: the return's acceptance fields (slice, `human_check: requested`, gates all green, the run's mutation score), an evidence report that states the run's results, and a ticket reconciliation with one final disposition for every descendant. Graded the same for the orchestrator's `acceptance` block and a retired Slice Coordinator's return (ADR-0050) |

**Must-pass cases.** Every case is `must_pass` except the bootstrap case, which is tracked only: its live
session ran before the harness was installed. Its `harness_copy` puts the agent and harness skills under
test on the branch, as bootstrap would (ADR-0046).

**Normalization.** A case's `normalize` edits make an old commit valid under today's rules, using the fixes
the live run made later. They never change behavior. A case that couldn't be normalized without rewriting
history was left out; the ADR lists those.

## Running an eval

```sh
H=/path/to/ai-factory-swarm   # a checkout on origin/main (or --allow-unreleased for a topology experiment)
R=2026-11-15-baseline-r1
E=martins-vds/ai-factory-eval
python $H/tools/afs-eval prepare  --run $R --eval-repo $E --harness $H
python $H/tools/afs-eval dispatch --run $R --eval-repo $E
# … sessions finish (each PR leaves [WIP]) …
python $H/tools/afs-eval grade    --run $R --eval-repo $E
python $H/tools/afs-eval report   --results evals/results/$R.json --baseline evals/results/<baseline>.json
```

**Repeats.** Run each case at least twice, as runs `…-r1` and `…-r2`. The first baseline's report compares
r2 with r1, which shows how much the cases vary on their own.

**Comparisons.** Compare only against a baseline taken with the same Copilot model. Each results file records
when it was graded.

**Deciding on a change.** Use `compare` with all the runs of both variants:

```sh
python $H/tools/afs-eval compare --runs evals/results/$R-r{1,2,3}.json --baseline evals/results/<base>-r{1,2,3}.json
```

It judges every case by majority of its runs. It exits 1 when a case that passes by majority in the baseline
fails by majority now: the rule ADR-0041 and ADR-0042 apply.

Beside each case it shows the median model requests, output tokens and minutes, with the change from the
baseline. These come from the sessions' cost records. The coding agent records no input tokens, so no cost in
money is computed. Usage informs a person's call; it never decides one.

**What the eval can't measure yet.** `coverage` lists the role chains the live targets used, one per ticket,
from their returns, and the roles that have no case:

```sh
python $H/tools/afs-eval coverage --target /path/to/pilot --target /path/to/synthetic
```

Run it before changing a role. A change to a role without a case can't be measured until a case covers it.
A case runs one session, so even a chain whose roles all have cases can drop a handoff unseen.

**Phase 4a (Verifier or not).** `chain --from-run M --run V` starts a Verifier on each finished Migrator PR of run
M. `oracle --run M` adds hidden ground truth to M's graded results: the layering and UI tools, plus the case's
`oracle.forbid_calls` and `oracle.forbid_stripped_args` (a stripped value stored, or a Django form field that
strips by default). Chaining from a B run (`chain --from-run <B run>`) audits B's heads with a Verifier that is
not part of B. `evals/variants/` holds the configuration-B agent (`afs-migrator-selfverify`), which is
copied to the eval repo only.

**Which roles to merge.** `coupling` reads the live targets' return history. Each slice is one trace, with
its roles in the order they first committed a return (`--by ticket` makes each ticket a trace instead):

```sh
python $H/tools/afs-eval coupling --target /path/to/pilot --target /path/to/synthetic
```

It shows how many traces each role appears in. It flags a pair as a merge candidate when one role follows the
other in most traces that hold the rarer of the two. Some pairs follow by design, such as the Migrator and
Verifier under ADR-0040: read each candidate against the ADR that set its order.

`compare`, `coverage` and `coupling` adapt three scripts from Anthropic's
[single-agent-loop kit](https://github.com/anthropics/single-agent-loop-kit) (Apache-2.0): `compare.py`,
`chain_coverage.py` and `coupling_map.py`. The kit's eval runner and reference loop drive an agent built on the
API; ours are Copilot custom agents, so those parts don't fit.

## The eval repository's `main`

Copilot reads custom agents and `copilot-setup-steps.yml` from the default branch. So the eval repository's
`main` carries the `.github/` that the harness under test installs:
- copy it from any prepared case branch;
- merge it through a PR, as the ruleset requires;
- update it whenever the harness under test changes its agents, skills or setup steps.

`prepare` refuses to run while `main`'s agents differ from the harness under test or its `evals/variants/`
(ADR-0058). `--allow-agent-drift` overrides it for a run that means to measure other agents.

Each case branch merges `main` with `-s ours`, which leaves its own tree intact. So `main`'s content never
leaks into a case.

## When `main` moves during a run

Don't change `main` while a run is in progress. If it does move, every case branch loses `main` as an
ancestor, `check_stack_base.py` fails, and CI skips every other job. Baseline r1 hit this when the snapshot
workflow merged mid-run. To recover, run `afs-eval refresh --run R --eval-repo E`. It re-chains main → case →
work → each finished agent PR, as ADR-0038's stack refresh does. Run it again for PRs that finish later.

## Sessions that hit the time limit

The platform cancels a Copilot session after about an hour. Its PR keeps `[WIP]` and has no return file.
`grade` reads the session's run and reports `session-timed-out`, which counts as a fail.

## Changed code is measured from the case base

`afs-mutation` diffs against `$AFS_BASE`, falling back to `origin/main`. The eval repo's `main` is unrelated
to every case, so its Copilot setup steps set `AFS_BASE` to the case's prepared base commit (the
`Eval case <id>: base at …` commit), and only the agent's changes count as changed code. Baselines r1 and r2
ran without this and are confounded.

## Data cases

Data tickets (`specialty: data`) start from the newest **AFS data snapshot** artifact. Run that workflow once
in the eval repository, on a prepared pilot data case branch, before dispatching those cases. Otherwise the
setup step only warns, and the agent works without a snapshot.

## Results

`results/<run>.json` holds the graded run. `results/<run>.state.json` holds the issue, the work PR and the base
branch of each dispatched case. Commit both, together with the report, in the PR that cites them.
