"""tools/check_slice_returns.py (ADR-0024): a slice epic closes only when every ticket left its return file."""
import os
import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ticket_guard  # noqa: E402
import check_slice_returns as csr  # noqa: E402

REPO = "o/r"
RETURN = """role: afs-verifier
ticket: T1
issue: o/r#1
pr: o/r#10
verdict: changes-required
gates: null
evidence_logs: []
findings: []
tests_added: []
ledger_issues: []
quirk_tickets: []
"""


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
            (pathlib.Path(d) / "T1.afs-verifier.yaml").write_text(RETURN.replace("o/r#1\n", "o/r#22\n"))
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
                self.assertEqual(csr.utc(csr.rule_since()), csr.utc("2026-11-03T04:00:00Z"), "first install, not the upgrade")
                head = git("rev-parse", "HEAD").stdout.decode().strip()
                (pathlib.Path(d) / ".git/shallow").write_text(head + "\n")
                self.assertIsNone(csr.rule_since(), "a shallow boundary must not create a false pre-rule exemption")
            finally:
                os.chdir(cwd)


class HistoricalAttributionTest(unittest.TestCase):
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
        self.path = self.root / ".migration/returns/T1.afs-verifier.yaml"
        self.path.parent.mkdir(parents=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, text, message="return"):
        self.path.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def supersede(self, previous=RETURN):
        old = self.commit(previous, "original run")
        self.commit(RETURN.replace("o/r#1\n", "o/r#2\n").replace("changes-required", "pass"), "later run")
        return old

    def run_guard(self, subs=None, *, reopen=True, epic=True):
        calls = []

        def gh(endpoint, *args, **kwargs):
            calls.append((endpoint, args, kwargs))
            if "/sub_issues?" in endpoint:
                return subs if subs is not None else [sub(1)]
            return {"state": "closed", "labels": [{"name": "afs:slice"}] if epic else []}

        def parent_gh(endpoint, *args, **kwargs):
            if endpoint.startswith("repos/o/r/issues/"):
                return {"number": int(endpoint.rsplit("/", 1)[1])}
            return {}

        output = io.StringIO()
        with mock.patch.object(csr.fog_rewalk, "gh", side_effect=gh), \
                mock.patch.object(ticket_guard, "gh", side_effect=parent_gh), \
                mock.patch.object(csr, "rule_since", return_value="2026-11-03T00:00:00Z"), \
                contextlib.redirect_stdout(output):
            result = csr.main(["--repo", REPO, "--epic", "99"] + (["--reopen"] if reopen else []))
        return result, output.getvalue(), calls

    def assert_blocked(self):
        result, output, calls = self.run_guard()
        self.assertEqual(result, 1, output)
        self.assertIn("verdict=fail", output)
        self.assertIn("reopened #99", output)
        self.assertTrue(any(c[2].get("data") == {"state": "open"} for c in calls))
        self.assertNotIn("superseded attribution:", output)
        return output

    def test_valid_supersession_is_attribution_not_a_passing_verdict(self):
        old = self.supersede()
        current = self.path.read_bytes()
        result, output, calls = self.run_guard()
        self.assertEqual(result, 0, output)
        self.assertIn(f".migration/returns/T1.afs-verifier.yaml@{old}", output)
        self.assertIn("issue: o/r#1", output)
        self.assertIn("Historical attribution is not a passing verdict", output)
        self.assertIn("verdict=pass tickets=1 failures=0", output)
        self.assertFalse(any(c[1] for c in calls), "passing guard must not mutate issues")
        self.assertEqual(self.path.read_bytes(), current)

    def test_genuinely_missing_return_still_reopens(self):
        self.supersede(RETURN.replace("o/r#1\n", "o/r#3\n"))
        self.assertIn("no `.migration/returns/*.yaml`", self.assert_blocked())

    def test_invalid_historical_evidence_cannot_attribute(self):
        cases = {
            "wrong repository": RETURN.replace("o/r#1", "other/repo#1"),
            "wrong ticket": RETURN.replace("ticket: T1", "ticket: T9"),
            "wrong role": RETURN.replace("afs-verifier", "afs-migrator"),
            "malformed YAML": "issue: [\n",
            "not a mapping": "- a list\n",
            "missing contract fields": "role: afs-verifier\nticket: T1\nissue: o/r#1\n",
            "invalid verdict": RETURN.replace("changes-required", "passed"),
            "noncanonical issue": RETURN.replace("o/r#1\n", "o/r#01\n"),
            "null issue": RETURN.replace("issue: o/r#1", "issue: null"),
        }
        for label, previous in cases.items():
            with self.subTest(label=label):
                self.supersede(previous)
                self.assert_blocked()

    def test_wrong_role_with_its_own_valid_contract_cannot_attribute(self):
        previous = yaml.safe_load(RETURN)
        previous.update(role="afs-auditor", scope=None, report=None, capabilities_checked=0,
                        gaps=[], graph_inconsistencies=[], verdict="complete")
        self.supersede(yaml.safe_dump(previous))
        self.assert_blocked()

    def test_misnamed_current_and_historical_file_cannot_attribute(self):
        self.path = self.path.with_name("wrong.afs-verifier.yaml")
        self.supersede()
        self.assert_blocked()

    def test_wrong_repository_current_return_cannot_unlock_history(self):
        self.supersede()
        self.commit(self.path.read_text().replace("o/r#2", "other/repo#2"))
        self.assert_blocked()

    def test_deleted_or_invalid_current_return_cannot_unlock_history(self):
        for current in (None, "issue: [\n", RETURN.replace("o/r#1\n", "o/r#2\n").replace("changes-required", "bogus")):
            with self.subTest(current=current):
                self.supersede()
                if current is None:
                    self.path.unlink()
                else:
                    self.path.write_text(current)
                self.git("add", "-A")
                self.git("commit", "-qm", "remove or invalidate current return")
                self.assert_blocked()

    def test_uncommitted_current_return_cannot_unlock_history(self):
        self.commit(RETURN)
        self.path.write_text(RETURN.replace("o/r#1\n", "o/r#2\n"))
        self.assert_blocked()

    def test_other_refs_and_unreachable_objects_cannot_attribute(self):
        self.commit(RETURN.replace("o/r#1\n", "o/r#3\n"))
        base = self.git("rev-parse", "HEAD")
        old = self.commit(RETURN)
        self.git("update-ref", "refs/heads/unmerged", old)
        self.git("reset", "--hard", base)
        self.commit(RETURN.replace("o/r#1\n", "o/r#2\n"))
        self.assert_blocked()
        self.git("update-ref", "-d", "refs/heads/unmerged")
        self.assert_blocked()  # the old commit still exists in the reflog/object database

    def test_merged_side_branch_history_is_reachable(self):
        self.commit(RETURN.replace("o/r#1\n", "o/r#3\n"))
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "worker")
        old = self.supersede()
        self.git("checkout", "--detach", base)
        self.git("merge", "--no-ff", "worker", "-m", "approved merge")
        result, output, _ = self.run_guard()
        self.assertEqual(result, 0, output)
        self.assertIn(old, output)

    def test_return_committed_only_in_merge_resolution_is_reachable(self):
        base = self.commit(RETURN.replace("o/r#1\n", "o/r#3\n"))
        self.git("checkout", "-qb", "worker")
        (self.root / "worker.txt").write_text("worker work\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "worker")
        self.git("checkout", "--detach", base)
        self.git("merge", "--no-ff", "--no-commit", "worker")
        old = self.commit(RETURN, "return recorded during merge")
        self.assertEqual(len(self.git("rev-list", "--parents", "-n1", old).split()), 3)
        self.commit(RETURN.replace("o/r#1\n", "o/r#2\n"))
        result, output, _ = self.run_guard()
        self.assertEqual(result, 0, output)
        self.assertIn(old, output)

    def test_replacement_ref_cannot_fabricate_ancestry(self):
        ancestor = self.commit(RETURN.replace("o/r#1\n", "o/r#3\n"))
        tip = self.commit(RETURN.replace("o/r#1\n", "o/r#2\n"))
        self.git("checkout", "--orphan", "unapproved")
        forged = self.commit(RETURN, "unrelated return")
        self.git("checkout", "--detach", tip)
        self.git("replace", ancestor, forged)
        self.assertIn("issue: o/r#3", self.git("--no-replace-objects", "show",
                                            f"{ancestor}:.migration/returns/T1.afs-verifier.yaml"))
        self.assert_blocked()

    def test_shallow_history_fails_explicitly_even_if_a_match_is_visible(self):
        old = self.supersede()
        (self.root / ".git/shallow").write_text(old + "\n")
        self.assertIn("history unavailable", self.assert_blocked())

    def test_missing_git_history_fails_explicitly(self):
        self.supersede()
        self.git("update-ref", "-d", "HEAD")
        self.assertIn("history unavailable", self.assert_blocked())

    def test_missing_historical_blob_fails_explicitly(self):
        old = self.supersede()
        blob = self.git("rev-parse", f"{old}:.migration/returns/T1.afs-verifier.yaml")
        (self.root / ".git/objects" / blob[:2] / blob[2:]).unlink()
        self.assertIn("history unavailable", self.assert_blocked())

    def test_untracked_return_is_not_history_or_a_blocker_for_valid_proof(self):
        old = self.supersede()
        (self.path.parent / "A1.afs-verifier.yaml").write_text(
            RETURN.replace("ticket: T1", "ticket: A1").replace("o/r#1\n", "o/r#3\n"))
        result, output, _ = self.run_guard()
        self.assertEqual(result, 0, output)
        self.assertIn(old, output)

    def test_parent_ticket_return_requires_the_exact_landed_child_pr(self):
        returned = RETURN.replace("changes-required", "pass").replace("pr: o/r#10", "pr: o/r#12")
        landed = self.commit(returned, "parent-owned child return")
        endpoints = {
            "repos/o/r/issues/99": {"number": 99, "state": "closed", "labels": [{"name": "afs:slice"}]},
            "repos/o/r/issues/99/sub_issues?per_page=100&page=1": [sub(2)],
            "repos/o/r/issues/2/sub_issues?per_page=100&page=1": [],
        }

        def gh(endpoint, *args, **kwargs):
            return endpoints.get(endpoint, {})

        def parent_gh(endpoint, *args, **kwargs):
            if endpoint == "repos/o/r/issues/2":
                return {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}
            if endpoint == "repos/o/r/pulls/12":
                return {"number": 12, "state": "closed", "merged_at": "2026-11-05T00:00:00Z",
                        "merge_commit_sha": landed, "head": {"sha": landed}, "body": "Fixes #2"}
            return {}

        output = io.StringIO()
        with mock.patch.object(csr.fog_rewalk, "gh", side_effect=gh), \
                mock.patch.object(ticket_guard, "gh", side_effect=parent_gh), \
                mock.patch.object(csr, "rule_since", return_value="2026-11-03T00:00:00Z"), \
                contextlib.redirect_stdout(output):
            result = csr.main(["--repo", REPO, "--epic", "99"])
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("verdict=pass tickets=1 failures=0", output.getvalue())

    def test_parent_ticket_return_rejects_an_unrelated_carrier_pr(self):
        returned = RETURN.replace("changes-required", "pass").replace("pr: o/r#10", "pr: o/r#12")
        landed = self.commit(returned, "unrelated carrier return")

        def gh(endpoint, *args, **kwargs):
            if endpoint == "repos/o/r/issues/99":
                return {"number": 99, "state": "closed", "labels": [{"name": "afs:slice"}]}
            if endpoint == "repos/o/r/issues/99/sub_issues?per_page=100&page=1":
                return [sub(2)]
            if endpoint == "repos/o/r/issues/2/sub_issues?per_page=100&page=1":
                return []
            return {}

        def parent_gh(endpoint, *args, **kwargs):
            if endpoint == "repos/o/r/issues/2":
                return {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}
            if endpoint == "repos/o/r/pulls/12":
                return {"number": 12, "state": "closed", "merged_at": "2026-11-05T00:00:00Z",
                        "merge_commit_sha": landed, "head": {"sha": landed}, "body": "Updates #2"}
            return {}

        output = io.StringIO()
        with mock.patch.object(csr.fog_rewalk, "gh", side_effect=gh), \
                mock.patch.object(ticket_guard, "gh", side_effect=parent_gh), \
                mock.patch.object(csr, "rule_since", return_value="2026-11-03T00:00:00Z"), \
                contextlib.redirect_stdout(output):
            result = csr.main(["--repo", REPO, "--epic", "99"])
        self.assertEqual(result, 1, output.getvalue())
        self.assertIn("no `.migration/returns/*.yaml`", output.getvalue())
        self.assertIn("does not close child issue #2", output.getvalue())

    def test_parent_ticket_continuation_can_use_same_path_history_after_current_pass(self):
        failed = RETURN.replace("pr: o/r#10", "pr: o/r#12")
        failed_head = self.commit(failed, "failed parent-owned child return")
        passed = RETURN.replace("changes-required", "pass").replace("pr: o/r#10", "pr: o/r#13")
        current_head = self.commit(passed, "corrected parent-owned child return")

        def gh(endpoint, *args, **kwargs):
            if endpoint == "repos/o/r/issues/99":
                return {"number": 99, "state": "closed", "labels": [{"name": "afs:slice"}]}
            if endpoint == "repos/o/r/issues/99/sub_issues?per_page=100&page=1":
                return [sub(2)]
            if endpoint == "repos/o/r/issues/2/sub_issues?per_page=100&page=1":
                return []
            return {}

        def parent_gh(endpoint, *args, **kwargs):
            if endpoint == "repos/o/r/issues/2":
                return {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}
            if endpoint == "repos/o/r/pulls/12":
                return {"number": 12, "state": "closed", "merged_at": None,
                        "merge_commit_sha": None, "head": {"sha": failed_head}, "body": "Fixes #2"}
            if endpoint == "repos/o/r/pulls/13":
                return {"number": 13, "state": "closed", "merged_at": "2026-11-05T00:00:00Z",
                        "merge_commit_sha": current_head, "head": {"sha": current_head}, "body": "Fixes #1"}
            return {}

        output = io.StringIO()
        with mock.patch.object(csr.fog_rewalk, "gh", side_effect=gh), \
                mock.patch.object(ticket_guard, "gh", side_effect=parent_gh), \
                mock.patch.object(csr, "rule_since", return_value="2026-11-03T00:00:00Z"), \
                contextlib.redirect_stdout(output):
            result = csr.main(["--repo", REPO, "--epic", "99"])
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("parent-ticket continuation", output.getvalue())

    def test_generic_history_cannot_bypass_parent_child_pr_proof(self):
        child_return = RETURN.replace("o/r#1\n", "o/r#2\n").replace("pr: o/r#10", "pr: o/r#12")
        self.commit(child_return, "historical child return")
        current_return = RETURN.replace("changes-required", "pass").replace("pr: o/r#10", "pr: o/r#13")
        current_head = self.commit(current_return, "parent-owned return")

        def gh(endpoint, *args, **kwargs):
            if endpoint == "repos/o/r/issues/99":
                return {"number": 99, "state": "closed", "labels": [{"name": "afs:slice"}]}
            if endpoint == "repos/o/r/issues/99/sub_issues?per_page=100&page=1":
                return [sub(2)]
            if endpoint == "repos/o/r/issues/2/sub_issues?per_page=100&page=1":
                return []
            return {}

        def parent_gh(endpoint, *args, **kwargs):
            if endpoint == "repos/o/r/issues/2":
                return {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}
            if endpoint == "repos/o/r/pulls/13":
                return {"number": 13, "state": "closed", "merged_at": "2026-11-05T00:00:00Z",
                        "merge_commit_sha": current_head, "head": {"sha": current_head}, "body": "Fixes #1"}
            return {}

        output = io.StringIO()
        with mock.patch.object(csr.fog_rewalk, "gh", side_effect=gh), \
                mock.patch.object(ticket_guard, "gh", side_effect=parent_gh), \
                mock.patch.object(csr, "rule_since", return_value="2026-11-03T00:00:00Z"), \
                contextlib.redirect_stdout(output):
            result = csr.main(["--repo", REPO, "--epic", "99"])
        self.assertEqual(result, 1, output.getvalue())
        self.assertIn("no `.migration/returns/*.yaml`", output.getvalue())
        self.assertIn("does not close child issue #2", output.getvalue())

    def test_parent_ticket_continuation_rejects_a_failed_current_role_outcome(self):
        self.commit(RETURN, "parent-owned failed verifier return")
        current = csr.current_returns()
        with mock.patch.object(ticket_guard, "_parent_issue_number", return_value=1):
            attributed, diagnostics = csr.superseded_attribution({"o/r#2"}, current, REPO)
        self.assertEqual(attributed, set())
        self.assertTrue(any("current role outcome does not pass" in item for item in diagnostics))

    def test_malformed_intermediate_revision_does_not_hide_valid_ancestry(self):
        old = self.commit(RETURN)
        self.commit("issue: [\n")
        self.commit(RETURN.replace("o/r#1\n", "o/r#2\n"))
        result, output, _ = self.run_guard()
        self.assertEqual(result, 0, output)
        self.assertIn(old, output)

    def test_invalid_current_direct_attribution_is_not_a_return(self):
        for current in (RETURN.replace("changes-required", "bogus"),
                        "ticket: T1\nissue: o/r#1\n", "issue: [\n"):
            with self.subTest(current=current):
                self.commit(current)
                self.assert_blocked()

    def test_original_closure_behavior(self):
        self.commit(RETURN)
        result, output, _ = self.run_guard()
        self.assertEqual(result, 0, output)
        self.assertNotIn("superseded attribution", output)
        self.assertEqual(self.run_guard([sub(1, state="open")])[0], 1)
        self.assertEqual(self.run_guard([sub(9, reason="not_planned")])[0], 0)
        self.assertEqual(self.run_guard([sub(9, closed_at="2026-11-01T00:00:00Z")])[0], 0)
        result, output, calls = self.run_guard([sub(9)], reopen=False)
        self.assertEqual(result, 1, output)
        self.assertFalse(any(c[1] for c in calls))
        self.assertEqual(self.run_guard(epic=False)[0], 0)


if __name__ == "__main__":
    unittest.main()
