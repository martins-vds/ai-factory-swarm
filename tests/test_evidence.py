"""validate.py, ADR-0018: ledger evidence must exist, be committed and name a live symbol."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATE = ROOT / "tools/validate.py"
ENTRY = """id: demo.capability
kind: behavioral
title: Demo
source: {{location: src/Demo.java}}
boundary: demo
status: pending
verification: characterized
characterization_tier: B
evidence:
{items}
"""


class EvidenceTest(unittest.TestCase):
    def run_with(self, items, sample=False, source=False):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            (root / ".migration/ledger").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "tests/test_demo.py").write_text("def test_tracks():\n    assert True\n\n\nclass TestGroup:\n    pass\n")
            (root / "char").mkdir()
            (root / "char/DemoTest.java").write_text("class DemoTest {\n  @Test\n  void nextActivity() {}\n}\n")
            (root / ".migration/evidence/runs").mkdir(parents=True)
            (root / ".migration/evidence/runs/TC-01.md").write_text("# journal\n")
            if source:
                (root / ".source/src").mkdir(parents=True)
                (root / ".source/src/LegacyTest.java").write_text("void legacyCase() {}\n")
            (root / ".migration/ledger/demo.capability.yaml").write_text(
                ENTRY.format(items="\n".join(f'  - "{i}"' for i in items)))
            args = [sys.executable, str(VALIDATE), *(["--sample"] if sample else []), str(root / ".migration")]
            return subprocess.run(args, capture_output=True, text=True)

    def test_valid_forms_pass(self):
        r = self.run_with(["tests/test_demo.py::test_tracks[abc123]", "tests/test_demo.py::TestGroup",
                           "char/DemoTest.java::nextActivity", ".migration/evidence/runs/TC-01.md",
                           "legacy-test: .source/src/LegacyTest.java::legacyCase"], source=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_raw_logs_are_rejected(self):
        r = self.run_with([".migration/runs/TC-03/20261101T1-tests.log"])
        self.assertIn("raw log under .migration/runs/", r.stderr)

    def test_missing_file_and_stale_symbol(self):
        r = self.run_with(["tests/gone.py", "tests/test_demo.py::test_renamed"])
        self.assertIn("tests/gone.py does not exist", r.stderr)
        self.assertIn("no 'test_renamed' defined", r.stderr)

    def test_legacy_source_checked_only_when_present(self):
        item = "legacy-test: .source/src/LegacyTest.java::missingCase"
        self.assertEqual(self.run_with([item]).returncode, 0)
        self.assertIn("no 'missingCase' defined", self.run_with([item], source=True).stderr)

    def test_unknown_prefix(self):
        self.assertIn("unknown prefix 'manual:'", self.run_with(["manual: looked at it"]).stderr)

    def test_sample_mode_skips_file_checks(self):
        self.assertEqual(self.run_with(["tests/gone.py"], sample=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
