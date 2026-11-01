"""tools/check_return_contract.py against the real role agents."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_return_contract as crc  # noqa: E402

MIGRATOR = ("Done.\n\n```yaml\nticket: TC-02\npr: null\ngates: {build: pass}\nevidence_logs: []\n"
            "ledger_updated: [x]\nquirk_tickets: []\nnew_tickets: []\nhandoff: null\n```\n")


class ReturnContractTest(unittest.TestCase):
    def setUp(self):
        self.roles = crc.contracts(ROOT / "agents")

    def test_every_role_agent_has_a_parsable_contract(self):
        self.assertEqual(len(self.roles), len(list((ROOT / "agents").glob("afs-*.agent.md"))))

    def test_complete_contract_passes(self):
        ok, msg = crc.check(MIGRATOR, self.roles)
        self.assertTrue(ok, msg)
        self.assertIn("afs-migrator", msg)

    def test_missing_block_and_missing_keys_fail(self):
        self.assertFalse(crc.check("No yaml here.", self.roles)[0])
        ok, msg = crc.check(MIGRATOR.replace("handoff: null\n", ""), self.roles)
        self.assertFalse(ok)
        self.assertIn("handoff", msg)

    def run_event(self, body, ref, login):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"pull_request": {"body": body, "head": {"ref": ref}, "user": {"login": login}}}, fh)
        return subprocess.run([sys.executable, str(ROOT / "tools/check_return_contract.py"), "--event", fh.name,
                               "--agents", str(ROOT / "agents")], capture_output=True, text=True)

    def test_only_agent_prs_are_checked(self):
        self.assertEqual(self.run_event("no contract", "harness/upgrade", "martins-vds").returncode, 0)
        r = self.run_event("no contract", "copilot/tc-03", "Copilot")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error", r.stdout)
        self.assertEqual(self.run_event(MIGRATOR, "copilot/tc-03", "Copilot").returncode, 0)


if __name__ == "__main__":
    unittest.main()
