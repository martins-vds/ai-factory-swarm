#!/usr/bin/env python3
"""Check a data snapshot, and reconcile it with the target's loaded data (ADR-0010, ADR-0032).

The data-migration pipeline moves a **snapshot** of the legacy database into the target schema. This
tool proves the move, from files, without trusting the agent that wrote the loader:

  data_reconcile.py snapshot <snapshot dir>
      The snapshot is intact: every table in manifest.json has its CSV, with the stated row count and
      sha256. Run it before loading; a truncated or edited export fails here, not in reconciliation.

  data_reconcile.py reconcile --snapshot <dir> --target <dir> --mapping <mapping.yaml> [--report out.md]
      The target holds exactly the snapshot's data, mapped. `--target` is the target's own export of
      its tables, in the same CSV conventions (the profile's `data.export` command writes it). For each
      mapped table:
        * rows: the same count on both sides;
        * content: the same multiset of rows, compared on the mapped columns after each column's
          transform (a checksum per side, and the first differing keys when they disagree);
        * references: every `refs` value in the target points at an existing row (referential
          integrity, checked on the target side).
      Exit 1 on any mismatch. Prints `AFS-RESULT gate=data-reconcile …`.

Snapshot format: `<table>.csv` per table, UTF-8, RFC 4180, with a header row; NULL is the manifest's
`null` marker (default `\\N`), so NULL and the empty string stay different. manifest.json:
  {"source": {"engine": "derby", "database": "…"}, "taken_at": "…", "taken_by": "…", "null": "\\\\N",
   "tables": {"CARGO": {"rows": 12, "sha256": "…"}, …}}

Mapping (`.migration/data/mapping.yaml`; tables in load order, parents first):
  tables:
    - target: cargo
      source: CARGO
      key: [tracking_id]
      columns:                       # target column: source column, or {from: col, as: transform}
        id: ID
        tracking_id: TRACKING_ID
        origin_id: ORIGIN_ID
        last_event_time: {from: LAST_EVENT_TIME, as: timestamp}
      refs: {origin_id: location.id}
Transforms: identity (default), trim, int, decimal, bool, timestamp, date, null_if_empty, and
{map: {source value: target value}}. Timestamps compare as UTC to the second (`timestamp_tz` in the
mapping's `defaults` names the zone of naive source values; default UTC). Standard library + PyYAML.
"""
import argparse
import collections
import csv
import datetime
import decimal
import hashlib
import json
import pathlib
import sys

import yaml

csv.field_size_limit(sys.maxsize)
NULL = None


class DataError(Exception):
    pass


# ------------------------------------------------------------------------------------------ snapshot

def manifest(snapshot):
    path = pathlib.Path(snapshot) / "manifest.json"
    if not path.exists():
        raise DataError(f"{snapshot}: no manifest.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc.get("tables"), dict) or not doc["tables"]:
        raise DataError(f"{path}: `tables` lists no tables")
    return doc


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_table(folder, table, null_marker):
    """(header, rows) with NULLs as None."""
    path = pathlib.Path(folder) / f"{table}.csv"
    if not path.exists():
        raise DataError(f"{path}: missing")
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise DataError(f"{path}: empty file (a header row is required)")
        rows = []
        for n, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise DataError(f"{path}:{n}: {len(row)} fields, header has {len(header)}")
            rows.append([NULL if v == null_marker else v for v in row])
    return header, rows


def check_snapshot(snapshot):
    doc = manifest(snapshot)
    problems = []
    for table, meta in sorted(doc["tables"].items()):
        path = pathlib.Path(snapshot) / f"{table}.csv"
        if not path.exists():
            problems.append(f"{table}: {path.name} missing")
            continue
        if meta.get("sha256") and sha256(path) != meta["sha256"]:
            problems.append(f"{table}: sha256 differs from the manifest (the file changed after export)")
        try:
            _, rows = read_table(snapshot, table, doc.get("null", "\\N"))
        except DataError as e:
            problems.append(str(e))
            continue
        if "rows" in meta and len(rows) != meta["rows"]:
            problems.append(f"{table}: {len(rows)} rows, manifest says {meta['rows']}")
    return doc, problems


# ------------------------------------------------------------------------------------------ transforms

def _ts(value, tz):
    """ISO forms with or without an offset ('Z', '+02:00', '-0500'); naive values are in `tz`."""
    v = value.strip()
    try:
        t = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M"):
            try:
                t = datetime.datetime.strptime(v, fmt)
                break
            except ValueError:
                continue
        else:
            raise DataError(f"not a timestamp: {value!r}")
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz)
    return t.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


TRUE, FALSE = {"1", "true", "t", "yes", "y"}, {"0", "false", "f", "no", "n"}


def normalize(value, kind, tz=datetime.timezone.utc):
    """The comparable form of one value, the same on both sides."""
    if value is NULL:
        return NULL
    if isinstance(kind, dict):                      # {map: {...}} applies to the source side only
        return value
    if kind in ("identity", "null_if_empty"):
        return value
    if kind == "trim":
        return value.strip()
    if kind == "int":
        return str(int(decimal.Decimal(value.strip())))
    if kind == "decimal":
        return format(decimal.Decimal(value.strip()).normalize(), "f")
    if kind == "bool":
        v = value.strip().lower()
        if v in TRUE:
            return "true"
        if v in FALSE:
            return "false"
        raise DataError(f"not a boolean: {value!r}")
    if kind == "timestamp":
        return _ts(value, tz)
    if kind == "date":
        return _ts(value, tz)[:10] if len(value.strip()) > 10 else value.strip()
    raise DataError(f"unknown transform {kind!r}")


def source_value(value, kind, tz):
    if isinstance(kind, dict) and "map" in kind:
        if value is NULL:
            return NULL
        mapped = kind["map"].get(value, kind["map"].get(str(value)))
        if mapped is None and value not in kind["map"]:
            raise DataError(f"no mapping for value {value!r}")
        return NULL if mapped is None else str(mapped)
    if kind == "null_if_empty" and value is not NULL and value.strip() == "":
        return NULL
    return normalize(value, kind, tz)


def columns_of(spec):
    """[(target column, source column, transform)] in mapping order."""
    out = []
    for tcol, how in (spec.get("columns") or {}).items():
        if isinstance(how, dict):
            out.append((tcol, how.get("from"), how.get("as", "identity")))
        else:
            out.append((tcol, how, "identity"))
    return out


# ------------------------------------------------------------------------------------------ reconcile

def project(header, rows, cols, side, tz, where):
    idx = {c: i for i, c in enumerate(header)}
    missing = [c for c in cols if c[1 if side == "source" else 0] not in idx]
    if missing:
        names = [c[1 if side == "source" else 0] for c in missing]
        raise DataError(f"{where}: no column(s) {', '.join(names)} in its CSV header")
    out = []
    for r in rows:
        if side == "source":
            out.append(tuple(source_value(r[idx[s]], kind, tz) for _, s, kind in cols))
        else:
            out.append(tuple(normalize(r[idx[t]], "identity" if isinstance(kind, dict) else
                                       ("identity" if kind == "null_if_empty" else kind), tz)
                             for t, _, kind in cols))
    return out


def digest(rows):
    h = hashlib.sha256()
    for r in sorted(json.dumps(r) for r in rows):
        h.update(r.encode())
        h.update(b"\n")
    return h.hexdigest()


def reconcile(snapshot, target, mapping):
    snap = manifest(snapshot)
    snap_null = snap.get("null", "\\N")
    tgt_null = "\\N"
    tgt_manifest = pathlib.Path(target) / "manifest.json"
    if tgt_manifest.exists():
        tgt_null = json.loads(tgt_manifest.read_text(encoding="utf-8")).get("null", "\\N")
    defaults = mapping.get("defaults") or {}
    tz = datetime.timezone.utc
    if defaults.get("timestamp_tz"):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(defaults["timestamp_tz"])
    results, target_rows = [], {}
    for spec in mapping.get("tables") or []:
        t, s = spec["target"], spec["source"]
        cols = columns_of(spec)
        key = [c for c in spec.get("key") or []]
        res = {"table": t, "source": s, "problems": []}
        try:
            sh, srows = read_table(snapshot, s, snap_null)
            th, trows = read_table(target, t, tgt_null)
            target_rows[t] = (th, trows)
            src = project(sh, srows, cols, "source", tz, f"snapshot {s}")
            tgt = project(th, trows, cols, "target", tz, f"target {t}")
        except DataError as e:
            res["problems"].append(str(e))
            results.append(res)
            continue
        res["rows"] = (len(src), len(tgt))
        if len(src) != len(tgt):
            res["problems"].append(f"rows: snapshot {len(src)}, target {len(tgt)}")
        res["checksum"] = (digest(src), digest(tgt))
        if res["checksum"][0] != res["checksum"][1]:
            a, b = collections.Counter(src), collections.Counter(tgt)
            names = [c[0] for c in cols]
            kidx = [names.index(k) for k in key if k in names]
            label = (lambda r: ", ".join(f"{names[i]}={r[i]}" for i in kidx)) if kidx else (lambda r: str(r))
            only_src = list((a - b).elements())[:3]
            only_tgt = list((b - a).elements())[:3]
            res["problems"].append("content differs: " + "; ".join(
                [f"only in snapshot: {label(r)}" for r in only_src] + [f"only in target: {label(r)}" for r in only_tgt]))
        results.append(res)
    for spec in mapping.get("tables") or []:              # referential integrity on the target side
        t = spec["target"]
        if t not in target_rows:
            continue
        th, trows = target_rows[t]
        res = next(r for r in results if r["table"] == t)
        for col, ref in (spec.get("refs") or {}).items():
            rt, rc = ref.split(".", 1)
            if rt not in target_rows:
                try:
                    target_rows[rt] = read_table(target, rt, tgt_null)
                except DataError as e:
                    res["problems"].append(f"refs {col} → {ref}: {e}")
                    continue
            rh, rrows = target_rows[rt]
            if col not in th or rc not in rh:
                res["problems"].append(f"refs {col} → {ref}: column missing")
                continue
            known = {r[rh.index(rc)] for r in rrows}
            dangling = [r[th.index(col)] for r in trows if r[th.index(col)] is not NULL and r[th.index(col)] not in known]
            if dangling:
                res["problems"].append(f"refs {col} → {ref}: {len(dangling)} dangling, e.g. {dangling[0]}")
    return results


def render(results, snapshot_doc):
    lines = ["# Data reconciliation", "",
             f"- Snapshot: {snapshot_doc.get('source', {}).get('engine', '?')} · taken {snapshot_doc.get('taken_at', '?')}"
             f" by {snapshot_doc.get('taken_by', '?')}", "",
             "| Target table | Source | Rows (snapshot / target) | Checksums match | Problems |", "|---|---|---|---|---|"]
    for r in results:
        rows = "{} / {}".format(*r["rows"]) if "rows" in r else "—"
        same = "—" if "checksum" not in r else ("yes" if r["checksum"][0] == r["checksum"][1] else "**no**")
        probs = "; ".join(r["problems"]).replace("|", "/") or "none"
        lines.append(f"| `{r['table']}` | `{r['source']}` | {rows} | {same} | {probs} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("dir")
    r = sub.add_parser("reconcile")
    r.add_argument("--snapshot", required=True)
    r.add_argument("--target", required=True)
    r.add_argument("--mapping", required=True)
    r.add_argument("--report")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "snapshot":
            doc, problems = check_snapshot(a.dir)
            for p in problems:
                print(f"::error::snapshot {p}")
            print(f"AFS-RESULT gate=data-snapshot tables={len(doc['tables'])} problems={len(problems)}")
            return 1 if problems else 0
        mapping = yaml.safe_load(pathlib.Path(a.mapping).read_text(encoding="utf-8")) or {}
        doc, problems = check_snapshot(a.snapshot)
        if problems:
            for p in problems:
                print(f"::error::snapshot {p}")
            return 1
        results = reconcile(a.snapshot, a.target, mapping)
    except DataError as e:
        print(f"::error::{e}")
        return 1
    text = render(results, doc)
    if a.report:
        pathlib.Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.report).write_text(text, encoding="utf-8")
    print(text)
    bad = [x for x in results if x["problems"]]
    for x in bad:
        print(f"::error::{x['table']}: {'; '.join(x['problems'])}")
    rows = sum(x.get("rows", (0, 0))[0] for x in results)
    print(f"AFS-RESULT gate=data-reconcile tables={len(results)} rows={rows} mismatched_tables={len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
