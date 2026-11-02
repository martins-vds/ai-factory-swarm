#!/usr/bin/env python3
"""Check that the runtimes on PATH are the versions the profile's target stacks declare (ADR-0018).

Reads `target.stacks.*` from the profile and checks each entry that names a runtime with a version:

  python-3.13   → `python --version` is 3.13.x
  node-22       → `node --version`   is 22.x
  java-21       → `java -version`    is 21.x

Other stack entries (frameworks, databases) are ignored: the compose services pin those.
Exit 1 with one line per mismatch or missing runtime. Bootstrap writes the same Python version into
the Copilot setup steps and CI, so a mismatch here means the environment drifted from the profile.

Usage: check_runtime.py [--profile .migration/profile.yaml]
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

RUNTIMES = {
    "python": (["python", "--version"], r"Python (\d+(?:\.\d+)*)"),
    "node": (["node", "--version"], r"v(\d+(?:\.\d+)*)"),
    "java": (["java", "-version"], r'version "(?:1\.)?(\d+(?:\.\d+)*)'),
}
STACK = re.compile(r"^(python|node|java)-(\d+(?:\.\d+)?)$")


def declared(profile):
    """[(runtime, version)] from target.stacks, e.g. [("python", "3.13")]."""
    stacks = ((profile.get("target") or {}).get("stacks") or {})
    out = []
    for entries in stacks.values():
        for entry in entries or []:
            m = STACK.match(str(entry).strip().lower())
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def python_version(profile, default="3.12"):
    """The Python version bootstrap writes into the generated workflows."""
    return next((v for rt, v in declared(profile) if rt == "python"), default)


def actual(runtime):
    cmd, pattern = RUNTIMES[runtime]
    if shutil.which(cmd[0]) is None:
        return None
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(pattern, r.stdout + r.stderr)
    return m.group(1) if m else None


def matches(want, got):
    return got is not None and (got == want or got.startswith(want + "."))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=".migration/profile.yaml")
    a = ap.parse_args(argv)
    profile = yaml.safe_load(pathlib.Path(a.profile).read_text(encoding="utf-8")) or {}
    problems, ok = [], []
    for runtime, want in declared(profile):
        got = actual(runtime)
        if matches(want, got):
            ok.append(f"{runtime} {got}")
        else:
            problems.append(f"runtime {runtime}: profile declares {want}, found {got or 'none on PATH'}")
    for p in problems:
        print(p, file=sys.stderr)
    print(f"runtimes {'OK' if not problems else 'MISMATCH'}: " + (", ".join(ok) or "none declared"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
