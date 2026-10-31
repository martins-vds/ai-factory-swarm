#!/usr/bin/env python3
"""Schema tests: the samples are valid, and every invalid fixture fails with its expected error."""
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATE = ROOT / "tools" / "validate.py"
INVALID = ROOT / "tests" / "fixtures" / "invalid"


def run(folder):
    return subprocess.run([sys.executable, str(VALIDATE), str(folder)], capture_output=True, text=True)


class ValidateTest(unittest.TestCase):
    def test_samples_are_valid(self):
        r = run(ROOT / "templates" / "migration")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_invalid_fixtures_fail_for_the_right_reason(self):
        cases = [line.split("\t", 1) for line in (INVALID / "expected.tsv").read_text().splitlines() if line]
        self.assertTrue(cases)
        listed = {name for name, _ in cases}
        on_disk = {p.name for p in INVALID.iterdir() if p.is_dir()}
        self.assertEqual(listed, on_disk, "every fixture folder needs an expected.tsv row")
        for name, expected in cases:
            with self.subTest(fixture=name):
                r = run(INVALID / name)
                self.assertEqual(r.returncode, 1, f"{name} should be invalid")
                self.assertIn(expected, r.stderr)


if __name__ == "__main__":
    unittest.main()
