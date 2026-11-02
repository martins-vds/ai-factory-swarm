"""tools/check_runtime.py: declared runtimes from the profile, and version matching (ADR-0018)."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_runtime as cr  # noqa: E402


class RuntimeTest(unittest.TestCase):
    def test_declared_runtimes_from_target_stacks(self):
        prof = {"target": {"stacks": {"backend": ["Python-3.13", "django-5"], "frontend": ["node-22"],
                                      "data": ["postgresql-17"]}}}
        self.assertEqual(cr.declared(prof), [("python", "3.13"), ("node", "22")])
        self.assertEqual(cr.python_version(prof), "3.13")
        self.assertEqual(cr.python_version({}), "3.12")

    def test_version_matching(self):
        self.assertTrue(cr.matches("3.13", "3.13.1"))
        self.assertTrue(cr.matches("22", "22"))
        self.assertFalse(cr.matches("3.13", "3.12.15"))
        self.assertFalse(cr.matches("3.1", "3.13.0"))
        self.assertFalse(cr.matches("3.13", None))

    def run_tool(self, stacks):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "profile.yaml"
            p.write_text("target: {stacks: {backend: [%s]}}\n" % stacks)
            return subprocess.run([sys.executable, str(ROOT / "tools/check_runtime.py"), "--profile", str(p)],
                                  capture_output=True, text=True,
                                  env={"PATH": str(pathlib.Path(sys.executable).parent)})

    def test_cli_reports_a_mismatch(self):
        here = "%d.%d" % sys.version_info[:2]
        if pathlib.Path(sys.executable).name != "python" and not (pathlib.Path(sys.executable).parent / "python").exists():
            self.skipTest("no `python` next to the test interpreter")
        self.assertEqual(self.run_tool(f"python-{here}").returncode, 0)
        r = self.run_tool("python-2.7")
        self.assertEqual(r.returncode, 1)
        self.assertIn("profile declares 2.7", r.stderr)


if __name__ == "__main__":
    unittest.main()
