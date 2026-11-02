# ADR-0016: Test services from one compose file

- Status: Accepted
- Date: 2026-11-02

## Context
The migration skill (`migrating-java-to-django`) requires integration tests against **real** services,
the database and any external system, provided by Docker Compose, with no mocks where a real service is
available. The harness pinned the Docker skills for the Bootstrapper but never required a compose file.
So the pilot had none. CI hard-coded its own PostgreSQL service, and Copilot coding-agent sessions had no
database at all. In M5, TC-15b could not run the database tests it wanted as evidence and finished
anyway, relying on CI.

Options considered:
- **A database in the profile** (engine, version, credentials) that setup steps start. This duplicates
  what CI defines, covers only databases, and doesn't help the human run the app.
- **Actions `services:` in `copilot-setup-steps.yml`.** Supported, but it is a second copy of CI's
  definition and has no local equivalent.
- **Testcontainers** (tests start their own containers). Self-contained, but every pytest run starts a
  container, and the mutation gate runs pytest once per mutant.
- **One compose file in the target**, started everywhere by one tool.

## Decision
- The target owns `compose.yaml`, written by the Bootstrapper with the Docker skills. It defines every
  real service the tests need, each with a healthcheck, with credentials matching the target's default
  settings and ports bound to `127.0.0.1`. A slice that needs a new service adds it to the same file.
- The profile names it: `services: {compose, test, env?}`. It is required when `target.stacks.data`
  is set.
- `tools/afs-services` is the only way services are started or checked:
  - `up`: `docker compose up -d --wait` for `services.test`, plus `env` exported via `$GITHUB_ENV`;
  - `check`: running and healthy;
  - `lint`: the file defines each test service with a healthcheck.
- Copilot setup steps and the CI gates both run `afs-services up`. The CI harness job runs `lint`.
  `afs-setup-check` runs `check`.
- Contract: tests an agent's work depends on that cannot run in its session are a **stop**. "CI will run
  them" is not evidence, and mocks or in-memory stand-ins never replace a real service.

## Consequences
- Agent sessions, CI and the human's machine test against the same services. Drift between them is
  impossible by construction.
- Mutation shards share one server and use per-shard databases (`POSTGRES_DB` suffix). The compose
  user must be able to create databases; the official images' default superuser can.
- Image pulls in setup steps rely on registry access from the runner. If the Copilot firewall blocks
  them, the registry goes on its allowlist (operator checklist).
