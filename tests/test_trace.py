"""ADR-0027: every installed harness tool announces that it ran (afs_trace), so coverage is exact."""
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import bootstrap  # noqa: E402


class TraceTest(unittest.TestCase):
    def test_every_installed_tool_runs_through_afs_trace(self):
        for t in bootstrap.HARNESS_TOOLS:
            path = ROOT / "tools" / t
            if t.startswith("locks/") or t == "afs_trace.py" or path.suffix in (".json", ".yaml", ".lock", ".java"):   # data or non-Python sources, not tools
                continue
            with self.subTest(tool=t):
                entry = path.read_text(encoding="utf-8").rsplit('if __name__ == "__main__":', 1)[-1]
                self.assertIn("afs_trace.run(", entry, f"{t}: its entry point must be afs_trace.run(main)")

    def test_marker_carries_the_exit_code(self):
        ok = subprocess.run([sys.executable, str(ROOT / "tools/check_graph.py"), "--help"], capture_output=True, text=True)
        self.assertIn("AFS-TOOL check_graph.py exit=0", ok.stderr)
        bad = subprocess.run([sys.executable, str(ROOT / "tools/graph_gate.py"), "--side", "nope"], capture_output=True,
                             text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("AFS-TOOL graph_gate.py exit=2", bad.stderr)


if __name__ == "__main__":
    unittest.main()
