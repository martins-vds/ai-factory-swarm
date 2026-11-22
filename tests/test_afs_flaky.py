"""afs-flaky (ADR-0070): flaky runs from agent sessions and CI re-runs become one ticket per test."""
import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("afs_flaky", str(ROOT / "tools/afs-flaky"))
spec = importlib.util.spec_from_loader("afs_flaky", loader)
fl = importlib.util.module_from_spec(spec)
loader.exec_module(fl)

RECORD = """# Flaky runs: LL-03

Written by afs-run (ADR-0070): ...

## `pytest -q`
- failed: 2026-11-22T14:10:00+00:00 (exit 1, log `.migration/runs/LL-03/x.log`)
- passed: 2026-11-22T14:12:00+00:00, same code (tree `abc123def456`)
- tests that failed: `tests/fees/test_views.py::test_browser_pay`, `tests/fees/test_views.py::test_alert`
"""


class FakeGitHub:
    def __init__(self, issues=(), comments=None):
        self.issues = list(issues)
        self.comments = comments or {}
        self.calls = []

    def __call__(self, path, method="GET", body=None):
        self.calls.append((method, path, body))
        if path.startswith("repos/o/t/actions/runs?"):
            return {"workflow_runs": [
                {"id": 7, "name": "AFS harness check", "run_attempt": 2, "conclusion": "success",
                 "head_sha": "f00dfeed1234", "html_url": "https://x/runs/7"},
                {"id": 8, "name": "AFS harness check", "run_attempt": 1, "conclusion": "failure", "head_sha": "b"}]}
        if path == "repos/o/t/actions/runs/7/attempts/2/jobs":
            return {"jobs": [{"id": 72, "name": "Gates", "conclusion": "success"}]}
        if path == "repos/o/t/actions/runs/7/attempts/1/jobs":
            return {"jobs": [{"id": 71, "name": "Gates", "conclusion": "failure", "html_url": "https://x/jobs/71"},
                             {"id": 70, "name": "Lint", "conclusion": "failure"}]}
        if path == "repos/o/t/actions/jobs/71/logs":
            return "2026-11-22T10:00:00Z FAILED tests/fees/test_views.py::test_browser_pay - Timeout\n"
        if path.startswith("repos/o/t/issues?"):
            return self.issues
        if path.startswith("repos/o/t/issues/") and path.endswith("comments?per_page=100"):
            return self.comments.get(int(path.split("/")[4]), [])
        if method == "POST" and path == "repos/o/t/issues":
            return {"number": 99, "body": body["body"]}
        return {}


class FlakyTest(unittest.TestCase):
    def test_records_name_each_failing_test(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "LL-03.md").write_text(RECORD)
            got = fl.records(d)
        self.assertEqual([g["id"] for g in got], ["tests/fees/test_views.py::test_browser_pay",
                                                  "tests/fees/test_views.py::test_alert"])
        self.assertIn("ticket LL-03: `pytest -q` failed 2026-11-22T14:10:00+00:00", got[0]["evidence"])

    def test_a_job_that_failed_then_passed_on_a_rerun_is_flaky_and_one_that_stayed_red_is_not(self):
        got = fl.ci_flakes("o/t", 7, call=FakeGitHub())
        self.assertEqual([g["id"] for g in got], ["tests/fees/test_views.py::test_browser_pay"])
        self.assertIn("AFS harness check › Gates on `f00dfee`: failed on attempt 1", got[0]["evidence"])

    def test_one_issue_per_test_and_evidence_is_never_repeated(self):
        flakes = [{"id": "t::a", "source": "CI re-run", "evidence": "run 7"},
                  {"id": "t::b", "source": "CI re-run", "evidence": "run 7"}]
        existing = {"number": 5, "body": fl.marker("t::a") + "\n- run 6"}
        gh = FakeGitHub(issues=[existing], comments={5: [{"body": "Flaky again:\n- run 7"}]})
        self.assertEqual(fl.tickets("o/t", flakes, call=gh), ["open: t::b"])     # t::a already has run 7
        opened = [b for m, p, b in gh.calls if m == "POST" and p == "repos/o/t/issues"]
        self.assertEqual(opened[0]["labels"], ["afs-flaky"])
        self.assertIn("Fix the test, not the retry", opened[0]["body"])
        gh2 = FakeGitHub(issues=[existing])
        self.assertEqual(fl.tickets("o/t", flakes[:1], call=gh2), ["comment #5: t::a"])
        self.assertEqual(fl.tickets("o/t", flakes, dry_run=True, call=FakeGitHub()), ["open: t::a", "open: t::b"])

    def test_the_same_test_from_a_record_and_from_ci_is_one_issue(self):
        flakes = [{"id": "t::a", "source": "agent", "evidence": "LL-03"}, {"id": "t::a", "source": "CI", "evidence": "run 7"}]
        self.assertEqual(fl.tickets("o/t", flakes, dry_run=True, call=FakeGitHub()), ["open: t::a", "comment #None: t::a"])
