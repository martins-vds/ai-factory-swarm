#!/usr/bin/env python3
"""Seed a synthetic target with the legacy Lending Library (ADR-0037).

  seed.py --target <clone of the synthetic target repo> [--source legacy|legacy-billing|legacy-reports] [--update]

--update replaces an already seeded source with the harness copy, for when the legacy app gains a feature.
That is a source change: commit it in its own PR (with `legacy-smoke.yml` for the legacy source), then
re-pin `.migration/source.lock` to the merge commit in a follow-up setup PR, which rebuilds the source
graph (ADR-0019). Never hand-copy files: a partial copy pins a source no harness CI has built.

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
    ap.add_argument("--update", action="store_true",
                    help="replace an already seeded source with the harness copy (the legacy app changed)")
    a = ap.parse_args(argv)
    dest = a.target / a.source
    if dest.exists() and not a.update:
        print(f"{dest} already exists; it is rewritten only by --update, as a source change with its own re-pin",
              file=sys.stderr)
        return 1
    if a.update and not dest.exists():
        print(f"{dest} was never seeded; seed it without --update", file=sys.stderr)
        return 1
    if a.update:
        shutil.rmtree(dest)
    shutil.copytree(HERE / a.source, dest)
    if a.update and a.source == "legacy":
        shutil.copy2(HERE / "legacy-smoke.yml", a.target / ".github/workflows/legacy-smoke.yml")
    verb = "updated" if a.update else "seeded"
    print(f"{verb} {dest}. Commit and push it in its own PR; after it merges, pin it in .migration/source.lock:")
    print("  repo: <owner>/<synthetic target repo>\n  sha: <that merge commit>\n  path: " + a.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
