"""Stack checks use real git ancestry, not the PR checkout's synthetic merge."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_stack_base  # noqa: E402


class StackBaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.git("init", "-q", "--initial-branch=trunk")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.first = self.commit("initial")
        self.git("update-ref", "refs/remotes/origin/trunk", self.first)
        self.git("checkout", "-q", "-b", "work/topic")
        self.base = self.commit("work")
        self.git("update-ref", "refs/remotes/origin/work/topic", self.base)
        self.git("checkout", "-q", "-b", "verify/topic")
        self.head = self.commit("verify")
        self.event = {"repository": {"default_branch": "trunk"},
                      "pull_request": {"base": {"ref": "work/topic"}, "head": {"sha": self.head}}}

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def advance_default(self):
        self.git("checkout", "-q", "trunk")
        new = self.commit("default changed or reverted")
        self.git("update-ref", "refs/remotes/origin/trunk", new)
        return new

    def test_current_stack_passes(self):
        ok, message = check_stack_base.check(self.event, self.root)
        self.assertTrue(ok, message)
        self.assertIn("trunk -> work/topic -> PR head", message)

    def test_stale_base_fails_with_fix(self):
        self.advance_default()
        ok, message = check_stack_base.check(self.event, self.root)
        self.assertFalse(ok)
        self.assertIn("Merge origin/trunk into work/topic", message)
        self.assertIn("push", message)

    def test_updating_base_does_not_make_old_head_current(self):
        new = self.advance_default()
        self.git("checkout", "-q", "work/topic")
        self.git("merge", "-q", "--no-ff", new, "-m", "update base")
        self.git("update-ref", "refs/remotes/origin/work/topic", self.git("rev-parse", "HEAD"))
        # checkout's synthetic merge includes the new base, but the event still names the stale head.
        self.git("merge", "-q", "--no-ff", self.head, "-m", "synthetic merge")
        ok, message = check_stack_base.check(self.event, self.root)
        self.assertFalse(ok)
        self.assertIn("Merge origin/work/topic", message)
        self.git("checkout", "-q", "verify/topic")
        self.git("merge", "-q", "--no-ff", "work/topic", "-m", "update head")
        self.event["pull_request"]["head"]["sha"] = self.git("rev-parse", "HEAD")
        self.assertTrue(check_stack_base.check(self.event, self.root)[0])

    def test_default_branch_and_non_pr_events_do_not_need_stack_refs(self):
        self.event["pull_request"]["base"]["ref"] = "trunk"
        del self.event["pull_request"]["head"]
        self.assertTrue(check_stack_base.check(self.event, self.root)[0])
        self.assertTrue(check_stack_base.check({}, self.root)[0])

    def test_missing_ref_is_an_error_not_an_outdated_result(self):
        self.git("update-ref", "-d", "refs/remotes/origin/work/topic")
        with self.assertRaises(subprocess.CalledProcessError):
            check_stack_base.check(self.event, self.root)

    def test_invalid_head_is_rejected(self):
        self.event["pull_request"]["head"]["sha"] = "--help"
        with self.assertRaisesRegex(ValueError, "head SHA"):
            check_stack_base.check(self.event, self.root)

    def run_main(self, event):
        path = self.root / "event.json"
        path.write_text(json.dumps(event))
        result = subprocess.run([sys.executable, str(ROOT / "tools/check_stack_base.py"),
                                 "--event", str(path)], cwd=self.root, capture_output=True, text=True)
        self.assertIn(f"AFS-TOOL check_stack_base.py exit={result.returncode}", result.stderr)
        return result.returncode, result.stdout

    def test_entry_point_exit_codes_and_diagnostics(self):
        code, output = self.run_main(self.event)
        self.assertEqual(code, 0, output)
        self.advance_default()
        code, output = self.run_main(self.event)
        self.assertEqual(code, 1, output)
        self.assertIn("::error title=Stale stack base::", output)
        code, output = self.run_main({"pull_request": self.event["pull_request"]})
        self.assertEqual(code, 2, output)
        self.assertIn("::error title=Cannot check stack base::", output)

    def test_missing_history_and_malformed_payload_fail_explicitly(self):
        self.git("update-ref", "-d", "refs/remotes/origin/work/topic")
        code, output = self.run_main(self.event)
        self.assertEqual(code, 2, output)
        self.assertIn("full history", output)
        for event in ([], {"pull_request": "invalid"}, {"pull_request": {"base": None}}):
            with self.subTest(event=event):
                code, output = self.run_main(event)
                self.assertEqual(code, 2, output)
                self.assertIn("::error title=Cannot check stack base::", output)


if __name__ == "__main__":
    unittest.main()
