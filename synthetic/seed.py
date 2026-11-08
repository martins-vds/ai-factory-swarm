#!/usr/bin/env python3
"""Seed a synthetic target with the legacy Lending Library (ADR-0037).

  seed.py --target <clone of the synthetic target repo>

Copies `synthetic/legacy/` to `<target>/legacy/` and `synthetic/scenarios.yaml` to
`<target>/legacy/SCENARIOS.yaml`, then prints the `source.lock` lines to pin it once that commit is pushed
(the source is the target repo itself, path `legacy`). It writes no `.migration/` state: bootstrap and the
role sessions do that, as on any target. Standard library only.
"""
import argparse
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", required=True, type=pathlib.Path)
    a = ap.parse_args(argv)
    dest = a.target / "legacy"
    if dest.exists():
        print(f"{dest} already exists; the legacy source is pinned once and never rewritten", file=sys.stderr)
        return 1
    shutil.copytree(HERE / "legacy", dest)
    shutil.copyfile(HERE / "scenarios.yaml", dest / "SCENARIOS.yaml")
    print(f"seeded {dest}. Commit and push it, then pin it in .migration/source.lock:")
    print("  repo: <owner>/<synthetic target repo>\n  sha: <that commit>\n  path: legacy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
