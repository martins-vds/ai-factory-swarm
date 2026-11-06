#!/usr/bin/env python3
"""Schema tests: the samples are valid, and every invalid fixture fails with its expected error."""
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATE = ROOT / "tools" / "validate.py"
INVALID = ROOT / "tests" / "fixtures" / "invalid"


def run(folder, *extra):
    return subprocess.run([sys.executable, str(VALIDATE), *extra, str(folder)], capture_output=True, text=True)


class ValidateTest(unittest.TestCase):
    def test_samples_are_valid(self):
        r = run(ROOT / "templates" / "migration", "--sample")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_invalid_fixtures_fail_for_the_right_reason(self):
        cases = [line.split("\t", 1) for line in (INVALID / "expected.tsv").read_text().splitlines() if line]
        self.assertTrue(cases)
        listed = {name for name, _ in cases}
        on_disk = {p.name for p in INVALID.iterdir() if p.is_dir()}
        self.assertEqual(listed, on_disk, "every fixture folder needs an expected.tsv row")
        for name, expected in cases:
            with self.subTest(fixture=name):
                r = run(INVALID / name, "--sample")
                self.assertEqual(r.returncode, 1, f"{name} should be invalid")
                self.assertIn(expected, r.stderr)


if __name__ == "__main__":
    unittest.main()


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import validate as validate_mod  # noqa: E402


class ThresholdTest(unittest.TestCase):
    """A gate command's own limit must equal the profile threshold (pilot drill: --max 30 hid a threshold of 0)."""
    CMD = "python .migration/harness/tools/crap.py runs/lizard.csv --lcov runs/crap.lcov --max {}"

    def errors(self, limit, cmd_max):
        errs = []
        validate_mod.check_thresholds("profile.yaml", {"thresholds": {"crap_max_per_method": limit},
                                                       "gates": {"crap": ["lizard --csv src", self.CMD.format(cmd_max)]}}, errs)
        return errs

    def test_equal_limits_pass(self):
        self.assertEqual(self.errors(30, 30), [])

    def test_different_limits_fail(self):
        self.assertEqual(len(self.errors(0, 30)), 1)

    def test_a_gate_without_its_own_limit_passes(self):
        errs = []
        validate_mod.check_thresholds("p", {"thresholds": {"crap_max_per_method": 30}, "gates": {"crap": ["crap.py x"]}}, errs)
        self.assertEqual(errs, [])
