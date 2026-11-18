"""tools/check_signoff.py (ADR-0031): a human sign-off is an approver's review on the exact head commit."""
import contextlib
import datetime
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_signoff  # noqa: E402

RET = ".migration/returns/TC-16.afs-slice-coordinator.yaml"


def coordinator(check):
    return f"role: afs-slice-coordinator\nticket: TC-16\nissue: o/r#9\nhuman_check: {check}\n"


def review(login, state, commit):
    return {"user": {"login": login}, "state": state, "commit_id": commit}


class SignoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.write(".migration/profile.yaml", "signoff:\n  approvers: [alice]\n")
        self.write(RET, coordinator("requested"))
        self.commit("base")
        self.base = self.rev()
        self.calls = []

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def git(self, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True,
                              capture_output=True, text=True).stdout

    def write(self, path, text):
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def rev(self):
        return self.git("rev-parse", "HEAD").strip()

    def run_check(self, args, reviews, head=None, prs=(42,)):
        head = head or self.rev()

        def gh(path):
            self.calls.append(path)
            if path.endswith("/reviews?per_page=100"):
                return reviews
            if "/commits/" in path and path.endswith("/pulls"):
                return [{"number": n} for n in prs]
            if "/pulls/" in path:
                return {"head": {"sha": head}}
            raise AssertionError(path)
        orig, check_signoff.gh = check_signoff.gh, gh
        try:
            return check_signoff.main(["--repo", "o/r", *args])
        finally:
            check_signoff.gh = orig

    def pr_args(self):
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        return ["--pr", "42", "--base", "origin/main"]

    def sign(self):
        self.write(RET, coordinator("passed"))
        self.commit("sign off")

    def test_no_new_signoff_passes_without_asking_github(self):
        self.write("src/app.py", "x = 1\n")
        self.commit("work")
        self.assertEqual(self.run_check(self.pr_args(), []), 0)
        self.assertEqual(self.calls, [])

    def test_passed_without_a_review_fails(self):
        self.sign()
        self.assertEqual(self.run_check(self.pr_args(), []), 1)

    def test_approver_review_on_the_head_signs_off(self):
        self.sign()
        self.assertEqual(self.run_check(self.pr_args(), [review("alice", "APPROVED", self.rev())]), 0)

    def test_a_review_by_someone_not_listed_does_not(self):
        self.sign()
        self.assertEqual(self.run_check(self.pr_args(), [review("mallory", "APPROVED", self.rev())]), 1)

    def test_an_approval_of_an_older_commit_is_stale(self):
        self.sign()
        old = self.rev()
        self.write("notes.md", "late push\n")
        self.commit("after approval")
        self.assertEqual(self.run_check(self.pr_args(), [review("alice", "APPROVED", old)]), 1)

    def test_a_later_changes_requested_or_dismissal_withdraws_it(self):
        self.sign()
        head = self.rev()
        for later in ("CHANGES_REQUESTED", "DISMISSED"):
            reviews = [review("alice", "APPROVED", head), review("alice", later, head)]
            self.assertEqual(self.run_check(self.pr_args(), reviews), 1, later)
        comment_after = [review("alice", "APPROVED", head), review("alice", "COMMENTED", head)]
        self.assertEqual(self.run_check(self.pr_args(), comment_after), 0, "a comment doesn't withdraw it")

    def test_no_approvers_configured_fails_and_names_the_setting(self):
        self.write(".migration/profile.yaml", "graph: {}\n")
        self.sign()
        self.assertEqual(self.run_check(self.pr_args(), [review("alice", "APPROVED", self.rev())]), 1)

    def test_a_push_to_main_finds_the_pr_that_set_it(self):
        self.sign()
        signed = self.rev()
        self.assertEqual(self.run_check(["--range", f"{self.base}..{signed}"],
                                        [review("alice", "APPROVED", signed)], head=signed), 0)
        self.assertTrue(any(c == f"repos/o/r/commits/{signed}/pulls" for c in self.calls))

    def test_a_push_with_no_pr_fails(self):
        self.sign()
        self.assertEqual(self.run_check(["--range", f"{self.base}..{self.rev()}"], [], prs=()), 1)

    def test_other_roles_saying_passed_are_not_signoffs(self):
        self.write(".migration/returns/X.afs-verifier.yaml", "role: afs-verifier\nhuman_check: passed\n")
        self.commit("not a coordinator")
        self.assertEqual(self.run_check(self.pr_args(), []), 0)



    def defer(self, issue="o/r#418", due=None):
        due = due or (datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=7)).isoformat()
        text = coordinator("deferred").rstrip("\n") + f"\nhuman_check_issue: {issue}\nhuman_check_due: '{due}'\n"
        self.write(RET, text)
        self.commit("defer")

    def test_a_deferral_needs_the_approvers_review_too(self):
        self.defer()
        self.assertEqual(self.run_check(self.pr_args(), []), 1)
        self.assertEqual(self.run_check(self.pr_args(), [review("alice", "APPROVED", self.rev())]), 0)

    def test_a_deferral_needs_its_issue_and_a_near_due_date(self):
        self.defer(issue="", due=(datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=45)).isoformat())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.run_check(self.pr_args(), [review("alice", "APPROVED", self.rev())])
        self.assertEqual(code, 1)
        self.assertIn("needs human_check_issue", out.getvalue())
        self.assertIn("more than 30 days away", out.getvalue())

    def test_overdue_deferrals_warn_then_fail(self):
        self.defer(due=(datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=3)).isoformat())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(check_signoff.main(["--repo", "o/r", "--deferrals"]), 0)
        self.assertIn("3 day(s) overdue", out.getvalue())
        self.defer(due=(datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=31)).isoformat())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_signoff.main(["--repo", "o/r", "--deferrals"]), 1)

if __name__ == "__main__":
    unittest.main()
