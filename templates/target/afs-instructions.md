<!-- afs-instructions v1 -->
# AI Factory Swarm — migration rules

This repository is the **target** of a code migration run by AI Factory Swarm. These rules apply to
every session; role-specific guidance lives in `.github/agents/afs-*.agent.md`.

- **Fidelity contract:** preserve observable behavior, re-architect freely behind it, surface every
  quirk to a human. Load the `afs-migration-contract` skill before migration work.
- **Setup first:** run the `afs-setup-check` skill before anything else; stop if it fails.
- **Source is read-only** and pinned (`.migration/source.lock`). Remote sessions find it in `.source/`;
  never edit, commit or re-clone it.
- **One ticket per session.** Keep context under the working budget in `.migration/profile.yaml`;
  near the soft limit, write a handoff (`afs-handoff`) and stop.
- **Shell output:** use `rtk` for shell commands as the RTK block below says. For gate runs (build,
  tests, CRAP, mutation) use `.migration/harness/tools/afs-run`, which keeps the full log and prints a
  summary. If this block and the RTK block disagree, this block wins.
- **Harness files are pinned:** do not edit `.github/agents/afs-*`, `.github/skills/`,
  `.github/hooks/rtk-rewrite.json` or `.migration/harness/`; `check_installed.py` fails CI on drift.
<!-- /afs-instructions -->
