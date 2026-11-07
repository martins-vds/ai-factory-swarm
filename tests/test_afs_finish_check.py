"""tools/afs-finish-check: the ADR-0034 stop hook, on a throwaway git repo."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools/afs-finish-check"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class FinishCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.origin, self.repo = base / "origin.git", base / "repo"
        git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(base, "init", "-q", "-b", "main", str(self.repo))
        r = self.repo
        mig = r / ".migration"
        (mig / "harness").mkdir(parents=True)
        shutil.copytree(ROOT / "schemas", mig / "harness" / "schemas")
        (mig / "plan").mkdir()
        (mig / "plan" / "booking.md").write_text("# booking\n")
        (mig / "plan" / "booking.tickets.yaml").write_text(yaml.safe_dump({"slice": "booking", "tickets": [
            {"id": "BK-05D", "role": "afs-specialist-migrator", "files": ["src/wizard.py", "templates/wizard/"],
             "blocked_by": []}]}))
        self.profile(enabled=True)
        (r / "README.md").write_text("x\n")
        git(r, "add", "-A")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        git(r, "remote", "add", "origin", str(self.origin))
        git(r, "push", "-q", "origin", "main")
        git(r, "fetch", "-q", "origin")
        git(r, "checkout", "-q", "-b", "copilot/bk-05d")

    def tearDown(self):
        self.tmp.cleanup()

    def profile(self, enabled, max_blocks=2):
        (self.repo / ".migration" / "profile.yaml").write_text(
            yaml.safe_dump({"self_heal": {"enabled": enabled, "max_blocks": max_blocks}}))

    def write(self, rel, text="x\n"):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_hook(self, session="s1", prompt="Role: `afs-specialist-migrator`, ticket `BK-05D`"):
        env = {**os.environ, "COPILOT_AGENT_PROMPT": prompt}
        env.pop("AFS_TICKET", None)
        r = subprocess.run([sys.executable, str(TOOL), "--hook"], cwd=self.repo, env=env, capture_output=True,
                           text=True, input=json.dumps({"sessionId": session}))
        self.assertEqual(r.returncode, 0, r.stderr)
        return (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr

    def test_missing_return_file_blocks_with_the_fix(self):
        self.write("src/wizard.py")
        out, _ = self.run_hook()
        self.assertEqual(out["decision"], "block")
        self.assertIn(".migration/returns/BK-05D.afs-specialist-migrator.yaml", out["reason"])

    def test_budget_then_self_check_failed_handoff(self):
        self.write("src/wizard.py")
        self.profile(enabled=True, max_blocks=1)
        first, _ = self.run_hook()
        self.assertEqual(first["decision"], "block")
        second, err = self.run_hook()
        self.assertIsNone(second, "the same failure twice: let it stop")
        self.assertIn("allowing the stop", err)
        handoff = (self.repo / ".migration/handoffs/BK-05D.md").read_text()
        self.assertIn("self-check failed", handoff)
        self.assertIn("### Next step for the next session", handoff)

    def test_disabled_only_reports(self):
        self.write("src/wizard.py")
        self.profile(enabled=False)
        out, err = self.run_hook()
        self.assertIsNone(out)
        self.assertIn("would have blocked", err)

    def test_scope_outside_the_plan_needs_a_handoff(self):
        self.write("src/wizard.py")
        self.write("src/settings.py")
        out, _ = self.run_hook()
        self.assertIn("`src/settings.py`", out["reason"])
        self.assertIn("Don't widen your own scope", out["reason"])

    def test_operator_scope_line_in_the_issue_allows_a_file(self):
        self.write("src/settings.py")
        prompt = "Role: `afs-specialist-migrator`, ticket `BK-05D`\nAFS-SCOPE: `src/settings.py`\n"
        out, _ = self.run_hook(prompt=prompt)
        self.assertNotIn("src/settings.py", (out or {}).get("reason", ""))

    def test_folder_scope_and_own_records_pass(self):
        self.write("templates/wizard/origin.html")
        self.write(".migration/evidence/runs/BK-05D.md", "| UTC | Gate |\n")
        self.write(".migration/returns/BK-05D.afs-specialist-migrator.yaml",
                   "role: afs-specialist-migrator\nticket: BK-05D\nissue: o/r#291\n")
        out, err = self.run_hook()
        reason = (out or {}).get("reason", "")
        self.assertNotIn("outside", reason)
        self.assertNotIn("No return file", reason)

    def test_return_reporting_a_handoff_must_commit_it(self):
        self.write("src/wizard.py")
        self.write(".migration/returns/BK-05D.afs-specialist-migrator.yaml",
                   "role: afs-specialist-migrator\nticket: BK-05D\nissue: o/r#291\nhandoff: .migration/handoffs/BK-05D.md\n")
        out, _ = self.run_hook()
        self.assertIn("reports a handoff", out["reason"])

    def test_unknown_session_is_allowed(self):
        self.write("notes.txt")
        out, err = self.run_hook(prompt="fix a typo")
        self.assertIsNone(out)
        self.assertIn("no ticket/role", err)

    def test_manual_run_exit_code(self):
        self.write("src/wizard.py")
        r = subprocess.run([sys.executable, str(TOOL), "--ticket", "BK-05D", "--role", "afs-specialist-migrator"],
                           cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("[mechanical]", r.stdout)
        self.assertIn("AFS-TOOL afs-finish-check exit=1", r.stderr)


if __name__ == "__main__":
    unittest.main()
