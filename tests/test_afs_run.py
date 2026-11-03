#!/usr/bin/env python3
"""Tests for tools/afs-run."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

AFS_RUN = pathlib.Path(__file__).resolve().parent.parent / "tools" / "afs-run"


def afs(runs, *cmd, ticket="T-1", extra=()):
    return subprocess.run([sys.executable, str(AFS_RUN), "--ticket", ticket, "--runs-dir", runs, *extra, "--", *cmd],
                          capture_output=True, text=True)


class AfsRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def records(self, ticket="T-1"):
        path = pathlib.Path(self.runs, ticket, "runs.jsonl")
        return [json.loads(l) for l in path.read_text().splitlines()]

    def test_the_command_knows_its_ticket(self):
        r = afs(self.runs, sys.executable, "-c", "import os; print('ticket=' + os.environ['AFS_TICKET'])",
                ticket="HR-04D")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = next(pathlib.Path(self.runs, "HR-04D").glob("*.log")).read_text()
        self.assertIn("ticket=HR-04D", log)

    def test_success_keeps_full_log_and_short_summary(self):
        script = "for i in $(seq 1 500); do echo line $i; done"
        r = afs(self.runs, "bash", "-c", script, extra=("--name", "loop"))
        self.assertEqual(r.returncode, 0)
        self.assertIn("loop ok exit=0", r.stdout)
        self.assertLess(len(r.stdout.splitlines()), 25, "summary must stay short")
        rec = self.records()[0]
        log = pathlib.Path(rec["log"]).read_text()
        self.assertEqual(len(log.splitlines()), 500, "raw log must be complete")
        self.assertEqual(rec["exit"], 0)
        self.assertEqual(rec["lines"], 500)

    def test_failure_propagates_exit_code_and_highlights_errors(self):
        script = ("for i in $(seq 1 300); do echo ok $i; done; "
                  "echo 'tests/test_x.py:12: AssertionError: expected 3, got 2' >&2; "
                  "echo '1 failed, 10 passed'; exit 3")
        r = afs(self.runs, "bash", "-c", script)
        self.assertEqual(r.returncode, 3)
        self.assertIn("FAILED exit=3", r.stdout)
        self.assertIn("AssertionError: expected 3, got 2", r.stdout)
        self.assertIn("1 failed, 10 passed", r.stdout)
        self.assertIn("-- last", r.stdout)

    def test_success_lines_are_not_highlighted(self):
        r = afs(self.runs, "bash", "-c", "echo 'Tests run: 5, Failures: 0, Errors: 0'; echo 'BUILD SUCCESS'")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("highlights", r.stdout)

    def test_repeated_errors_are_collapsed(self):
        script = "for i in $(seq 1 200); do echo \"ERROR row $i rejected\"; done; exit 1"
        r = afs(self.runs, "bash", "-c", script)
        highlights = [l for l in r.stdout.splitlines() if "ERROR row" in l and l.strip()[0].isdigit()]
        self.assertEqual(len(highlights), 1)

    def test_missing_command(self):
        r = afs(self.runs, "definitely-not-a-command-xyz")
        self.assertEqual(r.returncode, 127)
        self.assertIn("command not found", r.stdout)

    def test_runs_accumulate_per_ticket(self):
        afs(self.runs, "true")
        afs(self.runs, "false")
        afs(self.runs, "true", ticket="T-2")
        self.assertEqual([r["exit"] for r in self.records()], [0, 1])
        self.assertEqual(len(self.records("T-2")), 1)

    def test_usage_without_separator(self):
        r = subprocess.run([sys.executable, str(AFS_RUN), "echo", "x"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_journal_records_the_tools_result_line(self):
        j = pathlib.Path(self.runs, "journal")
        script = "echo noise; echo 'AFS-RESULT gate=mutation score=0.700 threshold=0.8'; echo 'AFS-RESULT gate=mutation score=0.812 threshold=0.8'"
        afs(self.runs, "bash", "-c", script, extra=("--journal-dir", str(j), "--name", "mut"))
        text = (j / "T-1.md").read_text()
        self.assertIn("| Result |", text)
        row = [l for l in text.splitlines() if "| mut |" in l][0]
        self.assertTrue(row.rstrip().endswith("| gate=mutation score=0.812 threshold=0.8 |"), row)

    def test_old_journal_gains_the_result_column(self):
        j = pathlib.Path(self.runs, "journal"); j.mkdir()
        (j / "T-1.md").write_text("# Run journal: T-1\n\n"
                                  "| UTC | Gate | Exit | Seconds | Command | Log SHA-256 | First highlight |\n"
                                  "|---|---|---|---|---|---|---|\n"
                                  "| 2026-11-01T00:00:00+00:00 | old | 0 | 1.0 | `true` | `abc` |  |\n")
        afs(self.runs, "true", extra=("--journal-dir", str(j), "--name", "new"))
        lines = (j / "T-1.md").read_text().splitlines()
        self.assertIn("| Result |", lines[2])
        self.assertEqual(lines[3].count("|"), 9)
        self.assertTrue(all(l.count("|") == 9 for l in lines[4:]), lines)


if __name__ == "__main__":
    unittest.main()
