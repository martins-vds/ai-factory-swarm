# Exporting a snapshot

The snapshot format is fixed (see SKILL.md):
- `<TABLE>.csv` per table, UTF-8, RFC 4180, header row;
- NULL written as `\N`;
- plus `manifest.json` with each table's row count and sha256.

Engines differ in how their bulk export writes headers and NULLs. Whatever you use, **prove it on a
known row**: export a table that has a NULL and an empty string, then check that the CSV shows `\N` for
one and `""` for the other. Then run `data_reconcile.py snapshot <dir>`.

## PostgreSQL
```sql
\copy (SELECT * FROM cargo ORDER BY id) TO 'CARGO.csv' WITH (FORMAT csv, HEADER, NULL '\N', ENCODING 'UTF8')
```
The same form serves as a target's `profile.data.export` command for each mapped table.

## Engines whose bulk export can't write a header or a NULL marker
Some built-in exporters write no header row, or write NULL as an empty field. Check your engine's
documentation for its export procedure. If either is true, don't use it directly. Use the harness's
JDBC exporter, `data_snapshot.py export` (`java/JdbcSnapshot.java`), which does the following:

1. For each table: `SELECT * FROM <table> ORDER BY <primary key>`.
2. Write the header from the result set's column names.
3. Write each row with a CSV writer, mapping SQL NULL to `\N`.
4. Write timestamps in ISO 8601, with an offset when the column has one. A naive value is in the zone
   named by the mapping's `defaults.timestamp_tz`.

This works for any JDBC-reachable engine (Derby, Oracle, SQL Server, DB2, MySQL); give the driver as a
pinned Maven coordinate. For an embedded
database (e.g. embedded Derby inside an application server), stop the application first, or run the
exporter against a copy of the database files, so the snapshot is consistent.

## manifest.json
After the export, compute the counts and hashes. For example:
```bash
python3 - <<'PY'
import csv, hashlib, json, pathlib, sys
d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
tables = {}
for f in sorted(d.glob("*.csv")):
    rows = sum(1 for _ in csv.reader(f.open(newline="", encoding="utf-8"))) - 1
    tables[f.stem] = {"rows": rows, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
json.dump({"source": {"engine": "<engine>", "database": "<name>"}, "taken_at": "<UTC time>",
           "taken_by": "<snapshot owner>", "null": "\\N", "tables": tables},
          open(d / "manifest.json", "w"), indent=2)
PY
```
The snippet counts rows with a CSV reader, the same way `data_reconcile.py` does, so a value with an
embedded newline counts as one row.
