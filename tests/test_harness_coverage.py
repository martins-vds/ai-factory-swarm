"""tools/harness_coverage.py (ADR-0027): coverage computed from the installed harness and the repo's history."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools/harness_coverage.py"


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        h = self.d / ".migration/harness"
        shutil.copytree(ROOT / "schemas", h / "schemas")
        (h / "tools").mkdir(parents=True)
        entry = 'def main():\n    return 0\n\n\nif __name__ == "__main__":\n    import afs_trace\n    afs_trace.run(main)\n'
        for t in ("validate.py", "crap.py", "never.py", "check_inputs.py"):
            (h / "tools" / t).write_text(entry)
        (h / "tools" / "afs_trace.py").write_text('"""A tool\'s entry point is `afs_trace.run(main)`."""\ndef run(main):\n    pass\n')  # a library that names the call, not a tool

    def tearDown(self):
        shutil.rmtree(self.d)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.d), *args], check=True, capture_output=True)

    def commit(self, files, msg):
        for name, text in files.items():
            p = self.d / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)

    def report(self):
        r = subprocess.run([sys.executable, str(TOOL), "--offline"], cwd=self.d, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_history_counts_every_version_and_both_paths(self):
        row = "| 2026-11-01T00:00:00+00:00 | {g} | {code} | 1.0 | `python .migration/harness/tools/{t}` | `x` |  |  |\n"
        head = "| UTC | Gate | Exit | Seconds | Command | Log SHA-256 | First highlight | Result |\n|---|---|---|---|---|---|---|---|\n"
        self.commit({".migration/ledger/a.yaml": "id: a\nstatus: pending\nverification: pending\n",
                     ".migration/returns/T-1.afs-verifier.yaml": "role: afs-verifier\nticket: T-1\nverdict: changes-required\n",
                     ".migration/evidence/runs/T-1.md": head + row.format(g="crap", code=1, t="crap.py")}, "first")
        self.commit({".migration/ledger/a.yaml": "id: a\nstatus: dropped\nverification: review-only\n",
                     ".migration/returns/T-1.afs-verifier.yaml": "role: afs-verifier\nticket: T-1\nverdict: pass\n",
                     ".migration/evidence/runs/T-1.md": head + row.format(g="crap", code=1, t="crap.py")
                     + row.format(g="crap", code=0, t="crap.py") + row.format(g="validate", code=0, t="validate.py")},
                    "second")
        self.commit({".migration/costs/s1.json": '{"schema": "afs-cost/1", "harness_tools": ['
                     '{"tool": "check_inputs.py", "exit": 1, "count": 1}, {"tool": "check_inputs.py", "exit": 0, '
                     '"count": 2}, {"tool": "not-a-tool", "exit": 0, "count": 1}]}'}, "agent session")
        out = self.report()
        self.assertIn("✅ `afs-verifier`: 2 return file version(s)", out)
        self.assertIn("❌ `afs-planner`: 0 return file version(s)", out)
        self.assertIn("✅ `afs-verifier` `verdict: changes-required`", out, "an overwritten version still counts")
        self.assertIn("✅ `afs-verifier` `verdict: pass`", out)
        self.assertIn("❌ `afs-verifier` `verdict: blocked`", out)
        self.assertIn("✅ `status: pending`", out)
        self.assertIn("✅ `status: dropped`", out)
        self.assertIn("❌ `status: deferred`", out)
        self.assertIn("✅ `crap.py`: passed 1, failed 1 (journal)", out)
        self.assertIn("⚠️ `validate.py`: passed 1, failed 0 (journal)", out, "never seen failing")
        self.assertIn("❌ `never.py`: passed 0, failed 0", out)
        self.assertIn("✅ `check_inputs.py`: passed 2, failed 1 (agent session)", out, "runs recorded by the session hook")
        self.assertNotIn("afs_trace.py", out, "a library is not a tool")
        self.assertRegex(out, r"\*\*\d+ of \d+ paths exercised; \d+ to go\.\*\*")


if __name__ == "__main__":
    unittest.main()
