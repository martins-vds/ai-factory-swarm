---
name: afs-setup-check
description: Verify the working environment before doing anything — source checkout present, pinned and read-only, migration state valid, harness tools available, test services healthy. Use as the very first step of every role agent session; stop if any check fails.
---

# Setup check (ADR-0008)

A failed setup step does **not** stop a Copilot coding agent session — it just continues without, for
example, the source (spike M1-2). So every role agent checks its own setup first.

## Checks (run all; quote results compactly)
```bash
# 1. Source present, pinned, read-only (remote workers: .source/; local: path in your task)
test -d .source && git -C .source rev-parse HEAD
awk '/^sha:/{print $2}' .migration/source.lock          # must equal the HEAD above
touch .source/.afs-write-probe 2>/dev/null && echo "WRITABLE" || echo "read-only"
git check-ignore -q .source && echo "ignored"            # .source must never be committed

# 2. Migration state valid (when .migration/ has content)
python .migration/harness/tools/validate.py .migration

# 3. Every input your ticket names exists (paste the ticket body; --ignore paths it asks you to create)
python .migration/harness/tools/check_inputs.py <<'TICKET'
<ticket body>
TICKET

# 4. Tools
.migration/harness/tools/afs-run --ticket <your ticket> --name setup-probe -- true   # your own journal, never a shared one
rtk --version

# 5. Test services up and healthy (profile `services`; setup steps started them from the compose file)
python .migration/harness/tools/afs-services check
```
Roles that do not read the source (e.g. Program Orchestrator, Planner) skip check 1. Roles that do not
run tests (Program Orchestrator, Planner, Analyst) skip check 5. If check 5 fails, try
`python .migration/harness/tools/afs-services up` once (it prints the services' logs on failure) —
starting the compose services is the setup step, not a workaround. Never start a database or other
service by hand, and never point tests at an in-memory or mocked stand-in instead. Never conclude an
input "is not present" without check 3: a missing named input is a stop, not an open question.

## Outcome
- **All pass:** state "setup OK" with the pinned SHA in one line, then continue.
- **Any fail:** do not work around it (do not clone the source yourself, do not edit `source.lock`,
  do not continue without the source). Write a handoff (`afs-handoff`) with the failing check and
  stop. If the source was writable, remove any probe file you created and report it.
