"""ADR-0038: stacked PRs are refreshed bottom-up when the default branch moves; agent sessions in
progress, conflicts and forks are skipped and reported, never pushed over."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "stack_refresh.py"
REPO = "o/target"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def commit(cwd, path, text, msg):
    (pathlib.Path(cwd) / path).write_text(text)
    sh(cwd, "git", "add", path)
    sh(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def pr(n, head, base, title="Work", repo=REPO):
    return {"number": n, "title": title, "head": {"ref": head, "repo": {"full_name": repo}}, "base": {"ref": base}}


class StackRefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.origin, self.work = t / "origin.git", t / "work"
        sh(t, "git", "init", "-q", "--bare", "-b", "main", str(self.origin))
        sh(t, "git", "clone", "-q", str(self.origin), str(self.work))
        w = self.work
        sh(w, "git", "checkout", "-q", "-b", "main")
        commit(w, "a.txt", "a\n", "base")
        sh(w, "git", "push", "-q", "origin", "main")
        # stack: main <- s1 (#1) <- s2 (#2)
        sh(w, "git", "checkout", "-q", "-b", "s1")
        commit(w, "s1.txt", "1\n", "s1")
        sh(w, "git", "push", "-q", "origin", "s1")
        sh(w, "git", "checkout", "-q", "-b", "s2")
        commit(w, "s2.txt", "2\n", "s2")
        sh(w, "git", "push", "-q", "origin", "s2")
        # main moves
        sh(w, "git", "checkout", "-q", "main")
        commit(w, "m.txt", "m\n", "main moves")
        sh(w, "git", "push", "-q", "origin", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, prs, *extra):
        f = pathlib.Path(self.tmp.name) / "prs.json"
        f.write_text(json.dumps(prs))
        return subprocess.run([sys.executable, str(TOOL), "--repo", REPO, "--prs", str(f), "--default", "main", *extra],
                              cwd=self.work, capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "tools")})

    def contains(self, ancestor, branch):
        sh(self.work, "git", "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
        return subprocess.run(["git", "merge-base", "--is-ancestor", f"origin/{ancestor}", f"origin/{branch}"],
                              cwd=self.work).returncode == 0

    def test_a_stale_stack_is_refreshed_bottom_up(self):
        self.assertFalse(self.contains("main", "s2"))
        r = self.run_tool([pr(2, "s2", "s1"), pr(1, "s1", "main")])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.contains("main", "s1"))
        self.assertTrue(self.contains("s1", "s2"))
        self.assertTrue(self.contains("main", "s2"))
        self.assertLess(r.stdout.index("#1 "), r.stdout.index("#2 "), "parents first")
        self.assertIn("AFS-RESULT gate=stack-refresh", r.stdout)

    def test_a_current_stack_is_left_alone(self):
        self.run_tool([pr(2, "s2", "s1"), pr(1, "s1", "main")])
        before = sh(self.work, "git", "rev-parse", "origin/s2")
        r = self.run_tool([pr(2, "s2", "s1"), pr(1, "s1", "main")])
        self.assertEqual(r.returncode, 0)
        self.assertIn("current", r.stdout)
        sh(self.work, "git", "fetch", "-q", "origin")
        self.assertEqual(sh(self.work, "git", "rev-parse", "origin/s2"), before, "no empty merge commits")

    def test_an_agent_session_in_progress_is_not_pushed_over(self):
        r = self.run_tool([pr(2, "s2", "s1"), pr(1, "s1", "main", title="[WIP] still working")])
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.contains("main", "s1"))
        self.assertFalse(self.contains("main", "s2"))
        self.assertIn("#1 `s1` skipped: an agent session", r.stdout)
        self.assertIn("#2 `s2` skipped: its base `s1`", r.stdout)

    def test_a_conflict_is_reported_and_blocks_the_prs_above_it(self):
        w = self.work
        sh(w, "git", "checkout", "-q", "main")
        commit(w, "s1.txt", "main's version\n", "conflicting change")
        sh(w, "git", "push", "-q", "origin", "main")
        r = self.run_tool([pr(2, "s2", "s1"), pr(1, "s1", "main")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("#1 `s1` CONFLICT", r.stdout)
        self.assertIn("#2 `s2` skipped", r.stdout)
        self.assertFalse(self.contains("main", "s1"))
        self.assertEqual(sh(w, "git", "status", "--porcelain"), "", "the merge was aborted")

    def test_dry_run_pushes_nothing(self):
        r = self.run_tool([pr(2, "s2", "s1"), pr(1, "s1", "main")], "--dry-run")
        self.assertIn("would be refreshed", r.stdout)
        self.assertFalse(self.contains("main", "s1"))

    def test_fork_prs_and_unstacked_prs(self):
        r = self.run_tool([pr(3, "feature", "s1", repo="someone/fork"), pr(1, "s1", "main"), pr(4, "solo", "main")])
        self.assertIn("#3 skipped: its branch is in a fork", r.stdout)
        self.assertNotIn("#4", r.stdout, "a PR into main with nothing stacked on it isn't touched")
        self.assertNotIn("#1", r.stdout, "s1 has no stacked PR of ours above it")


class TemplateTest(unittest.TestCase):
    def test_the_workflow_requires_a_token_that_starts_ci(self):
        text = (ROOT / "templates/target/afs-stack-refresh.yml").read_text()
        self.assertIn("secrets.AFS_STACK_TOKEN", text)
        self.assertIn("stack_refresh.py", text)
        self.assertNotIn("github.token", text, "a GITHUB_TOKEN push starts no CI on the refreshed PRs")
        self.assertIn('"afs-stack-refresh.yml"', (ROOT / "tools/bootstrap.py").read_text())


if __name__ == "__main__":
    unittest.main()
