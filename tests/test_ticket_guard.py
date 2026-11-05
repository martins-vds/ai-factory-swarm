"""tools/ticket_guard.py (ADR-0029): a ticket closed before its work reached the default branch is reopened."""
import pathlib
import sys
import unittest
import base64
import contextlib
import io
import json
import os
import subprocess
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ticket_guard  # noqa: E402


class TicketGuardTest(unittest.TestCase):
    def run_guard(self, issue, pulls):
        calls = []

        def gh(path, *args, data=None):
            calls.append((path, args, data))
            if path == "repos/o/r/issues/129":
                return issue if not args else {}
            if path == "repos/o/r":
                return {"default_branch": "main"}
            if path.startswith("repos/o/r/pulls?"):
                return pulls
            return {}
        orig, ticket_guard.gh = ticket_guard.gh, gh
        try:
            self.assertEqual(ticket_guard.main(["--repo", "o/r", "--issue", "129"]), 0)
        finally:
            ticket_guard.gh = orig
        return [c for c in calls if c[1][:2] == ("-X", "PATCH")]

    CLOSED = {"state": "closed", "state_reason": "completed"}

    def test_reopens_when_an_open_pr_into_main_still_fixes_it(self):
        reopened = self.run_guard(self.CLOSED, [{"number": 141, "state": "open", "body": "Work.\n\n- Fixes #129"}])
        self.assertEqual(reopened, [("repos/o/r/issues/129", ("-X", "PATCH"), {"state": "open"})])

    def test_leaves_it_closed_otherwise(self):
        self.assertEqual(self.run_guard(self.CLOSED, [{"number": 7, "state": "open", "body": "Fixes #1290"}]), [],
                         "another issue number")
        self.assertEqual(self.run_guard(self.CLOSED, [{"number": 7, "state": "open", "body": "Mentions #129"}]), [],
                         "a mention is not a fix")
        self.assertEqual(self.run_guard({"state": "closed", "state_reason": "not_planned"},
                                        [{"number": 141, "state": "open", "body": "Fixes #129"}]), [],
                         "closed as not planned")
        self.assertEqual(self.run_guard(self.CLOSED, []), [], "its work PR already merged")

    def test_closing_keywords(self):
        for body in ("fixes #129", "Closes: #129", "resolved o/r#129", "FIX #129"):
            self.assertTrue(ticket_guard.open_fixers([{"state": "open", "body": body}], 129), body)


class TicketReconciliationTest(unittest.TestCase):
    RETURN = """role: afs-verifier
ticket: T1
issue: o/r#1
pr: o/r#101
verdict: pass
gates: null
evidence_logs: []
findings: []
tests_added: []
ledger_issues: []
quirk_tickets: []
"""
    FAILED_RETURN = RETURN.replace("ticket: T1", "ticket: T3").replace("issue: o/r#1", "issue: o/r#3") \
        .replace("pr: o/r#101", "pr: o/r#103").replace("verdict: pass", "verdict: changes-required")
    REPORT = ".migration/evidence/ticket-reconciliation/99.yaml"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def write_report(self, issues):
        path = self.root / self.REPORT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"epic": 99, "scope": "slice-epic-descendants", "issues": issues}),
                        encoding="utf-8")

    def setup_completed_stack(self):
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        (returns / "T1.afs-verifier.yaml").write_text(self.RETURN, encoding="utf-8")
        (returns / "T2.afs-verifier.yaml").write_text(
            self.RETURN.replace("ticket: T1", "ticket: T2").replace("o/r#1", "o/r#2")
            .replace("o/r#101", "o/r#102"), encoding="utf-8")
        (self.root / "work.txt").write_text("accepted work\n", encoding="utf-8")
        head = self.commit("accepted work head")
        (self.root / "carrier.txt").write_text("carried by another PR\n", encoding="utf-8")
        main = self.commit("accepted main")
        self.write_report([
            {"number": 1, "disposition": "completed", "pull_requests": [101],
             "returns": [".migration/returns/T1.afs-verifier.yaml"]},
            {"number": 2, "disposition": "completed", "pull_requests": [102],
             "returns": [".migration/returns/T2.afs-verifier.yaml"]},
        ])
        self.commit("reconciliation evidence")
        return head, main

    def children(self, issues):
        return {f"repos/o/r/issues/{number}/sub_issues?per_page=100&page=1": []
                for number in [99, *(i["number"] for i in issues)]}

    def run_reconciliation(self, issues, pulls, contents=None, *, report_exists=True, labels=None,
                           report_issues=None):
        if report_exists:
            self.write_report(report_issues if report_issues is not None else issues)
            self.commit("reconciliation evidence")
        calls = []
        children = self.children(issues)

        def gh(endpoint, *args, data=None):
            calls.append((endpoint, args, data))
            if endpoint == "repos/o/r/issues/99":
                return {"number": 99, "state": "closed", "labels": [{"name": "afs:slice"}]}
            if endpoint.endswith("/comments") or args:
                return {}
            if endpoint in children:
                if endpoint.endswith("/99/sub_issues?per_page=100&page=1"):
                    return labels if labels is not None else [
                        {"number": i["number"], "title": f"T{i['number']}", "state": "closed",
                         "state_reason": "completed", "labels": []} for i in issues
                    ]
                return []
            if endpoint.startswith("repos/o/r/issues/") and "/sub_issues?" not in endpoint:
                number = int(endpoint.rsplit("/", 1)[1])
                return {"number": number, "state": "open", "title": f"T{number}"}
            if endpoint.startswith("repos/o/r/pulls/"):
                return pulls[int(endpoint.rsplit("/", 1)[1])]
            if endpoint.startswith("repos/o/r/contents/"):
                return contents[endpoint]
            return {}

        output = io.StringIO()
        with mock.patch.object(ticket_guard, "gh", side_effect=gh), \
                contextlib.redirect_stdout(output):
            result = ticket_guard.main(["--repo", "o/r", "--reconcile-epic", "99", "--reopen"])
        return result, output.getvalue(), calls

    def pull(self, number, *, head, merged=False):
        return {"number": number, "state": "closed", "merged_at": "2026-11-05T00:00:00Z" if merged else None,
                "merge_commit_sha": head if merged else None, "head": {"sha": head}}

    def test_completed_stacked_wrappers_accept_merged_and_exact_unmerged_integrated_heads(self):
        head, main = self.setup_completed_stack()
        issues = [
            {"number": 1, "disposition": "completed", "pull_requests": [101],
             "returns": [".migration/returns/T1.afs-verifier.yaml"]},
            {"number": 2, "disposition": "completed", "pull_requests": [102],
             "returns": [".migration/returns/T2.afs-verifier.yaml"]},
        ]
        result, output, _ = self.run_reconciliation(issues, {
            101: self.pull(101, head=main, merged=True),
            102: self.pull(102, head=head),
        }, report_exists=False)
        self.assertEqual(result, 0, output)
        self.assertIn("gate=ticket-reconciliation epic=99 verdict=pass", output)

    def test_skipped_reconciliation_reopens_epic_and_fails(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        result, output, calls = self.run_reconciliation([], {}, report_exists=False)
        self.assertEqual(result, 1, output)
        self.assertIn("missing", output)
        self.assertTrue(any(c[2] == {"state": "open"} for c in calls))
        self.assertTrue(any(c[0] == "repos/o/r/issues/99/comments" for c in calls))

    def test_superseded_failure_requires_replacement_and_preserved_failed_verifier_return(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "failed-verification")
        failed_path = self.root / ".migration/returns/T3.afs-verifier.yaml"
        failed_path.parent.mkdir(parents=True)
        failed_path.write_text(self.FAILED_RETURN, encoding="utf-8")
        failed_head = self.commit("failed verifier return")
        self.git("checkout", "-q", "--detach", base)
        replacement_path = self.root / ".migration/returns/T4.afs-verifier.yaml"
        replacement_path.parent.mkdir(parents=True, exist_ok=True)
        replacement_path.write_text(
            self.RETURN.replace("ticket: T1", "ticket: T4").replace("o/r#1", "o/r#4")
            .replace("o/r#101", "o/r#104"), encoding="utf-8")
        (self.root / "main.txt").write_text("replacement landed\n", encoding="utf-8")
        main = self.commit("replacement accepted")
        report = [
            {"number": 3, "disposition": "superseded", "replacement": 4,
             "failure": {"pull_request": 103, "return": ".migration/returns/T3.afs-verifier.yaml"}},
            {"number": 4, "disposition": "completed", "pull_requests": [104],
             "returns": [".migration/returns/T4.afs-verifier.yaml"]},
        ]
        issues = [{"number": 3, "disposition": "superseded"}, {"number": 4, "disposition": "completed"}]
        content_path = ("repos/o/r/contents/.migration/returns/T3.afs-verifier.yaml"
                        f"?ref={failed_head}")
        encoded = base64.b64encode(self.FAILED_RETURN.encode()).decode()
        result, output, _ = self.run_reconciliation(issues, {
            103: self.pull(103, head=failed_head),
            104: self.pull(104, head=main, merged=True),
        }, contents={content_path: {"encoding": "base64", "content": encoded}}, report_issues=report,
           labels=[
               {"number": 3, "title": "failed verification", "state": "closed", "state_reason": "not_planned",
                "labels": []},
               {"number": 4, "title": "replacement verification", "state": "closed",
                "state_reason": "completed", "labels": []},
           ])
        self.assertEqual(result, 0, output)
        self.assertIn("superseded", output)
        self.assertNotEqual(failed_head, main)

    def test_explicit_retained_open_work_is_not_reported_as_stale(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        issue = {"number": 5, "disposition": "retained-open", "outstanding": "Finish the data import.",
                 "blocker": "Waiting for the operator-owned production snapshot."}
        result, output, _ = self.run_reconciliation([issue], {}, labels=[
            {"number": 5, "title": "data import", "state": "open", "state_reason": None, "labels": []}
        ])
        self.assertEqual(result, 0, output)
        self.assertIn("retained-open", output)

    def test_decision_map_research_and_issues_outside_the_epic_are_excluded(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        issue = {"number": 1, "disposition": "retained-open", "outstanding": "Work remains.",
                 "blocker": "Blocked by a concrete external dependency."}
        result, output, _ = self.run_reconciliation([issue], {}, labels=[
            {"number": 1, "title": "unfinished slice task", "state": "open", "labels": []},
            {"number": 2, "title": "decision research", "state": "open",
             "labels": [{"name": "wayfinder:research"}]},
        ])
        self.assertEqual(result, 0, output)
        self.assertIn("tickets=1", output)

    def test_unavailable_api_fails_explicitly(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        with mock.patch.object(ticket_guard, "gh", side_effect=SystemExit("gh api unavailable")):
            with self.assertRaisesRegex(SystemExit, "unavailable"):
                ticket_guard.main(["--repo", "o/r", "--reconcile-epic", "99"])

    def test_shallow_history_fails_closed(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        head = self.commit("base")
        (self.root / ".git/shallow").write_text(head + "\n", encoding="utf-8")
        issue = {"number": 1, "disposition": "retained-open", "outstanding": "Work remains.",
                 "blocker": "Blocked by a concrete external dependency."}
        result, output, _ = self.run_reconciliation([issue], {}, labels=[
            {"number": 1, "title": "unfinished slice task", "state": "open", "labels": []}
        ])
        self.assertEqual(result, 1, output)
        self.assertIn("history unavailable", output)


if __name__ == "__main__":
    unittest.main()
