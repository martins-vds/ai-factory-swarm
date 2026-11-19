"""ADR-0049: the reconciliation file is generated from the check's own evidence rules, then reviewed."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import reconcile_epic as re_  # noqa: E402
import ticket_guard as tg  # noqa: E402


class ReconcileEpicTest(unittest.TestCase):
    def setUp(self):
        self.saved = (tg.gh, tg._issue_pull_references, tg.descendants)
        pulls = {11: {"merged_at": "x"}, 12: {"merged_at": None}}
        files = {11: [{"filename": ".migration/returns/LL-01.afs-migrator.yaml", "status": "added"},
                      {"filename": "src/a.py", "status": "added"}]}

        def gh(path, *a, **k):
            if "/files" in path:
                return files.get(int(path.split("/pulls/")[1].split("/")[0]), [])
            return pulls.get(int(path.rsplit("/", 1)[1]))
        tg.gh = gh
        tg._issue_pull_references = lambda repo, n: [11, 12] if n == 1 else []
        tg.descendants = lambda repo, epic, gh=None: {
            1: {"state": "closed", "state_reason": "completed"},
            2: {"state": "open"},
            3: {"state": "closed", "state_reason": "not_planned"}}

    def tearDown(self):
        tg.gh, tg._issue_pull_references, tg.descendants = self.saved

    def test_a_proven_completed_issue_needs_no_review(self):
        entry, needs = re_.disposition("o/t", 1, {"state": "closed", "state_reason": "completed"},
                                       prove=lambda *a, **k: [])
        self.assertFalse(needs)
        self.assertEqual(entry, {"number": 1, "disposition": "completed", "pull_requests": [11],
                                 "returns": [".migration/returns/LL-01.afs-migrator.yaml"]})

    def test_what_the_check_rejects_is_written_for_review_with_the_checks_reason(self):
        entry, needs = re_.disposition("o/t", 1, {"state": "closed", "state_reason": "completed"},
                                       prove=lambda *a, **k: ["no cited landed PR contains this role return"])
        self.assertTrue(needs)
        self.assertEqual(entry["needs_review"], "no cited landed PR contains this role return")

    def test_only_the_pairs_the_check_accepts_are_kept(self):
        # Synthetic epic 58: a landing PR also changed the acceptance and audit returns of other issues.
        tg.gh = (lambda old: lambda path, *a, **k: [{"filename": ".migration/returns/A.yaml"},
                                                    {"filename": ".migration/returns/B.yaml"}]
                 if "/files" in path else old(path))(tg.gh)
        entry, needs = re_.disposition("o/t", 1, {"state": "closed", "state_reason": "completed"},
                                       prove=lambda repo, n, e, **k: [] if e["returns"] == [".migration/returns/B.yaml"]
                                       else ["not this issue's"])
        self.assertFalse(needs)
        self.assertEqual(entry["returns"], [".migration/returns/B.yaml"])
        self.assertEqual(entry["pull_requests"], [11])

    def test_open_and_superseded_issues_are_never_guessed(self):
        tg_prove = re_.tg.completed_evidence_problems
        re_.tg.completed_evidence_problems = lambda *a, **k: []
        try:
            report, review = re_.build("o/t", 9)
        finally:
            re_.tg.completed_evidence_problems = tg_prove
        by = {e["number"]: e for e in report["issues"]}
        self.assertEqual(report["scope"], "slice-epic-descendants")
        self.assertEqual(by[2]["disposition"], "retained-open")
        self.assertEqual(by[2]["outstanding"], "")
        self.assertEqual(by[3]["disposition"], "superseded")
        self.assertIsNone(by[3]["replacement"])
        self.assertEqual(review, 2)


if __name__ == "__main__":
    unittest.main()
