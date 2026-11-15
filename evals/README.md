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

**Must-pass cases.** Every case is `must_pass` except the bootstrap case, which is tracked only: its live
session ran before the harness was installed.

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

## The eval repository's `main`

Copilot reads custom agents and `copilot-setup-steps.yml` from the default branch. So the eval repository's
`main` carries the `.github/` that the harness under test installs:
- copy it from any prepared case branch;
- merge it through a PR, as the ruleset requires;
- update it whenever the harness under test changes its agents, skills or setup steps.

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

## Data cases

Data tickets (`specialty: data`) start from the newest **AFS data snapshot** artifact. Run that workflow once
in the eval repository, on a prepared pilot data case branch, before dispatching those cases. Otherwise the
setup step only warns, and the agent works without a snapshot.

## Results

`results/<run>.json` holds the graded run. `results/<run>.state.json` holds the issue, the work PR and the base
branch of each dispatched case. Commit both, together with the report, in the PR that cites them.
