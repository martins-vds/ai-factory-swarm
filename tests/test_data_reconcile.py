"""tools/data_reconcile.py (ADR-0032): snapshot integrity and snapshot ↔ target reconciliation."""
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import data_reconcile as dr  # noqa: E402

MAPPING = {
    "defaults": {"timestamp_tz": "UTC"},
    "tables": [
        {"target": "location", "source": "LOCATION", "key": ["unlocode"],
         "columns": {"id": "ID", "unlocode": {"from": "UNLOCODE", "as": "trim"}, "name": "NAME"}},
        {"target": "cargo", "source": "CARGO", "key": ["tracking_id"],
         "columns": {"id": "ID", "tracking_id": "TRACKING_ID", "origin_id": "ORIGIN_ID",
                     "misdirected": {"from": "MISDIRECTED", "as": "bool"},
                     "routing_status": {"from": "ROUTING_STATUS", "as": {"map": {"0": "NOT_ROUTED", "1": "ROUTED"}}},
                     "last_event": {"from": "LAST_EVENT", "as": "timestamp"},
                     "note": {"from": "NOTE", "as": "null_if_empty"}},
         "refs": {"origin_id": "location.id"}},
    ],
}


def write_csv(folder, name, header, rows, null="\\N"):
    lines = [",".join(header)] + [",".join(null if v is None else v for v in r) for r in rows]
    path = pathlib.Path(folder) / f"{name}.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.snap = pathlib.Path(self.tmp.name) / "snapshot"
        self.tgt = pathlib.Path(self.tmp.name) / "target"
        self.snap.mkdir()
        self.tgt.mkdir()
        self.src_tables = {
            "LOCATION": (["ID", "UNLOCODE", "NAME"], [["1", "SESTO ", "Stockholm"], ["2", "CNHKG", "Hong Kong"]]),
            "CARGO": (["ID", "TRACKING_ID", "ORIGIN_ID", "MISDIRECTED", "ROUTING_STATUS", "LAST_EVENT", "NOTE"],
                      [["10", "ABC123", "1", "0", "1", "2026-03-01 10:15:00.000", ""],
                       ["11", "XYZ789", "2", "1", "0", None, "late"]]),
        }
        self.tgt_tables = {
            "location": (["id", "unlocode", "name"], [["1", "SESTO", "Stockholm"], ["2", "CNHKG", "Hong Kong"]]),
            "cargo": (["id", "tracking_id", "origin_id", "misdirected", "routing_status", "last_event", "note"],
                      [["10", "ABC123", "1", "false", "ROUTED", "2026-03-01T10:15:00+00:00", None],
                       ["11", "XYZ789", "2", "true", "NOT_ROUTED", None, "late"]]),
        }
        self.write_all()

    def tearDown(self):
        self.tmp.cleanup()

    def write_all(self):
        tables = {}
        for name, (h, rows) in self.src_tables.items():
            p = write_csv(self.snap, name, h, rows)
            tables[name] = {"rows": len(rows), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        (self.snap / "manifest.json").write_text(json.dumps(
            {"source": {"engine": "derby"}, "taken_at": "2026-11-06T00:00:00Z", "taken_by": "ops", "null": "\\N",
             "tables": tables}))
        for name, (h, rows) in self.tgt_tables.items():
            write_csv(self.tgt, name, h, rows)

    def problems(self):
        return {r["table"]: r["problems"] for r in dr.reconcile(self.snap, self.tgt, MAPPING)}

    def test_a_faithful_load_reconciles(self):
        self.assertEqual(self.problems(), {"location": [], "cargo": []})
        self.assertEqual(dr.main(["reconcile", "--snapshot", str(self.snap), "--target", str(self.tgt),
                                  "--mapping", self.mapping_file()]), 0)

    def mapping_file(self):
        import yaml
        p = pathlib.Path(self.tmp.name) / "mapping.yaml"
        p.write_text(yaml.safe_dump(MAPPING))
        return str(p)

    def test_a_missing_row_is_a_count_and_content_mismatch(self):
        self.tgt_tables["cargo"][1].pop()
        self.write_all()
        probs = self.problems()["cargo"]
        self.assertIn("rows: snapshot 2, target 1", probs)
        self.assertTrue(any("only in snapshot: tracking_id=XYZ789" in p for p in probs))

    def test_a_changed_value_names_the_key(self):
        self.tgt_tables["cargo"][1][0][3] = "true"          # misdirected flipped on ABC123
        self.write_all()
        probs = self.problems()["cargo"]
        self.assertTrue(any("tracking_id=ABC123" in p for p in probs), probs)

    def test_null_and_empty_string_stay_different(self):
        self.src_tables["LOCATION"][1][1][2] = ""           # empty name in the source …
        self.tgt_tables["location"][1][1][2] = None         # … loaded as NULL: a real difference
        self.write_all()
        self.assertTrue(self.problems()["location"])

    def test_a_dangling_reference_fails(self):
        self.tgt_tables["cargo"][1][1][2] = "99"
        self.src_tables["CARGO"][1][1][2] = "99"            # same on both sides; still dangling in the target
        self.write_all()
        self.assertTrue(any("dangling" in p for p in self.problems()["cargo"]))

    def test_snapshot_integrity(self):
        doc, probs = dr.check_snapshot(self.snap)
        self.assertEqual(probs, [])
        with open(self.snap / "CARGO.csv", "a") as fh:
            fh.write("12,LATE1,1,0,0,\\N,\\N\n")             # edited after export
        _, probs = dr.check_snapshot(self.snap)
        self.assertTrue(any("sha256" in p for p in probs) and any("3 rows, manifest says 2" in p for p in probs))
        self.assertEqual(dr.main(["snapshot", str(self.snap)]), 1)

    def test_an_unmapped_value_is_an_error_not_a_guess(self):
        self.src_tables["CARGO"][1][0][4] = "7"
        self.write_all()
        self.assertTrue(any("no mapping for value" in p for p in self.problems()["cargo"]))

    def test_timestamps_compare_in_utc_across_zones(self):
        self.assertEqual(dr.normalize("2026-03-01 10:15:00", "timestamp"), "2026-03-01T10:15:00+00:00")
        self.assertEqual(dr.normalize("2026-03-01T12:15:00+02:00", "timestamp"), "2026-03-01T10:15:00+00:00")
        self.assertEqual(dr.normalize("2026-03-01 05:15:00.250-05:00", "timestamp"), "2026-03-01T10:15:00+00:00")
        self.assertEqual(dr.normalize("2026-03-01T10:15:00Z", "timestamp"), "2026-03-01T10:15:00+00:00")
        with self.assertRaises(dr.DataError):
            dr.normalize("yesterday", "timestamp")


if __name__ == "__main__":
    unittest.main()
