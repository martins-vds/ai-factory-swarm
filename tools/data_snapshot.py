#!/usr/bin/env python3
"""Make, describe and fetch data snapshots in the afs-data-pipeline format (ADR-0032).

  data_snapshot.py export --jdbc-url URL (--driver group:artifact:version[@sha256] | --driver-jar PATH)
                          --out DIR [--schema S] [--engine NAME] [--taken-by WHO]
      Export every table of a JDBC database with the harness's JdbcSnapshot (java/JdbcSnapshot.java),
      write manifest.json, then check the snapshot (`data_reconcile.py snapshot`). Needs a JDK (javac)
      on PATH or in JAVA_HOME; the driver comes from Maven Central unless given as a jar. Pin it with
      `@<sha256>`; an unpinned driver prints its hash so it can be pinned.

  data_snapshot.py manifest DIR [--engine NAME] [--taken-by WHO]
      Write manifest.json for CSVs some other exporter wrote.

  data_snapshot.py fetch --repo OWNER/REPO [--dir DIR]
      Download the newest successful `afs-snapshot` artifact (from the AFS data snapshot workflow) into
      DIR (default: the profile's data.snapshot_dir). Copilot setup steps run this so data tickets
      start with the snapshot; agents never make one.

Production data stays out of git: DIR is gitignored by bootstrap. Standard library + PyYAML; `fetch`
uses `gh`.
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import yaml

HERE = pathlib.Path(__file__).resolve().parent
MAVEN = os.environ.get("AFS_MAVEN_REPO", "https://repo1.maven.org/maven2")
PROFILE = pathlib.Path(".migration/profile.yaml")
WORKFLOW = "afs-snapshot.yml"
ARTIFACT = "afs-snapshot"


class SnapshotError(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def write_manifest(folder, engine, taken_by, database=None):
    folder = pathlib.Path(folder)
    tables = {}
    for f in sorted(folder.glob("*.csv")):
        with open(f, newline="", encoding="utf-8") as fh:
            rows = sum(1 for _ in csv.reader(fh)) - 1
        tables[f.stem] = {"rows": max(rows, 0), "sha256": sha256(f)}
    if not tables:
        raise SnapshotError(f"{folder}: no CSV files to describe")
    doc = {"source": {"engine": engine, **({"database": database} if database else {})}, "taken_at": now(),
           "taken_by": taken_by, "null": "\\N", "tables": tables}
    (folder / "manifest.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def driver_jar(spec, cache):
    """A Maven coordinate `group:artifact:version[@sha256]` → a local jar, checked against the pin."""
    coord, _, pin = spec.partition("@")
    parts = coord.split(":")
    if len(parts) != 3:
        raise SnapshotError(f"--driver {spec!r}: expected group:artifact:version[@sha256]")
    group, artifact, version = parts
    jar = pathlib.Path(cache) / f"{artifact}-{version}.jar"
    if not jar.exists():
        url = f"{MAVEN}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar"
        with urllib.request.urlopen(url, timeout=120) as r, open(jar, "wb") as out:
            shutil.copyfileobj(r, out)
    got = sha256(jar)
    if pin and got != pin:
        raise SnapshotError(f"driver {coord}: sha256 {got} differs from the pin {pin}")
    if not pin:
        print(f"warning: driver {coord} is not pinned; pin it as {coord}@{got}", file=sys.stderr)
    return jar


def jdk_tool(name):
    home = os.environ.get("JAVA_HOME")
    if home and (pathlib.Path(home) / "bin" / name).exists():
        return str(pathlib.Path(home) / "bin" / name)
    found = shutil.which(name)
    if not found:
        raise SnapshotError(f"{name} not found: put a JDK on PATH or set JAVA_HOME")
    return found


def export(a):
    out = pathlib.Path(a.out)
    if out.exists() and any(out.iterdir()):
        raise SnapshotError(f"{out} is not empty; a snapshot is written into a fresh folder")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="afs-snapshot-") as tmp:
        jar = pathlib.Path(a.driver_jar) if a.driver_jar else driver_jar(a.driver, tmp)
        classes = pathlib.Path(tmp) / "classes"
        classes.mkdir()
        subprocess.run([jdk_tool("javac"), "-d", str(classes), str(HERE / "java" / "JdbcSnapshot.java")], check=True)
        cp = os.pathsep.join([str(classes), str(jar)])
        cmd = [jdk_tool("java"), "-cp", cp, "JdbcSnapshot", a.jdbc_url, str(out)] + ([a.schema] if a.schema else [])
        r = subprocess.run(cmd)
        if r.returncode:
            raise SnapshotError(f"JdbcSnapshot exited {r.returncode}")
    doc = write_manifest(out, a.engine, a.taken_by, a.database)
    sys.path.insert(0, str(HERE))
    import data_reconcile
    _, problems = data_reconcile.check_snapshot(out)
    for p in problems:
        print(f"::error::snapshot {p}")
    rows = sum(t["rows"] for t in doc["tables"].values())
    print(f"AFS-RESULT gate=data-snapshot tables={len(doc['tables'])} rows={rows} problems={len(problems)}")
    return 1 if problems else 0


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode:
        raise SnapshotError(f"gh {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def fetch(a):
    folder = a.dir
    if not folder:
        prof = yaml.safe_load(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}
        folder = ((prof or {}).get("data") or {}).get("snapshot_dir") or ".migration/data/snapshot"
    run = gh("run", "list", "--repo", a.repo, "--workflow", WORKFLOW, "--status", "success", "--limit", "1",
             "--json", "databaseId", "--jq", ".[0].databaseId // empty")
    if not run:
        raise SnapshotError(f"no successful {WORKFLOW} run yet: the snapshot owner dispatches it")
    dest = pathlib.Path(folder)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    gh("run", "download", run, "--repo", a.repo, "--name", ARTIFACT, "--dir", str(dest))
    doc = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    print(f"snapshot from run {run}: {len(doc['tables'])} tables, taken {doc.get('taken_at')} by {doc.get('taken_by')}"
          f" → {dest}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--jdbc-url", required=True)
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--driver", help="Maven coordinate group:artifact:version[@sha256]")
    g.add_argument("--driver-jar")
    e.add_argument("--out", required=True)
    e.add_argument("--schema")
    e.add_argument("--engine", default="jdbc")
    e.add_argument("--database")
    e.add_argument("--taken-by", default=os.environ.get("GITHUB_ACTOR", "unknown"))
    m = sub.add_parser("manifest")
    m.add_argument("dir")
    m.add_argument("--engine", default="unknown")
    m.add_argument("--database")
    m.add_argument("--taken-by", default=os.environ.get("GITHUB_ACTOR", "unknown"))
    f = sub.add_parser("fetch")
    f.add_argument("--repo", required=True)
    f.add_argument("--dir")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            return export(a)
        if a.cmd == "manifest":
            doc = write_manifest(a.dir, a.engine, a.taken_by, a.database)
            print(f"manifest: {len(doc['tables'])} tables")
            return 0
        return fetch(a)
    except SnapshotError as e:
        print(f"::error::{e}")
        return 1


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
