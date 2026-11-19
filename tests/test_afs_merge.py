"""ADR-0047: afs-merge merges agent PRs only the safe way, and refuses the ways that went wrong."""
import importlib.machinery
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("afs_merge", str(ROOT / "tools" / "afs-merge"))
_spec = importlib.util.spec_from_loader("afs_merge", _loader)
am = importlib.util.module_from_spec(_spec)
_loader.exec_module(am)

REPO = "o/t"


class FakeGitHub:
    def __init__(self, pr, open_prs=(), checks=(("Gates", "success"), (am.VERIFIED, "success")), runs=()):
        self.pr, self.open, self.checks, self.runs, self.merged = pr, list(open_prs), checks, list(runs), []

    def api(self, path, method="GET", fields=None):
        if method == "PUT":
            self.merged.append((path, fields))
            return {"merged": True}
        if path == f"repos/{REPO}":
            return {"default_branch": "main"}
        if path.startswith(f"repos/{REPO}/pulls/"):
            return self.pr
        if "/check-runs" in path:
            return {"check_runs": [{"name": n, "status": "completed" if c else "in_progress", "conclusion": c}
                                   for n, c in self.checks]}
        if "/actions/runs" in path:
            return {"workflow_runs": self.runs}
        raise AssertionError(path)

    def paged(self, path):
        return self.open


def pr(n=5, base="main", head="w", draft=False, state="open"):
    return {"number": n, "state": state, "draft": draft, "base": {"ref": base}, "head": {"ref": head, "sha": "abc"}}


class AfsMergeTest(unittest.TestCase):
    def run_merge(self, fake, kind="work"):
        am.api, am.paged = fake.api, fake.paged
        try:
            return (am.merge_work if kind == "work" else am.merge_verifier)(REPO, 5), None
        except am.Refused as e:
            return None, str(e)

    def test_a_green_work_pr_merges_through_the_merge_api(self):
        fake = FakeGitHub(pr())
        out, err = self.run_merge(fake)
        self.assertIsNone(err)
        self.assertEqual(fake.merged[0][0], f"repos/{REPO}/pulls/5/merge")
        self.assertNotIn("merge-async", fake.merged[0][0])

    def test_a_stacked_work_pr_is_refused(self):
        out, err = self.run_merge(FakeGitHub(pr(base="other")))
        self.assertIn("it is stacked", err)

    def test_a_pr_with_prs_stacked_on_it_is_refused(self):
        # Synthetic #123: the bottom of a stack merged while a PR sat on it.
        out, err = self.run_merge(FakeGitHub(pr(), open_prs=[pr(n=6, base="w", head="v")]))
        self.assertIn("#6", err)

    def test_drafts_red_or_running_checks_and_waiting_runs_are_refused(self):
        self.assertIn("draft", self.run_merge(FakeGitHub(pr(draft=True)))[1])
        self.assertIn("not green", self.run_merge(FakeGitHub(pr(), checks=(("Gates", "failure"),)))[1])
        self.assertIn("still running", self.run_merge(FakeGitHub(pr(), checks=(("Gates", None),)))[1])
        runs = [{"id": 1, "name": "AFS harness check", "conclusion": "action_required", "status": "completed"}]
        self.assertIn("approval", self.run_merge(FakeGitHub(pr(), runs=runs))[1])
        later = runs + [{"id": 2, "name": "AFS harness check", "conclusion": "success", "status": "completed"}]
        self.assertIsNone(self.run_merge(FakeGitHub(pr(), runs=later))[1])

    def test_the_verified_merge_check_must_be_green(self):
        err = self.run_merge(FakeGitHub(pr(), checks=(("Gates", "success"), (am.VERIFIED, "skipped"))))[1]
        self.assertIn("verified", err)

    def test_a_verifier_pr_must_target_an_open_work_branch(self):
        self.assertIn("targets `main`", self.run_merge(FakeGitHub(pr()), "verifier")[1])
        self.assertIn("isn't the head", self.run_merge(FakeGitHub(pr(base="w2")), "verifier")[1])


if __name__ == "__main__":
    unittest.main()
