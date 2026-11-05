---
name: afs-setup-check
description: Verify the working environment before doing anything — source checkout present, pinned and read-only, target HEAD history complete, migration state valid, harness tools available, test services healthy, runtimes as declared. Use as the very first step of every role agent session; stop if any check fails.
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

# 2. Complete the current target checkout's HEAD ancestry before history-dependent validation.
# The Copilot setup workflow's fetch-depth does not guarantee this role checkout is complete.
shallow=$(git rev-parse --is-shallow-repository) || { echo "ERROR: cannot inspect target Git history"; exit 1; }
if [ "$shallow" = true ]; then
  git fetch --unshallow origin || { echo "ERROR: could not fetch complete HEAD ancestry from origin; setup is blocked"; exit 1; }
  shallow=$(git rev-parse --is-shallow-repository) || { echo "ERROR: cannot verify target Git history"; exit 1; }
fi
[ "$shallow" = false ] || { echo "ERROR: target checkout remains shallow; complete HEAD ancestry is required"; exit 1; }

# 3. Migration state valid (when .migration/ has content)
python .migration/harness/tools/validate.py .migration

# 4. Every input your ticket names exists (paste the ticket body; --ignore paths it asks you to create)
python .migration/harness/tools/check_inputs.py <<'TICKET'
<ticket body>
TICKET

# 5. Tools
.migration/harness/tools/afs-run --ticket <your ticket> --name setup-probe -- true   # your own journal, never a shared one
rtk --version

# 6. Test services up and healthy (profile `services`; setup steps started them from the compose file)
python .migration/harness/tools/afs-services check

# 7. Runtimes are the versions the profile declares (e.g. python-3.13 in target.stacks)
python .migration/harness/tools/check_runtime.py
```
Roles that do not read the source (e.g. Program Orchestrator, Planner) skip check 1. A failed check 7
means the session runs a different runtime than CI and the profile: stop, never run the gates on it. Roles that do not
run tests (Program Orchestrator, Planner, Analyst) skip check 6. If check 6 fails, try
`python .migration/harness/tools/afs-services up` once (it prints the services' logs on failure) —
starting the compose services is the setup step, not a workaround. Never start a database or other
service by hand, and never point tests at an in-memory or mocked stand-in instead. Never conclude an
input "is not present" without check 3: a missing named input is a stop, not an open question.

## Outcome
- **All pass:** state "setup OK" with the pinned SHA in one line, then continue.
- **Any fail:** do not work around it (do not clone the source yourself, do not edit `source.lock`,
  do not continue without the source). A history fetch/verification failure blocks state validation;
  write a blocking handoff (`afs-handoff`) that names the missing ancestry or access, then stop. Once
  resolved, restart setup from the beginning. If the source was writable, remove any probe file you
  created and report it.
