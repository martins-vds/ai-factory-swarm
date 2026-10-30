# M1 spikes — run book

Three spikes that test the assumptions the rest of the design depends on (see [roadmap](../../roadmap.md)).
Each one ends with a short findings file in this folder: `spike-1-graph.md`, `spike-2-remote-agent.md`,
`spike-3-crap-mutation.md`.

**Why they run on your machine:** the cloud workspace these were prepared in cannot reach npm, PyPI or
Maven Central, so it cannot build Understand Anything or run JaCoCo/PIT/mutmut. The scripts in
[`tools/spikes/`](../../tools/spikes/) use only the Python standard library and were tested there.

Source: [code-migration-hackathon](https://github.com/martins-vds/code-migration-hackathon) `main`
@ `c2df760`, folder `java/`.

---

## Spike 1 — What does the Understand Anything graph capture?

**Question:** does the graph contain what the ledger and slice planner need (endpoints/screens, tables,
services, domain flows, `tested_by`), and can we trace a screen to its data end to end? What does a
targeted run cost?

**Slice:** the *currency* admin screen — `admin/currency.jspx` → 4 JSF beans → service layer → `Currency`
JPA entity. 29 classes (depth 2), ~3,700 lines, plus the page and a trimmed `admin-config.xml`
(5 of 206 managed beans).

```bash
# 1. Extract the slice (original paths preserved; MANIFEST.txt lists every file)
python3 tools/spikes/extract_slice.py --root <hackathon>/java --out ~/spikes/currency-slice --depth 2 \
  --seed Currency --seed CurrencyTableModel --seed CurrencyTableBean --seed CurrencyBean --seed CurrencyFormBean \
  --extra toolkit-web/src/main/webapp/admin/currency.jspx \
  --faces-config toolkit-web/src/main/webapp/WEB-INF/admin-config.xml --bean-prefix currency
cd ~/spikes/currency-slice && git init -q && git add -A && git commit -qm "currency slice @ c2df760"

# 2. In Claude Code (or VS Code / Copilot CLI) with the Understand Anything plugin:
#    /understand ~/spikes/currency-slice
#    /understand-domain ~/spikes/currency-slice
#    Note wall-clock time and, if visible, tokens/cost.

# 3. Check the result
python3 tools/spikes/check_graph.py ~/spikes/currency-slice/.ua/knowledge-graph.json \
  --domain ~/spikes/currency-slice/.ua/domain-graph.json \
  --anchor currency.jspx --anchor CurrencyTableBean --anchor CurrencyFormBean > docs/spikes/m1/spike-1-graph.md
```

(The data folder may be `.understand-anything/` instead of `.ua/` on older plugin versions.)

**Record in the findings:** time and cost; whether `currency.jspx` became a `screen`/`page` node; whether
the JPA entity became a `table` node; whether an anchor → table path exists; whether the domain graph
produced a flow for "manage currencies"; anything wrong or missing. Commit the two JSON files next to the
findings so the result can be re-checked.

**Decision it informs:** ADR-0009 (Understand Anything as the single graph tool). If screens or tables are
missing, the Analyst needs an enrichment step, or the decision is revisited.

---

## Spike 2 — Can a remote worker use a read-only, pinned source?

Prepared in [ai-factory-pilot-target](https://github.com/martins-vds/ai-factory-pilot-target): a
`copilot-setup-steps.yml` that checks the source out read-only into `.source/` at the pinned SHA, and an
`afs-spike-probe` custom agent that runs six checks and reports through a PR. Steps are in that repo's
README (create a read-only token, add it to the `copilot` environment, run the setup workflow, create an
issue, assign it to Copilot with the probe agent).

**Record:** the probe's report, time to PR, and anything the setup needed that the design doesn't say.

**Decision it informs:** ADR-0008 (remote dispatch via the Copilot coding agent; agents in the target repo).

---

## Spike 3 — Do CRAP and mutation tooling work on legacy and target code?

**Questions:** (a) can we produce a CRAP risk map of legacy Java with no usable tests? (b) with coverage?
(c) does mutation testing run on a Python/Django target stub in reasonable time?

`crap.py` is language-agnostic: complexity from [lizard](https://github.com/terryyin/lizard) (≈20
languages), coverage from LCOV and/or JaCoCo XML, or none.

```bash
pip install lizard

# (a) Source risk map without tests — CRAP reduces to a complexity ranking (ADR-0013)
lizard --csv <hackathon>/java > /tmp/lizard.csv
python3 tools/spikes/crap.py /tmp/lizard.csv --top 30 --csv /tmp/crap-source.csv > /tmp/risk-map.md

# (b) With coverage, if the legacy build runs: add the JaCoCo plugin, run whatever tests exist
#     (mvn -q jacoco:prepare-agent test jacoco:report), then:
python3 tools/spikes/crap.py /tmp/lizard.csv --jacoco <module>/target/site/jacoco/jacoco.xml > /tmp/risk-map-cov.md

# (c) Target gate on a small Python stub (any Django app with a few tests)
pip install coverage mutmut
coverage run -m pytest && coverage lcov -o coverage.lcov
lizard --csv src > lizard.csv && python3 tools/spikes/crap.py lizard.csv --lcov coverage.lcov --max 30
mutmut run && mutmut results
```

**Record:** whether the legacy build runs at all (it may not — that is a finding, and ADR-0013 says the
risk map never blocks); top hot spots; whether the currency slice shows up hot; mutation run time and
score on the stub.

**Decisions it informs:** ADR-0011 (CRAP and mutation gates), ADR-0013 (source risk map).

---

## Spike 4 (M1-d) — Can we keep tool output out of agents' context?

**Questions:** how much do RTK's filters shrink real pilot output (Maven build/test, pytest, git)? Does
a Copilot `preToolUse` hook reliably deny unbounded commands and steer the agent to the wrapper? Does
Headroom help a local agent without hurting accuracy?

```bash
# RTK (single binary; see https://github.com/rtk-ai/rtk for install options)
rtk --version
rtk test mvn -q test          # in a pilot module that builds; compare with the raw output size
rtk err mvn -q package
rtk pytest                    # on the Python stub from spike 3
rtk gain                      # tokens saved

# Copilot hook (in ai-factory-pilot-target, on a branch): add .github/hooks/afs-output.json with a
# preToolUse hook that denies e.g. `mvn test` / `pytest` / `cat` of files > 200 lines unless wrapped,
# returning a reason that says "use afs-run". Then give the probe agent a task that tempts a raw run.
```

**Record:** raw vs filtered sizes per command; whether failures stay fully diagnosable from the summary
plus the saved log; whether the hook was honored (and whether it can rewrite, or only deny); Headroom
results if tried.

**Decision it informs:** ADR-0015 (which layers become mandatory).
