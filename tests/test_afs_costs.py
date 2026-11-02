"""tools/afs-costs (ADR-0021 phase 1.1): billed usage attributed to harness sessions, clearly as an estimate."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools/afs-costs"


def run(cwd, *args, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ("BILLING_READ_TOKEN", "GITHUB_REPOSITORY")}
    e.update(env or {})
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd, capture_output=True, text=True, env=e)


class CostsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        c = self.dir / ".migration/costs"
        (c / "billing").mkdir(parents=True)
        for sid, branch, out in (("a", "copilot/tc-15-accept", 3000), ("b", "copilot/tc-15c-raise", 1000),
                                 ("c", "main", 0)):
            (c / f"{sid}.json").write_text(json.dumps({
                "schema": "afs-cost/1", "session_id": sid, "branch": branch, "ended_at": "2026-11-02T22:12:00Z",
                "models": {"unknown": {"output": out}}, "usage_source": "assistant.message (output only, partial)"}))
        (c / "billing/2026-11-02.json").write_text(json.dumps({
            "date": "2026-11-02",
            "ai_credits": [{"product": "Copilot", "sku": "Copilot coding agent AI Credits", "unitType": "credits",
                            "grossQuantity": 800, "netQuantity": 800},
                           {"product": "Copilot", "sku": "Copilot AI Credits", "unitType": "credits",
                            "grossQuantity": 200, "netQuantity": 200}],
            "usage": [{"product": "Actions", "quantity": 95, "repositoryName": "o/pilot"},
                      {"product": "Actions", "quantity": 40, "repositoryName": "o/other"}]}))
        (c / "not-a-record.json").write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_shares_agent_credits_by_output_tokens(self):
        r = run(self.dir, "report", env={"GITHUB_REPOSITORY": "o/pilot"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| 2026-11-02 | 3 | 4,000 | 1,000 | 800 | 95 |", r.stdout)
        self.assertIn("| TC-15 | 1 | 3,000 | 600 | $6.00 |", r.stdout)
        self.assertIn("| TC-15c | 1 | 1,000 | 200 | $2.00 |", r.stdout)
        self.assertIn("| unattributed | 1 | 0 | 0 | $0.00 |", r.stdout)
        self.assertIn("**estimates**", r.stdout)
        self.assertIn("AFS-RESULT gate=costs sessions=3 billed_days=1 credits=1000 agent_credits=800 actions_minutes=95",
                      r.stdout)

    def test_fetch_without_config_or_token_only_warns(self):
        (self.dir / ".migration/profile.yaml").write_text("harness_version: 0.2.0\n")
        r = run(self.dir, "fetch", "--date", "2026-11-02")
        self.assertEqual(r.returncode, 0)
        self.assertIn("No costs.billing", r.stdout)
        (self.dir / ".migration/profile.yaml").write_text("costs: {billing: {scope: user, account: someone}}\n")
        r = run(self.dir, "fetch", "--date", "2026-11-02")
        self.assertEqual(r.returncode, 0)
        self.assertIn("BILLING_READ_TOKEN is not set", r.stdout)


if __name__ == "__main__":
    unittest.main()
