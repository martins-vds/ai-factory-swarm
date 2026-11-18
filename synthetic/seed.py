#!/usr/bin/env python3
"""Seed a synthetic target with the legacy Lending Library (ADR-0037).

  seed.py --target <clone of the synthetic target repo> [--source legacy|legacy-billing|legacy-reports]

Copies `synthetic/<source>/` to `<target>/<source>/` (default `legacy`), then prints the `source.lock` lines to pin it once that commit is pushed
(the source is the target repo itself, path `<source>`). It writes no `.migration/` state: bootstrap and the
role sessions do that, as on any target. The legacy app carries no hint of its scenarios: the
agents must reach every outcome from what they observe (on the first run, a Bootstrapper read the catalog
and cited it as its evidence). Standard library only.
"""
import argparse
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
SOURCES = ("legacy", "legacy-billing", "legacy-reports")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", required=True, type=pathlib.Path)
    ap.add_argument("--source", default="legacy", choices=SOURCES,
                    help="which legacy source to seed; each gets its own Bootstrapper session (one tier per source)")
    a = ap.parse_args(argv)
    dest = a.target / a.source
    if dest.exists():
        print(f"{dest} already exists; the legacy source is pinned once and never rewritten", file=sys.stderr)
        return 1
    shutil.copytree(HERE / a.source, dest)
    print(f"seeded {dest}. Commit and push it, then pin it in .migration/source.lock:")
    print("  repo: <owner>/<synthetic target repo>\n  sha: <that commit>\n  path: " + a.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
