"""tools/afs-mutation: parsing, path filtering, and (when mutmut 2.x is installed) a real run."""
import importlib.machinery
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("afs_mutation", str(ROOT / "tools/afs-mutation"))
spec = importlib.util.spec_from_loader("afs_mutation", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

JUNIT = """<?xml version="1.0" ?><testsuites><testsuite name="mutmut" tests="4" failures="1" errors="0" skipped="1">
<testcase name="Mutant #1" file="src/a.py" line="3"/>
<testcase name="Mutant #2" file="src/a.py" line="4"/>
<testcase name="Mutant #3" file="src/a.py" line="5"><failure message="bad survived"/></testcase>
<testcase name="Mutant #4" file="src/a.py" line="6"><skipped/></testcase>
</testsuite></testsuites>"""


class AfsMutationTest(unittest.TestCase):
    def test_score_counts_failures_as_survivors_and_ignores_skipped(self):
        killed, survived, skipped, locs = m.score_from_junit(JUNIT)
        self.assertEqual((killed, survived, skipped), (2, 1, 1))
        self.assertEqual(locs, ["src/a.py:5 Mutant #3"])

    def test_default_excludes(self):
        ex = m.DEFAULT_EXCLUDE
        self.assertFalse(m.keep("src/app/migrations/0001_initial.py", ex))
        self.assertFalse(m.keep("src/cargotracker/settings.py", ex))
        self.assertFalse(m.keep("tests/test_x.py", ex))
        self.assertTrue(m.keep("src/cargotracker/voyage/domain/voyage.py", ex))

    @unittest.skipUnless(shutil.which("mutmut"), "mutmut not installed")
    def test_real_run_enforces_the_threshold(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / "src").mkdir()
            (t / "src/calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef neg(a):\n    return -a\n")
            (t / "tests").mkdir()
            (t / "tests/test_calc.py").write_text(
                "import sys\nsys.path.insert(0, 'src')\nfrom calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
            (t / "setup.cfg").write_text("[mutmut]\ntests_dir=tests/\nrunner=python -m pytest -q -x\n")
            run = lambda thr: subprocess.run([sys.executable, str(ROOT / "tools/afs-mutation"), "--paths",
                                              "src/calc.py", "--threshold", thr], cwd=t, capture_output=True, text=True)
            low = run("0.4")   # add() is tested, neg() is not: roughly half the mutants survive
            self.assertEqual(low.returncode, 0, low.stdout + low.stderr)
            self.assertIn("score=", low.stdout)
            high = run("0.99")
            self.assertEqual(high.returncode, 1, high.stdout + high.stderr)
            self.assertIn("survived: ", high.stdout)


if __name__ == "__main__":
    unittest.main()
