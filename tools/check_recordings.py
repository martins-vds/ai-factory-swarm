#!/usr/bin/env python3
"""Recorded legacy exchanges are append-only (ADR-0077).

  check_recordings.py --base <ref>

A recording is a `.json` file under `.migration/characterization/` whose entries (top level, or one level down)
are exchanges: objects with a `request` and a `response`. Against the base ref, a change may add recordings and
exchanges, but it may not change, delete or rename an existing exchange, or delete a recording.

The recorded exchanges are the evidence behind every characterized capability and the oracle that specs replay.
Re-recording a whole file on a later day silently rewrites that evidence (dates, day counts, fees), even for
capabilities the change never touched. Changed legacy behaviour is recorded under a new key.

The one exception is a change that itself moves the source pin (the profile's `source.sha`, ADR-0076): the
legacy app changed, so its recordings may change with it.
"""
import argparse
import json
import subprocess
import sys

import yaml

ROOT = ".migration/characterization/"


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.returncode, r.stdout


def exchanges(doc):
    """{key path: exchange} for the exchanges in a recording, top level or one level down."""
    out = {}
    if not isinstance(doc, dict):
        return out
    for key, value in doc.items():
        if isinstance(value, dict) and "request" in value and "response" in value:
            out[(key,)] = value
        elif isinstance(value, dict):
            for sub, ex in value.items():
                if isinstance(ex, dict) and "request" in ex and "response" in ex:
                    out[(key, sub)] = ex
    return out


def read_at(ref, path):
    code, out = git("show", f"{ref}:{path}")
    if code:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def read_now(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def source_sha(text):
    try:
        return ((yaml.safe_load(text) or {}).get("source") or {}).get("sha")
    except yaml.YAMLError:
        return None


def pin_moved(base):
    code, old = git("show", f"{base}:.migration/profile.yaml")
    try:
        with open(".migration/profile.yaml", encoding="utf-8") as f:
            new = f.read()
    except OSError:
        return False
    return code == 0 and source_sha(old) != source_sha(new)


def problems(base):
    code, listing = git("ls-tree", "-r", "--name-only", base, "--", ROOT)
    if code:
        return [f"can't list {ROOT} at {base}"]
    out = []
    for path in sorted(p for p in listing.splitlines() if p.endswith(".json")):
        old = exchanges(read_at(base, path))
        if not old:
            continue                                   # not a recording
        now_doc = read_now(path)
        if now_doc is None:
            out.append(f"{path}: a recording was deleted or no longer parses; recordings are append-only")
            continue
        now = exchanges(now_doc)
        for key, ex in sorted(old.items()):
            name = " / ".join(key)
            if key not in now:
                out.append(f"{path}: exchange {name!r} was removed; recorded exchanges are append-only")
            elif now[key] != ex:
                out.append(f"{path}: exchange {name!r} changed; recorded exchanges are append-only. Keep it "
                           "byte-for-byte and record new behaviour under a new key (re-recording a whole file "
                           "rewrites every date-dependent answer)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the PR's base ref, e.g. origin/main")
    a = ap.parse_args(argv)
    if pin_moved(a.base):
        print("AFS-RESULT gate=recordings skipped=source-pin-moved")
        return 0
    found = problems(a.base)
    for p in found:
        print(f"::error::{p}")
    print(f"AFS-RESULT gate=recordings problems={len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
