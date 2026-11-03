"""tools/ticket_guard.py (ADR-0029): a ticket closed before its work reached the default branch is reopened."""
import pathlib
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
