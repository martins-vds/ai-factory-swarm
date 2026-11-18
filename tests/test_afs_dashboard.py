"""tools/afs-dashboard: the operator dashboard's data."""
import importlib.machinery
import importlib.util
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("afs_dashboard", str(ROOT / "tools/afs-dashboard"))
_spec = importlib.util.spec_from_loader("afs_dashboard", _loader)
dash = importlib.util.module_from_spec(_spec)
_loader.exec_module(dash)


class TrendTest(unittest.TestCase):
    def test_majority_per_case_and_kind_per_family(self):
        with tempfile.TemporaryDirectory() as d:
            for n, (v, m) in enumerate([(True, True), (True, False), (False, False)], 1):
                pathlib.Path(d, f"2026-11-17-v3x-r{n}.json").write_text(json.dumps({"cases": {
                    "a-verify": {"passed": v, "usage": {"minutes": 10.0 * n}},
                    "b": {"passed": m}}}))
            pathlib.Path(d, "2026-11-17-v3x-r1.state.json").write_text("{}")
            pathlib.Path(d, "2026-11-17-v3x-summary.md").write_text("x")
            fams, cases = dash.trend(d)
        self.assertEqual(len(fams), 1)
        f = fams[0]
        self.assertEqual((f["family"], f["runs"], f["verifier_passed"], f["verifier_cases"]), ("v3x", 3, 1, 1))
        self.assertEqual((f["migrator_passed"], f["migrator_cases"], f["median_minutes"]), (0, 1, 20.0))
        self.assertEqual({(c["case"], c["passes"], c["passed"]) for c in cases},
                         {("a-verify", 2, True), ("b", 1, False)})

    def test_write_carries_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d, "x.json")
            dash.write(out, [{"a": 1}], "input")
            doc = json.loads(out.read_text())
        self.assertEqual(doc["rows"], [{"a": 1}])
        self.assertEqual(doc["meta"][0]["type"], "code")
        self.assertIn("def needs(", doc["meta"][0]["value"])

    def test_tie_is_not_a_majority_and_zero_is_reported_usage(self):
        with tempfile.TemporaryDirectory() as d:
            for n in (1, 2):
                pathlib.Path(d, f"2026-11-17-v3x-r{n}.json").write_text(json.dumps({
                    "cases": {"a": {"passed": n == 1, "usage": {"minutes": 0}}}}))
            fams, cases = dash.trend(d)
        self.assertFalse(cases[0]["passed"])
        self.assertEqual(fams[0]["median_minutes"], 0)


class GitHubDataTest(unittest.TestCase):
    repo = "example/repo"
    now = dt.datetime(2026, 11, 18, 12, tzinfo=dt.timezone.utc)
    bot = {"login": "Copilot"}

    def ago(self, minutes):
        return (self.now - dt.timedelta(minutes=minutes)).isoformat()

    def test_needs_groups_runs_and_uses_oldest_and_pr(self):
        pull = {"number": 2, "title": "draft", "created_at": self.ago(30),
            "draft": True, "html_url": f"https://github.com/{self.repo}/pull/2",
            "head": {"ref": "copilot/work", "sha": "abc"}}
        ready = {**pull, "number": 3, "draft": False, "head": {**pull["head"], "ref": "copilot/ready"}}
        run = {"head_branch": "copilot/work", "pull_requests": []}

        def pages(path, key=None):
            if key:
                return [{**run, "created_at": self.ago(n)} for n in (5, 65, 50)]
            if path.endswith("/files?per_page=100"):
                return [{"filename": "x.afs-slice-coordinator.yaml"}] if "/2/" in path else []
            return [pull, ready]

        with patch.object(dash, "pages", pages), patch.object(dash, "gh", return_value="human_check: requested"):
            rows = dash.needs([self.repo])
        self.assertEqual([(r["kind"], r["number"]) for r in rows],
                     [("Approve workflow runs", 2), ("Side-by-side check", 2), ("Merge pull request", 3)])
        self.assertEqual(rows[0]["waiting_since"], self.ago(65))
        self.assertEqual(rows[0]["title"], "3 run(s) on copilot/work")

    def test_session_lifecycle_and_linked_approval(self):
        def issue(n):
            return {"number": n, "assignees": [self.bot], "state": "open", "updated_at": self.ago(0),
                    "title": "Verify BK-05G", "body": "**Role:** `afs-verifier`", "html_url": "issue url"}

        def pr(n, title, created):
            return {"number": n, "title": title, "user": self.bot, "state": "open", "updated_at": self.ago(0),
                    "created_at": self.ago(created), "html_url": "pr url", "head": {"ref": f"copilot/{n}", "sha": str(n)},
                    "base": {"ref": "eval/2026-11-18-4ra-r1/synthetic-ll-02"}}

        pulls = [pr(10, "[WIP] fresh", 8), pr(20, "[WIP] re-dispatch", 200), pr(30, "Done", 55)]
        histories = {
            1: [{"event": "assigned", "assignee": self.bot, "created_at": self.ago(7)}],
            2: [
                {"event": "assigned", "assignee": self.bot, "created_at": self.ago(n)} for n in (201, 52)
            ],
            3: [{"event": "assigned", "assignee": self.bot, "created_at": self.ago(56)}],
            4: [{"event": "assigned", "assignee": self.bot, "created_at": self.ago(16)}],
            30: [{"event": "renamed", "created_at": self.ago(5), "rename": {"from": "[WIP] Done", "to": "Done"}}],
        }
        for i, p in enumerate(pulls, 1):
            histories[i].append({"event": "cross-referenced", "source": {"issue": {
                **p, "repository_url": f"https://api.github.com/repos/{self.repo}", "pull_request": {},
            }}})

        def timeline(repo, n, **kwargs):
            return histories[n]

        def pages(path, **kwargs):
            if "/pulls?" in path:
                return pulls
            return [] if "state=closed" in path else [issue(n) for n in range(1, 5)]

        approval = {"branch": "copilot/20", "id": "approval"}
        with patch.object(dash, "pages", pages), patch.object(dash, "timeline", timeline), \
                patch.object(dash, "approval_needs", return_value=[approval]), \
                patch.object(dash, "gh", return_value={"commit": {"committer": {"date": self.ago(5)}}}):
            rows = {r["issue"]: r for r in dash.repo_sessions(self.repo, self.now)}
        self.assertEqual(rows[1]["started_at"], self.ago(8))
        self.assertEqual(rows[2]["started_at"], self.ago(52))
        self.assertEqual(rows[2]["approval"], approval)
        self.assertEqual(rows[2]["agent"], "afs-verifier")
        self.assertEqual(rows[2]["ticket"], "BK-05G")
        self.assertEqual((rows[2]["run"], rows[2]["case"]), ("2026-11-18-4ra-r1", "synthetic-ll-02"))
        self.assertEqual((rows[3]["status"], rows[3]["finished_at"]), ("finished", self.ago(5)))
        self.assertEqual((rows[4]["status"], rows[4]["pr"]), ("starting", None))


if __name__ == "__main__":
    unittest.main()
