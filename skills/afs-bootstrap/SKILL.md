---
name: afs-bootstrap
description: How the Program Orchestrator prepares a target repo for a migration at intake — detect the stacks, decide the characterization tier from evidence, write the capability checklist and the profile, have the dispatcher install the harness, scaffold, build the source graph, validate and open the setup PR. Load it at intake (orchestrator step 1). Replaces the former Bootstrapper role (ADR-0046).
---

# Bootstrap: prepare the target (Phase 0)

You prepare the target repo so the migration can start safely. Bootstrap is deliberately **not** fully
automatic: anything you can't cover becomes an operator ticket. This skill replaces the former Bootstrapper
role (ADR-0046); the orchestrator runs it at intake, after writing `.migration/source.lock`.

**The harness isn't installed yet.** `afs-setup-check`'s checks 3–7 need `.migration/harness/`, which step 5
installs: before that, run only its history check (and the source check when the source is checked out),
then go on. A missing harness at intake is the starting state, not a blocker (eval 2b-r1/r2 stopped on it).

## Skills this procedure loads (only when the step needs it)
- `setup-matt-pocock-skills`: tracker, labels and domain-doc layout (the operator invokes it).
- `find-skills`: look for a skill that covers a stack-specific capability.
- `skill-creator`: when the operator decides to write a missing skill.
- `self-learning`: research an unfamiliar technology into a skill.
- `architecture-patterns`: target layout and architecture ADR scaffolding.
- `docker-expert`, `multi-stage-dockerfile`, `docker-compose-orchestration`: containers and test services.

## Procedure
1. **Detect stacks** from build files and a quick scan: languages, frameworks, build tools, data stores,
   UI technology, integrations, source encoding.
2. **Characterization tier.** Is a legacy environment running (tier A)? If not, **try the tier-B recipe
   before anything else**: a full build that fails on a private or missing dependency is the case tier B
   exists for. Compile only what the source's own tests (or the units you would test) reach, e.g.
   `javac -sourcepath <src> -implicit:class <tests>` with public test jars, and run what compiles. Code
   that compiles and runs that way is tier B, even if the app as a whole never can. Tier C only when that
   attempt fails, or there is no code. Record the commands and results
   (`afs-migration-contract` → references/characterization.md). For tier C, `characterization.tier_b_attempt`
   in `capabilities.yaml` is required: `"ran: <command> -> <result>"` or `"no code: <what the source
   contains>"`. The schema and `validate.py` reject a tier C without it.
3. **Capability checklist.** For each required capability (build-run, characterization harness, tests,
   coverage, complexity, CRAP, mutation testing, lint/format, stack idioms, data migration, UI end-to-end,
   code graph, **graph data links** (a harness enricher for the stack, ADR-0020; none = `gap`), output
   filtering) and for source and target: find a provider in the built-in menu, then with `find-skills`.
   Write `.migration/capabilities.yaml`. Every unmet capability → an operator ticket (status `gap`).
   Source CRAP and coverage are `best_effort`.
4. **Profile.** Write `.migration/profile.yaml` from the harness template: stacks, tier, graph commit,
   patches, `graph.enrich` and `graph.require` (copy the stack pack's `graph` block; bootstrap refuses a
   profile without them), risk-map exclusions (vendored/minified/generated code), stack skills, gate
   commands, thresholds (defaults unless the operator says otherwise), concurrency, context budgets, RTK
   edition, `layering` contracts from the architecture ADRs and, with a UI, `ui_checks` (ADR-0043).
   **With a data stack, write the test services now** (step 6's Test services paragraph): the profile's
   `services` is required when `target.stacks.data` is set, and it must name a `compose.yaml` that exists.
   Every CI job and Copilot setup step starts those services, so bootstrap refuses to install a profile
   whose compose file is missing.
5. **Install.** The dispatcher runs this step: the Copilot coding agent may not change `.github/agents/`,
   so in a cloud session you stop after steps 1–4, commit the profile and checklist, and hand off. The
   dispatcher runs the harness's `tools/bootstrap.py` from a checkout at the release being installed:
   `--target <clone> --profile <profile> --capabilities <checklist> --stack-pack stacks/<pack>.json
   --create-gap-issues`. A new gap gets `ticket: new`, and bootstrap opens its operator issue. Keep
   `ticket` when the gap is later met or waived: the harness closes that issue from main. Bootstrap
   installs pinned role agents, skills, harness tools and schemas (with `installed.json`), RTK's hook,
   both instruction blocks, `copilot-setup-steps.yml` and the `afs-harness-check.yml` CI. Never hand-edit
   those files; re-run bootstrap.
6. **Scaffold the target** per the architecture ADRs: layout, CI running the gates, lint/format, test
   runner with project-wide test isolation (listed in `target.shared_test_files`), coverage, CRAP and
   mutation tooling, containers.
   **Test services:** write the target's `compose.yaml` with `docker-compose-orchestration` (images with
   `docker-expert`, Dockerfiles with `multi-stage-dockerfile`; never by hand). It defines every real
   service the tests need (the database from `target.stacks.data`, brokers, stand-ins for external
   systems), each with a healthcheck, credentials that match the target's default settings, and ports
   bound to `127.0.0.1`. Record it in the profile's `services` (`compose`, `test`), then confirm
   `afs-services lint` and `afs-services up` pass and the test gate runs against it. Agents never test
   against mocks where a real service exists.
   The setup PR must be complete when it's opened (profile, checklist, test services) and merged before
   any Copilot session runs: Copilot's setup steps come from the default branch only, and a session based
   on the unmerged setup branch has no RTK, so the RTK pre-tool hook blocks every tool call. Fix a setup
   PR from the dispatcher's clone, never in a session.
7. **Graph first (ADR-0020).** Once the setup PR is merged, the dispatcher runs the afs-understand
   workflow with `side=source` on `main` and merges its PR. `python .migration/harness/tools/graph_gate.py
   --side source --require-graph` must pass before any analysis or planning. Review its entry-point report
   with the operator; a page that should reach data and doesn't is an enricher gap to fix in the harness.
8. **Validate** (`python .migration/harness/tools/validate.py .migration`) and open the **setup PR**,
   with the operator checklist from `docs/operator-setup.md` (bootstrap prints it) as unchecked boxes.

## Rules
- Never mark a capability `met` without naming what provides it; never `waived` without a human.
- Never install a skill or tool outside `skills.lock.json` or the profile without recording it.
- Record the outcome in your orchestrator return (`phase: 0`): the setup PR under `awaiting_human`, each
  gap ticket, and the tier with its evidence in `decisions`. The tier proof itself lives in
  `capabilities.yaml`, where `validate.py` checks it.
