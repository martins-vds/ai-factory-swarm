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


class TierAttemptTest(unittest.TestCase):
    """ADR-0005 amendment: tier C only after the tier-B recipe was tried (SY-01B rated a source C from a failed
    `mvn package` alone, though its tested code compiles from source)."""
    def errs(self, **doc):
        out = []
        validate_mod.check_tier_attempt("r.yaml", {"role": "afs-bootstrapper", **doc}, out)
        return out

    def test_tier_c_without_an_attempt_is_rejected(self):
        self.assertTrue(self.errs(characterization_tier="C"))
        self.assertTrue(self.errs(characterization_tier="C", tier_b_attempt=None))
        self.assertTrue(self.errs(characterization_tier="C", tier_b_attempt="mvn package failed"))
        self.assertIn("tier-B recipe", self.errs(characterization_tier="C")[0])

    def test_tier_c_with_an_attempt_or_no_code_passes(self):
        self.assertEqual(self.errs(characterization_tier="C",
                                   tier_b_attempt="ran: javac -sourcepath src -implicit:class T.java -> 40 errors"), [])
        self.assertEqual(self.errs(characterization_tier="C", tier_b_attempt="no code: specs and CSV samples"), [])

    def test_other_tiers_and_roles_are_not_affected(self):
        self.assertEqual(self.errs(characterization_tier="A"), [])
        self.assertEqual(self.errs(characterization_tier="B"), [])
        out = []
        validate_mod.check_tier_attempt("r.yaml", {"role": "afs-verifier", "characterization_tier": "C"}, out)
        self.assertEqual(out, [])


class ShallowHistoryTest(unittest.TestCase):
    """A shallow clone can't prove a pre-rule return's exemption; the error must say so (pilot BK-04 restart)."""
    def test_detects_a_shallow_clone(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a, cwd: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                                 check=True, capture_output=True)
            src, dst = pathlib.Path(d) / "src", pathlib.Path(d) / "dst"
            src.mkdir()
            run("init", "-q", "-b", "main", cwd=src)
            for i in range(3):
                run("commit", "-q", "--allow-empty", "-m", f"c{i}", cwd=src)
            run("clone", "-q", "--depth", "1", src.as_uri(), str(dst), cwd=d)
            self.assertTrue(validate_mod.shallow_history(dst))
            self.assertFalse(validate_mod.shallow_history(src))


class ComponentReferenceTest(unittest.TestCase):
    """ADR-0018 amendment: a migrated ledger entry's target components name code that exists. Synthetic LL-02
    moved its use cases behind ports and left `src.loans.services.lend_loan` in the ledger; the circulation
    audit (LC-AUDIT) found it as `misplaced`, and nothing failed on the PR that caused it."""
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        files = {
            "src/loans/__init__.py": "",
            "src/loans/services.py": "class LoanApplication:\n    def lend(self):\n        pass\n\nVALUE = 1\n",
            "src/shop/views.py": "def create_dialog_views(x):\n    return x\n",
            "templates/tracking/result.html": "<p/>\n",
            "Makefile": "run:\n\tpython manage.py runserver\n",
        }
        for name, text in files.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text)

    def problems(self, *components, status="migrated"):
        errors = []
        validate_mod.check_components(self.root, "ledger/x.yaml",
                                      {"status": status, "target": {"components": list(components)}}, errors)
        return errors

    def test_existing_references_in_every_form_pass(self):
        self.assertEqual(self.problems(
            "src.loans.services.LoanApplication.lend", "loans.services.LoanApplication", "loans.services.VALUE",
            "loans", "templates.tracking.result", "templates/tracking/", "src/shop/views.py:create_dialog_views",
            "src/shop/views.py::create_dialog_views", "Makefile.run", "Leaflet 1.7.1 with OpenStreetMap tiles"), [])

    def test_a_function_moved_behind_a_port_is_stale(self):
        errors = self.problems("src.loans.services.lend_loan")
        self.assertEqual(len(errors), 1)
        self.assertIn("no 'lend_loan' in src/loans/services.py (stale reference)", errors[0])

    def test_a_missing_method_module_or_file_is_stale(self):
        errors = self.problems("src.loans.services.LoanApplication.return_loan", "src.loans.repository.Repo",
                               "templates/missing.html", "src/shop/views.py:gone", "Makefile.deploy")
        self.assertEqual(len(errors), 5, errors)

    def test_entries_not_yet_migrated_are_not_held_to_their_components(self):
        self.assertEqual(self.problems("src.loans.services.future_thing", status="in-progress"), [])
