"""tools/afs-dashboard: the operator dashboard's data."""
import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("afs_dashboard", str(ROOT / "tools/afs-dashboard"))
_spec = importlib.util.spec_from_loader("afs_dashboard", _loader)
dash = importlib.util.module_from_spec(_spec)
_loader.exec_module(dash)


class TrendTest(unittest.TestCase):
    def test_majority_per_case_and_kind_per_family(self):
        with tempfile.TemporaryDirectory() as d:
            for n, (v, m) in enumerate([(True, True), (True, False), (False, False)], 1):
                pathlib.Path(d, f"2026-11-17-v3x-r{n}.json").write_text(json.dumps({"cases": {
                    "a-verify": {"passed": v, "usage": {"minutes": 10.0 * n}},
                    "b": {"passed": m}}}))
            pathlib.Path(d, "2026-11-17-v3x-r1.state.json").write_text("{}")
            pathlib.Path(d, "2026-11-17-v3x-summary.md").write_text("x")
            fams, cases = dash.trend(d)
        self.assertEqual(len(fams), 1)
        f = fams[0]
        self.assertEqual((f["family"], f["runs"], f["verifier_passed"], f["verifier_cases"]), ("v3x", 3, 1, 1))
        self.assertEqual((f["migrator_passed"], f["migrator_cases"], f["median_minutes"]), (0, 1, 20.0))
        self.assertEqual({(c["case"], c["passes"], c["passed"]) for c in cases},
                         {("a-verify", 2, True), ("b", 1, False)})

    def test_write_carries_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d, "x.json")
            dash.write(out, [{"a": 1}], "input")
            doc = json.loads(out.read_text())
        self.assertEqual(doc["rows"], [{"a": 1}])
        self.assertEqual(doc["meta"][0]["type"], "code")
        self.assertIn("def needs(", doc["meta"][0]["value"])


if __name__ == "__main__":
    unittest.main()
