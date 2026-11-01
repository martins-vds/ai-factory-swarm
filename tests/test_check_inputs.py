"""tools/check_inputs.py: which tokens count as named inputs, and the exit code."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_inputs  # noqa: E402

TICKET = ("Inputs: `.migration/graphs/source/full/knowledge-graph.json`, `docs/adr/0001-*.md`.\n"
          "Write `.migration/returns/TC-04.afs-migrator.yaml`; load `afs-ledger`; see `martins-vds/x#3`, "
          "`https://example.org/a`, `<ticket>`, `pytest -q`.\n")


class CheckInputsTest(unittest.TestCase):
    def test_candidates_skip_outputs_skills_refs_urls_placeholders_and_commands(self):
        self.assertEqual(check_inputs.candidates(TICKET),
                         [".migration/graphs/source/full/knowledge-graph.json", "docs/adr/0001-*.md"])

    def test_exit_code_reflects_missing_inputs(self):
        with tempfile.TemporaryDirectory() as t:
            run = lambda: subprocess.run([sys.executable, str(ROOT / "tools/check_inputs.py")], input=TICKET,
                                         cwd=t, capture_output=True, text=True)
            r = run()
            self.assertEqual(r.returncode, 1)
            self.assertIn("MISSING .migration/graphs/source/full/knowledge-graph.json", r.stdout)
            os.makedirs(os.path.join(t, ".migration/graphs/source/full"))
            os.makedirs(os.path.join(t, "docs/adr"))
            pathlib.Path(t, ".migration/graphs/source/full/knowledge-graph.json").write_text("{}")
            pathlib.Path(t, "docs/adr/0001-x.md").write_text("x")
            self.assertEqual(run().returncode, 0)

    def test_a_named_prefix_matches_an_existing_file(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "docs/adr"))
            pathlib.Path(t, "docs/adr/0001-ddd-layers.md").write_text("x")
            cwd = os.getcwd()
            os.chdir(t)
            try:
                self.assertTrue(check_inputs.exists("docs/adr/0001"))
                self.assertFalse(check_inputs.exists("docs/adr/0004"))
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
