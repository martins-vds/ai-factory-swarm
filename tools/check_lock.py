#!/usr/bin/env python3
"""Check skills.lock.json, the pinned built-in skill menu.

Offline checks (always): structure, 40-char commits, known sources and roles, unique names, licenses in
the redistribution allow-list (or the skill marked `needs-license`), vendored skills present with a
PROVENANCE.md, patches present.
--remote: also verify, at each pinned commit, that every path exists upstream (needs git + network).

Exit 1 on errors; `needs-license` items are reported as warnings.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}
ROLES = {"program-orchestrator", "bootstrapper", "analyst", "characterizer", "planner", "slice-coordinator",
         "migrator", "specialist-migrator", "verifier", "auditor"}
INSTALL = {"upstream", "vendored", "harness"}
SHA = re.compile(r"^[0-9a-f]{40}$")


def path_exists_remote(repo, commit, path, cache):
    if repo not in cache:
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "fetch", "-q", "--depth", "1", "--filter=blob:none",
                        f"https://github.com/{repo}", commit], check=True)
        cache[repo] = d
    return subprocess.run(["git", "-C", cache[repo], "cat-file", "-e", f"{commit}:{path}" if path != "." else commit],
                          capture_output=True).returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lock", default=str(ROOT / "skills.lock.json"))
    ap.add_argument("--remote", action="store_true")
    a = ap.parse_args()
    lock = json.loads(pathlib.Path(a.lock).read_text(encoding="utf-8"))
    errors, warnings = [], []
    sources = lock.get("sources", {})

    for sid, s in sources.items():
        if not SHA.match(s.get("commit", "")):
            errors.append(f"source {sid}: commit must be a 40-char SHA")
        if not s.get("licenseEvidence"):
            errors.append(f"source {sid}: licenseEvidence is required")

    names = set()
    entries = [("skill", e) for e in lock.get("skills", [])] + [("plugin", e) for e in lock.get("plugins", [])]
    for kind, e in entries:
        name = e.get("name", "?")
        if name in names:
            errors.append(f"{kind} {name}: duplicate name")
        names.add(name)
        bad_roles_early = None
        if kind == "skill" and e.get("install") == "harness":
            if not (ROOT / e.get("path", "") / "SKILL.md").exists():
                errors.append(f"skill {name}: harness skill missing {e.get('path')}/SKILL.md")
            if not e.get("roles") or set(e.get("roles", [])) - ROLES:
                errors.append(f"skill {name}: roles must be non-empty and known")
            continue
        src = sources.get(e.get("source"))
        if src is None:
            errors.append(f"{kind} {name}: unknown source '{e.get('source')}'")
            continue
        bad_roles = set(e.get("roles", [])) - ROLES
        if not e.get("roles") or bad_roles:
            errors.append(f"{kind} {name}: roles must be non-empty and known (bad: {sorted(bad_roles)})")
        if kind == "skill" and e.get("install") not in INSTALL:
            errors.append(f"skill {name}: install must be one of {sorted(INSTALL)}")
        if src["license"] not in ALLOWED_LICENSES:
            if e.get("status") == "needs-license":
                warnings.append(f"{kind} {name}: source license '{src['license']}' — needs a license before shipping")
            else:
                errors.append(f"{kind} {name}: license '{src['license']}' is not redistributable; mark status needs-license or remove")
        if kind == "skill" and e.get("install") == "vendored":
            d = ROOT / "skills" / name
            for f in ("SKILL.md", "PROVENANCE.md", "LICENSE"):
                if not (d / f).exists():
                    errors.append(f"skill {name}: vendored copy missing skills/{name}/{f}")
        for p in e.get("patches", []):
            if not (ROOT / "patches" / p).exists():
                errors.append(f"{kind} {name}: patch patches/{p} not found")

    for t in lock.get("tools", []):
        if t.get("license") not in ALLOWED_LICENSES:
            errors.append(f"tool {t.get('name')}: license '{t.get('license')}' not allowed")

    if a.remote:
        cache = {}
        for kind, e in entries:
            src = sources.get(e.get("source"))
            if e.get("install") == "harness":
                continue
            if e.get("status") == "needs-license":
                warnings.append(f"{kind} {e['name']}: remote check skipped (unlicensed, possibly private source)")
                continue
            if src and not path_exists_remote(src["repo"], src["commit"], e["path"], cache):
                errors.append(f"{kind} {e['name']}: {e['path']} not found in {src['repo']}@{src['commit'][:7]}")

    for w in warnings:
        print("warning:", w)
    for err in errors:
        print("error:", err, file=sys.stderr)
    print(f"{len(entries)} entries, {len(sources)} sources: {len(errors)} error(s), {len(warnings)} warning(s)"
          + (" [remote paths verified]" if a.remote else ""))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
