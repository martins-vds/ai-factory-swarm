import contextlib
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import check_verified_merge as cvm  # noqa: E402

VERIFIER = """role: afs-verifier
ticket: {ticket}
issue: o/r#2
pr: o/r#12
verdict: {verdict}
gates: null
evidence_logs: []
findings: []
tests_added: []
ledger_issues: []
quirk_tickets: []
"""


class VerifiedMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        (self.root / ".migration/returns").mkdir(parents=True)
        (self.root / "README").write_text("base\n")
        self.commit("base")
        self.git("branch", "base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def migrate(self, ticket="LL-01", role="afs-migrator", note="first"):
        (self.root / f"src_{ticket}.py").write_text(f"# {note}\n")
        (self.root / f".migration/returns/{ticket}.{role}.yaml").write_text(f"role: {role}\nnote: {note}\n")
        self.commit(f"migrate {ticket} ({note})")

    def verify(self, ticket="LL-01", verdict="pass", as_ticket=None):
        (self.root / f".migration/returns/{ticket}.afs-verifier.yaml").write_text(
            VERIFIER.format(ticket=as_ticket or ticket, verdict=verdict))
        self.commit(f"verify {ticket}")

    def run_check(self, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cvm.main(["--base", "base", *extra])
        return result, output.getvalue()

    def test_migrator_work_verified_after_its_latest_change_passes(self):
        self.migrate()
        self.verify()
        result, output = self.run_check()
        self.assertEqual(result, 0, output)
        self.assertIn("LL-01: verified by its passing Verifier return", output)

    def test_specialist_migrator_work_is_covered_too(self):
        self.migrate(role="afs-specialist-migrator")
        result, output = self.run_check()
        self.assertEqual(result, 1, output)
        self.assertIn("no Verifier return", output)

    def test_unverified_migrator_work_cannot_merge(self):
        self.migrate()
        result, output = self.run_check()
        self.assertEqual(result, 1, output)
        self.assertIn("LL-01: no Verifier return .migration/returns/LL-01.afs-verifier.yaml", output)

    def test_a_verifier_that_did_not_pass_blocks(self):
        self.migrate()
        self.verify(verdict="changes-required")
        result, output = self.run_check()
        self.assertEqual(result, 1, output)
        self.assertIn("Verifier hasn't passed it", output)

    def test_a_verifier_return_for_another_ticket_blocks(self):
        self.migrate()
        self.verify(as_ticket="LL-09")
        result, output = self.run_check()
        self.assertEqual(result, 1, output)
        self.assertIn("LL-01.afs-verifier.yaml is not a valid return", output)

    def test_migrator_rework_after_verification_needs_a_fresh_verification(self):
        self.migrate()
        self.verify()
        self.migrate(note="rework")
        result, output = self.run_check()
        self.assertEqual(result, 1, output)
        self.assertIn("re-verify the current work", output)

    def test_one_commit_writing_both_returns_is_not_verification(self):
        (self.root / ".migration/returns/LL-01.afs-migrator.yaml").write_text("role: afs-migrator\n")
        (self.root / ".migration/returns/LL-01.afs-verifier.yaml").write_text(
            VERIFIER.format(ticket="LL-01", verdict="pass"))
        self.commit("migrator writes its own verification")
        result, output = self.run_check()
        self.assertEqual(result, 1, output)
        self.assertIn("re-verify the current work", output)

    def test_an_earlier_verification_on_the_base_does_not_cover_new_work(self):
        self.migrate()
        self.verify()
        self.git("branch", "-f", "base")
        self.migrate(note="new fix")
        result, output = self.run_check()
        self.assertEqual(result, 1, output)
        self.assertIn("re-verify the current work", output)

    def test_prs_without_migrator_returns_pass(self):
        (self.root / "docs.md").write_text("notes\n")
        self.commit("docs")
        result, output = self.run_check()
        self.assertEqual(result, 0, output)
        self.assertIn("tickets=0", output)

    def test_prs_into_another_branch_are_out_of_scope(self):
        self.migrate()
        result, output = self.run_check("--pr-base", "copilot/ll-01", "--default-branch", "main")
        self.assertEqual(result, 0, output)
        self.assertIn("out of scope", output)


if __name__ == "__main__":
    unittest.main()
