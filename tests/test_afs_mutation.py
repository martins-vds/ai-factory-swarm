"""tools/afs-mutation: parsing, path filtering, and (when mutmut 2.x is installed) a real run."""
import importlib.machinery
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

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
    def test_fatal_mutmut_run_is_reported_not_dropped(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw.get("env", {}).get("POSTGRES_DB")))
            if cmd[:2] == ["mutmut", "run"]:
                # src/a.py: mutants survived (bit 2) — fine; src/b.py: fatal (bit 1), e.g. tests fail unmutated
                rc = 2 if cmd[3] == "src/a.py" else 1
                return subprocess.CompletedProcess(cmd, rc, stdout="baseline tests failed\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="<testsuite/>", stderr="")

        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(m.subprocess, "run", fake_run):
            xml, _, failed, _ = m.run_shard(1, d, ["src/a.py", "src/b.py"], {"src/a.py": "x", "src/b.py": "y"},
                                         {"POSTGRES_DB": "cargotracker"})
        self.assertEqual([f for f, _ in failed], ["src/b.py"])
        self.assertIn("baseline tests failed", failed[0][1])
        self.assertTrue(all(db == "cargotracker_w1" for _, db in calls), calls)

    def test_profile_services_env_supplies_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "profile.yaml"
            p.write_text("services: {compose: compose.yaml, test: [db], env: {POSTGRES_DB: cargotracker}}\n")
            self.assertEqual(m.services_env(str(p)), ({"POSTGRES_DB": "cargotracker"}, True))
            p.write_text("services: {compose: compose.yaml, test: [db]}\n")
            self.assertEqual(m.services_env(str(p)), ({}, True))
            p.write_text("gates: {}\n")
            self.assertEqual(m.services_env(str(p)), ({}, False))

    def test_score_counts_failures_as_survivors_and_ignores_skipped(self):
        killed, survived, skipped, locs = m.score_from_junit(JUNIT)
        self.assertEqual((killed, survived, skipped), (2, 1, 1))
        self.assertEqual(locs, ["src/a.py:5 Mutant #3"])

    def test_survivors_are_written_for_the_ticket(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            try:
                os.chdir(d)
                with unittest.mock.patch.dict(os.environ, {"AFS_TICKET": "HR-04D"}):
                    self.assertIsNone(m.write_survivors(["src/a.py:5 Mutant #3"], 0.5, 0.8, 1, 1, "main"),
                                      "no .migration/: nothing to write")
                    os.mkdir(".migration")
                    path = m.write_survivors(["src/a.py:5 Mutant #3", "src/b.py:9 Mutant #7"], 0.5, 0.8, 2, 2, "main")
                    text = path.read_text()
                self.assertEqual(path.as_posix(), ".migration/evidence/mutants/HR-04D.md")
                self.assertIn("- `src/b.py:9 Mutant #7`", text)
                self.assertIn("score 0.500, threshold 0.8", text)
                with unittest.mock.patch.dict(os.environ, {"AFS_TICKET": "adhoc"}):
                    self.assertIsNone(m.write_survivors([], 1.0, 0.8, 1, 0, "main"), "no ticket: nothing to write")
            finally:
                os.chdir(cwd)

    def test_survivor_diffs_come_from_mutmut_show(self):
        def fake_run(cmd, **kw):
            if cmd[:2] == ["mutmut", "run"]:
                return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="")
            if cmd[:2] == ["mutmut", "junitxml"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=JUNIT, stderr="")
            if cmd[:2] == ["mutmut", "show"]:
                self.assertEqual(cmd[2], "3")
                return subprocess.CompletedProcess(cmd, 0, stdout="--- src/a.py\n+++ src/a.py\n@@ -5 +5 @@\n"
                                                   "-    return a + b\n+    return a - b\n", stderr="")
            raise AssertionError(cmd)

        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(m.subprocess, "run", fake_run):
            _, _, _, diffs = m.run_shard(0, d, ["src/a.py"], {"src/a.py": "x"}, {})
        self.assertEqual(diffs, {"src/a.py:5 Mutant #3": "@@ -5 +5 @@\n-    return a + b\n+    return a - b"})

    def test_survivor_file_shows_each_mutants_diff(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            try:
                os.chdir(d)
                os.mkdir(".migration")
                with unittest.mock.patch.dict(os.environ, {"AFS_TICKET": "DM-05C"}):
                    path = m.write_survivors(["src/a.py:5 Mutant #3", "src/a.py:9 Mutant #4"], 0.5, 0.8, 2, 2, "main",
                                             {"src/a.py:5 Mutant #3": "-    return a + b\n+    return a - b"})
                text = path.read_text()
            finally:
                os.chdir(cwd)
        self.assertIn("- `src/a.py:5 Mutant #3`\n\n  ```diff\n  -    return a + b\n  +    return a - b\n  ```", text)
        self.assertIn("- `src/a.py:9 Mutant #4`", text, "a survivor without a diff is still listed")

    def test_default_excludes(self):
        ex = m.DEFAULT_EXCLUDE
        self.assertFalse(m.keep("src/app/migrations/0001_initial.py", ex))
        self.assertFalse(m.keep("src/cargotracker/settings.py", ex))
        self.assertFalse(m.keep("tests/test_x.py", ex))
        self.assertTrue(m.keep("src/cargotracker/voyage/domain/voyage.py", ex))

    def test_context_tests_and_shards(self):
        with tempfile.TemporaryDirectory() as t:
            cwd = pathlib.Path.cwd()
            import os
            os.chdir(t)
            try:
                pathlib.Path("tests/cargo").mkdir(parents=True)
                self.assertEqual(m.context_tests("src/app/cargo/domain/x.py", "src"), "tests/cargo")
                self.assertIsNone(m.context_tests("src/app/voyage/domain/x.py", "src"))
                self.assertIsNone(m.context_tests("src/calc.py", "src"))
                self.assertIn("tests/cargo", m.runner_for(["src/app/cargo/a.py"], "src", "auto"))
                self.assertNotIn("tests/", m.runner_for(["src/app/cargo/a.py", "src/calc.py"], "src", "auto"))
            finally:
                os.chdir(cwd)
        groups = m.shards(["a.py", "b.py", "c.py"], 2)
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(sum(groups, [])), ["a.py", "b.py", "c.py"])
        self.assertEqual(len(m.shards(["a.py"], 4)), 1)

    @unittest.skipUnless(m.has_pytest_cov(), "pytest-cov not installed")
    def test_coverage_picks_the_tests_that_execute_each_file(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / "src").mkdir()
            (t / "src/alpha.py").write_text("def a():\n    return 1\n")
            (t / "src/beta.py").write_text("def b():\n    return 2\n")
            (t / "tests").mkdir()
            (t / "tests/test_alpha.py").write_text("import sys\nsys.path.insert(0, 'src')\nfrom alpha import a\n\n\n"
                                                    "def test_a():\n    assert a() == 1\n")
            (t / "tests/test_beta.py").write_text("import sys\nsys.path.insert(0, 'src')\nfrom beta import b\n\n\n"
                                                   "def test_b():\n    assert b() == 2\n")
            import os
            cwd = os.getcwd()
            os.chdir(t)
            try:
                mapping = m.covering_tests(["src/alpha.py", "src/beta.py"], "src", ["tests"])
            finally:
                os.chdir(cwd)
            self.assertEqual(mapping["src/alpha.py"], ["tests/test_alpha.py::test_a"])
            self.assertEqual(mapping["src/beta.py"], ["tests/test_beta.py::test_b"])

    @unittest.skipUnless(shutil.which("mutmut"), "mutmut not installed")
    def test_parallel_run_matches_serial(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / "src").mkdir()
            (t / "src/calc.py").write_text("def add(a, b):\n    return a + b\n")
            (t / "src/more.py").write_text("def mul(a, b):\n    return a * b\n")
            (t / "tests").mkdir()
            (t / "tests/test_calc.py").write_text(
                "import sys\nsys.path.insert(0, 'src')\nfrom calc import add\nfrom more import mul\n\n\n"
                "def test_ops():\n    assert add(2, 3) == 5\n    assert mul(2, 3) == 6\n")
            (t / "setup.cfg").write_text("[mutmut]\ntests_dir=tests/\n")
            out = {}
            for jobs in ("1", "2"):
                r = subprocess.run([sys.executable, str(ROOT / "tools/afs-mutation"), "--paths", "src/calc.py,src/more.py",
                                    "--threshold", "0.5", "--jobs", jobs], cwd=t, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                out[jobs] = r.stdout.split("score=")[1].split()[0]
                self.assertIn(f"jobs={jobs}", r.stdout)
            self.assertEqual(out["1"], out["2"])

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
            result = [l for l in low.stdout.splitlines() if l.startswith("AFS-RESULT ")]
            self.assertEqual(len(result), 1, low.stdout)
            self.assertRegex(result[0], r"^AFS-RESULT gate=mutation score=0\.\d{3} threshold=0\.4 killed=\d+ survived=\d+")
            # A test that fails on unmutated code makes mutmut abort: no score, exit 2, never a silent drop.
            (t / "tests/test_calc.py").write_text(
                "import sys\nsys.path.insert(0, 'src')\nfrom calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 6\n")
            broken = run("0.4")
            self.assertEqual(broken.returncode, 2, broken.stdout + broken.stderr)
            self.assertIn("mutmut failed on src/calc.py", broken.stderr)
            self.assertIn("AFS-RESULT gate=mutation score=n/a error=mutmut-failed", broken.stdout)
            (t / "tests/test_calc.py").write_text(
                "import sys\nsys.path.insert(0, 'src')\nfrom calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
            high = run("0.99")
            self.assertEqual(high.returncode, 1, high.stdout + high.stderr)
            self.assertIn("survived: ", high.stdout)


if __name__ == "__main__":
    unittest.main()
