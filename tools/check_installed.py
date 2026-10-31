#!/usr/bin/env python3
"""Check that the harness files bootstrap installed in a target repo are unchanged (drift check).

Usage (from the target repo root):
  python .migration/harness/tools/check_installed.py [--root .]

Reads `.migration/harness/installed.json`, written by the harness's `tools/bootstrap.py`, and
recomputes the hash of every installed file: role agents, skills, hook, harness tools and schemas.
Exits 1 on any edited, missing or unexpected file, with one line per problem. Harness files are
changed by re-running bootstrap from a new harness version, never by hand (ADR-0003).
Standard library only.
"""
import argparse
import hashlib
import json
import pathlib
import sys

MANIFEST = ".migration/harness/installed.json"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_files(root, rel):
    base = root / rel
    if base.is_file():
        return [rel]
    return sorted(str(p.relative_to(root)) for p in base.rglob("*") if p.is_file())


def check(root):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    problems = []
    for entry in manifest["entries"]:
        rel = entry["path"]
        expected = entry["files"]
        if not (root / rel).exists():
            problems.append(f"missing: {rel}")
            continue
        actual = {f: file_hash(root / f) for f in tree_files(root, rel)}
        for f, h in expected.items():
            if f not in actual:
                problems.append(f"missing: {f}")
            elif actual[f] != h:
                problems.append(f"edited: {f}")
        for f in sorted(set(actual) - set(expected)):
            problems.append(f"unexpected: {f}")
    return manifest, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    manifest, problems = check(pathlib.Path(a.root))
    for p in problems:
        print(p)
    n = sum(len(e["files"]) for e in manifest["entries"])
    print(f"harness {manifest['harness_version']} ({manifest['harness_commit'][:7]}): "
          f"{len(manifest['entries'])} entries, {n} files, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
