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


class HealthTest(unittest.TestCase):
    """Step 5.1 (ADR-0071): per-slice test health from a target's own records, and the per-ticket trend."""

    def test_health_reads_returns_journals_flaky_records_tests_and_specs(self):
        import subprocess
        import yaml
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d) / "target"
            mig = t / ".migration"
            for sub in ("plan", "returns", "evidence/runs", "evidence/flaky", "spec/fees", "ledger"):
                (mig / sub).mkdir(parents=True)
            (mig / "profile.yaml").write_text("gates:\n  tests: [pytest -q, python .migration/harness/tools/afs-spec run]\n")
            (mig / "plan/fees.tickets.yaml").write_text(yaml.safe_dump({"slice": "fees", "tickets": [
                {"id": "LL-03", "role": "afs-migrator", "files": ["src/fees/", "tests/fees/"], "blocked_by": []},
                {"id": "LL-09", "role": "afs-migrator", "files": ["src/fees/", "tests/fees/"], "blocked_by": ["LL-03"]},
                {"id": "LL-10", "role": "afs-migrator", "files": ["src/fees/"], "blocked_by": []}]}))
            head = "| UTC | Gate | Exit | Seconds | Command | Log SHA-256 | First highlight | Result |\n|---|---|---|---|---|---|---|---|\n"
            for tid, score, crap, secs in (("LL-03", 0.8, 7, 11.7), ("LL-09", 0.93, 9, 12.5)):
                (mig / f"returns/{tid}.afs-migrator.yaml").write_text(yaml.safe_dump({"gates": {"mutation_changed": score}}))
                (mig / f"evidence/runs/{tid}.md").write_text(head +
                    f"| 2026-11-20T10:00:00Z | verifier-crap | 0 | 2.0 | `crap.py` | a | - | gate=crap max={crap} |\n"
                    f"| 2026-11-20T10:01:00Z | behaviour | 1 | 99.0 | `pytest -q` | a | - |  |\n"
                    f"| 2026-11-20T10:02:00Z | my-label | 0 | {secs} | `pytest -q` | a | - |  |\n")
            (mig / "evidence/flaky/LL-09.md").write_text("# Flaky runs\n\n## `pytest -q`\n- x\n\n## `pytest -q`\n- y\n")
            (t / "src/fees").mkdir(parents=True)
            (t / "src/fees/views.py").write_text("def fee():\n    return 1\n")
            (t / "tests/fees").mkdir(parents=True)
            (t / "tests/fees/test_fee.py").write_text(
                "from unittest import mock\nfrom fees import views\n\ndef test_a():\n"
                "    with mock.patch('fees.views.fee'):\n        assert views._cache\n")
            (mig / "ledger/fees.calc.yaml").write_text(yaml.safe_dump({"id": "fees.calc", "rules": [{"id": "r"}]}))
            (mig / "spec/fees/late.yaml").write_text(yaml.safe_dump({"capability": "fees.calc", "cases": [
                {"title": "a fee", "rule": "r", "examples": {"columns": ["x"], "rows": [[1], [2]]},
                 "when": {"http": {"method": "GET", "path": "/f/{x}"}}, "then": {"status": 200}}]}))
            for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
                subprocess.run(["git", *cmd], cwd=t, check=True, capture_output=True)
            slices, tickets = dash.health([t])
        self.assertEqual([(r["ticket"], r["mutation"], r["crap_max"], r["tests_seconds"], r["flaky"]) for r in tickets],
                         [("LL-03", 0.8, 7.0, 11.7, 0), ("LL-09", 0.93, 9.0, 12.5, 2)])   # LL-10 has no return yet
        (row,) = slices
        self.assertEqual({k: row[k] for k in ("slice", "tickets", "mutation_first", "mutation_last", "crap_max",
                                              "tests_seconds", "flaky", "own_patches", "private", "spec_cases")},
                         {"slice": "fees", "tickets": 2, "mutation_first": 0.8, "mutation_last": 0.93, "crap_max": 9.0,
                          "tests_seconds": 12.5, "flaky": 2, "own_patches": 1, "private": 1, "spec_cases": 2})
        self.assertEqual(row["coupling"], 0.0)               # one commit changed the code and only added tests


class RefactorCostTest(unittest.TestCase):
    """ADR-0072: the tests a refactor's landing commit had to modify are its coupling measurement."""

    def test_the_merge_that_landed_the_refactor_is_measured(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d)
            run = lambda *a: subprocess.run(["git", *a], cwd=t, check=True, capture_output=True)
            who = ["-c", "user.name=t", "-c", "user.email=t@t"]
            (t / "tests/fees").mkdir(parents=True)
            (t / "tests/fees/test_a.py").write_text("x = 1\n")
            (t / "tests/fees/test_b.py").write_text("y = 1\n")
            (t / ".migration/returns").mkdir(parents=True)
            run("init", "-q", "-b", "main")
            run("add", "-A")
            run(*who, "commit", "-qm", "base")
            run("checkout", "-q", "-b", "ref")
            (t / "tests/fees/test_a.py").write_text("x = 2\n")              # the refactor had to change one test
            (t / "tests/fees/test_new.py").write_text("z = 1\n")            # added tests don't count
            ret = t / ".migration/returns/REF-1.afs-migrator.yaml"
            ret.write_text("ticket: REF-1\n")
            run("add", "-A")
            run(*who, "commit", "-qm", "refactor")
            run("checkout", "-q", "main")
            run(*who, "merge", "-q", "--no-ff", "ref", "-m", "Merge REF-1")
            self.assertEqual(dash.refactor_cost(t, ret, ["tests/fees/"]), 1)
