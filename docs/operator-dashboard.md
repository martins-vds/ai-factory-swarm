# Operator dashboard

Open the **Operator dashboard** canvas (`operator-dashboard`) in a Copilot session
for this repository. The project extension only reads and links: it cannot
approve runs, merge PRs, assign agents, cancel work, or sign off on a slice.

On the machine running the extension, install Python 3 and sign in to `gh` with
an account that can read the pilot target, synthetic target, eval, and swarm
repositories. The canvas refreshes remote sessions about every two minutes
and Needs about every ten minutes while visible. All GitHub requests are made
by the local generator using `gh api`; the browser never receives a token.
Cold refreshes may take longer in repositories with many assigned issues.
The canvas keeps the last successful data visible when a refresh fails.

Generate the eval snapshots from a harness checkout with the eval results,
case catalog, and `tools/check_plan.py`. For coverage, install PyYAML and the
planner's dependencies, and pass the live target checkouts that contain
`.migration/returns`:

```bash
mkdir -p .afs-dashboard
tools/afs-dashboard trend \
  --eval-root /path/to/eval-enabled-harness \
  --target /path/to/ai-factory-pilot-target \
  --target /path/to/ai-factory-synthetic-target \
  --out .afs-dashboard/trend.json
```

Omit `--target` for trend and case results alone. Use `--results` if the graded
files are outside `<eval-root>/evals/results`. The canvas reads
`trend.json`, `trend-cases.json`, and `trend-coverage.json` from `.afs-dashboard/`.
That directory is ignored by Git.

`tools/afs-dashboard needs` and `tools/afs-dashboard sessions` accept one
`--repo OWNER/REPO` per repository and `--out`. Use `.afs-dashboard/needs.json`
or `.afs-dashboard/sessions.json` for local fallback snapshots. **Generator &
input** shows the command, source, and generation time. Sessions become stale
after five minutes; other datasets become stale after one hour.

The session list uses open Copilot-linked `[WIP]` PRs and currently assigned
issues without a PR. Finished sessions require a recorded title change out of
`[WIP]` or a close time on a PR whose title no longer starts with `[WIP]`.
GitHub REST does not always return an agent or ticket explicitly; the collector
also checks the issue's dispatch text and leaves unknown fields blank.

## Executable acceptance spec

The [Gherkin features](../tests/dashboard-bdd/features/) are the dashboard's
acceptance contract. Cucumber runs them against the real `afs-dashboard` CLI
and canvas in Chromium. A local `gh` double serves GitHub REST fixtures and
rejects writes; no GitHub credentials or network calls are needed for the scenarios.
The **Operator dashboard acceptance** job runs the same suite on pull requests.

```bash
python3 -m pip install pyyaml
cd tests/dashboard-bdd
npm ci
npx --no-install playwright install --only-shell chromium
npm test
```
