# Patches

Patches applied to pinned third-party skills and plugins after install (see `skills.lock.json`). Each is a
`git apply`-able diff relative to the upstream repository root at the pinned commit.

| Patch | Upstream | Why |
|---|---|---|
| `understand-anything/argument-hint.patch` | Egonex-AI/Understand-Anything @ `4e6d329` | The `understand` skill's `argument-hint` is a YAML list; under GitHub Copilot the skill silently fails to load (spike M1-1). Rewrites it as a string. Report upstream and drop the patch once fixed. |
