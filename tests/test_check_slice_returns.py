"""tools/check_slice_returns.py (ADR-0024): a slice epic closes only when every ticket left its return file."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_slice_returns as csr  # noqa: E402

REPO = "o/r"


def sub(n, state="closed", reason="completed", closed_at="2026-11-05T12:00:00Z"):
    return {"number": n, "title": f"T{n}", "state": state, "state_reason": reason if state == "closed" else None,
            "closed_at": closed_at if state == "closed" else None}


class ProblemsTest(unittest.TestCase):
    def test_open_tickets_and_missing_returns_fail(self):
        found = csr.problems(REPO, [sub(1), sub(2), sub(3, state="open"), sub(4, reason="not_planned")],
                             {"o/r#1"}, "2026-11-03T00:00:00+00:00")
        self.assertEqual(found, [
            "#2 T2: closed as completed, but no `.migration/returns/*.yaml` has `issue: o/r#2`",
            "#3 T3: still open"])

    def test_tickets_closed_before_the_rule_are_exempt_but_open_ones_never(self):
        old = "2026-11-01T13:00:00Z"
        found = csr.problems(REPO, [sub(10, closed_at=old), sub(11, state="open")], set(), "2026-11-03T04:00:00+00:00")
        self.assertEqual(found, ["#11 T11: still open"])
        self.assertEqual(len(csr.problems(REPO, [sub(10, closed_at=old)], set(), None)), 1, "no rule date: no exemption")

    def test_returned_issues_reads_committed_return_files(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "TC-02.afs-migrator.yaml").write_text("ticket: TC-02\nissue: o/r#22\n")
            (pathlib.Path(d) / "broken.yaml").write_text("issue: [\n")
            (pathlib.Path(d) / "notes.yaml").write_text("- a list\n")
            self.assertEqual(csr.returned_issues(d), {"o/r#22"})

    def test_rule_date_is_the_commit_that_added_the_tool(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "GIT_COMMITTER_DATE": "2026-11-03T04:00:00+00:00"}
            git = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, env=env)
            git("init", "-q")
            tool = pathlib.Path(d) / csr.SELF
            tool.parent.mkdir(parents=True)
            tool.write_text("v1\n")
            git("add", "-A")
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "install")
            tool.write_text("v2\n")
            env["GIT_COMMITTER_DATE"] = "2026-12-01T00:00:00+00:00"
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "upgrade")
            cwd = os.getcwd()
            try:
                os.chdir(d)
                self.assertEqual(csr.rule_since(), "2026-11-03T04:00:00+00:00", "first install, not the upgrade")
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
