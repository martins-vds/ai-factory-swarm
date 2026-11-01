"""Return files: the generated schema, validate.py, and the CI check."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_return_contract as crc  # noqa: E402

RETURN = """role: afs-migrator
ticket: TC-02
issue: martins-vds/ai-factory-pilot-target#22
pr: martins-vds/ai-factory-pilot-target#38
gates: {build: 0, behavior: 0, idiom: 0, crap: 0, mutation_changed: 1.0, regression: 0}
evidence_logs: [.migration/evidence/runs/TC-02.md]
ledger_updated: [track-cargo.data-location]
quirk_tickets: []
new_tickets: []
handoff: null
"""


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class ReturnFileTest(unittest.TestCase):
    def test_schema_is_generated_from_the_agents(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools/gen_return_schema.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def validate(self, files):
        with tempfile.TemporaryDirectory() as t:
            (pathlib.Path(t) / "returns").mkdir()
            for name, text in files.items():
                (pathlib.Path(t) / "returns" / name).write_text(text)
            return subprocess.run([sys.executable, str(ROOT / "tools/validate.py"), t], capture_output=True, text=True)

    def test_validate_accepts_a_complete_return_file(self):
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_validate_rejects_missing_keys_bad_gates_and_wrong_names(self):
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN.replace("handoff: null\n", "")})
        self.assertIn("'handoff' is a required property", r.stderr)
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN.replace("build: 0", "build: [0]")})
        self.assertIn("gates/build", r.stderr)
        r = self.validate({"tc2.yaml": RETURN})
        self.assertIn("file name must be 'TC-02.afs-migrator.yaml'", r.stderr)

    def test_ci_check_wants_a_changed_return_file_for_the_closed_issue(self):
        with tempfile.TemporaryDirectory() as t:
            repo = pathlib.Path(t)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
            git(repo, "checkout", "-q", "-b", "copilot/tc-02")
            self.assertEqual(crc.changed_return_files("main", repo), [])
            self.assertFalse(crc.check("Fixes #22", [], repo)[0])
            (repo / ".migration/returns").mkdir(parents=True)
            (repo / ".migration/returns/TC-02.afs-migrator.yaml").write_text(RETURN)
            git(repo, "add", "-A")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "work")
            files = crc.changed_return_files("main", repo)
            self.assertEqual(files, [".migration/returns/TC-02.afs-migrator.yaml"])
            self.assertTrue(crc.check("Fixes #22", files, repo)[0])
            ok, msg = crc.check("Fixes #23", files, repo)
            self.assertFalse(ok)
            self.assertIn("#23", msg)

    def test_pasted_contract_is_detected(self):
        self.assertTrue(crc.pasted_contract("Done.\n\n```yaml\n" + RETURN + "```\n"))
        self.assertFalse(crc.pasted_contract("Return file: `.migration/returns/TC-02.afs-migrator.yaml`"))
        self.assertFalse(crc.pasted_contract("```yaml\nfoo: 1\n```"))

    def test_only_agent_prs_are_checked(self):
        self.assertFalse(crc.is_agent_pr({"head": {"ref": "harness/x"}, "user": {"login": "martins-vds"}}))
        self.assertTrue(crc.is_agent_pr({"head": {"ref": "copilot/tc-03"}, "user": {"login": "Copilot"}}))


if __name__ == "__main__":
    unittest.main()
