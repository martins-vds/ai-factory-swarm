"""Capability-gap issues close when the checklist on main says the gap is closed (synthetic target: six gap
issues stayed open after the scaffolding met them)."""
import contextlib
import io
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import close_gap_issues as cgi  # noqa: E402

REPO = "o/r"


def issue(n, title):
    return {"number": n, "title": title, "labels": [{"name": "afs:capability-gap"}]}


class CloseGapIssuesTest(unittest.TestCase):
    def run_tool(self, entries, issues, *extra):
        with tempfile.TemporaryDirectory() as d:
            caps = pathlib.Path(d) / "capabilities.yaml"
            caps.write_text(yaml.safe_dump({"capabilities": entries}))
            calls = []

            def gh(path, *args, data=None):
                calls.append((path, args, data))
                if path.startswith(f"repos/{REPO}/issues?state=open"):
                    return issues
                return {}
            out = io.StringIO()
            with mock.patch.object(cgi, "gh", side_effect=gh), contextlib.redirect_stdout(out):
                rc = cgi.main(["--repo", REPO, "--capabilities", str(caps), *extra])
        return rc, out.getvalue(), [c for c in calls if c[1]]

    def test_met_waived_and_not_applicable_close_open_gap_stays(self):
        entries = [
            {"id": "build-run", "applies_to": "target", "status": "met", "ticket": "o/r#11",
             "provided_by": [{"kind": "tool", "name": "manage.py"}]},
            {"id": "coverage", "applies_to": "target", "status": "met",      # ticket dropped: match by title
             "provided_by": [{"kind": "tool", "name": "pytest-cov"}]},
            {"id": "data-migration", "applies_to": "both", "status": "waived", "ticket": "o/r#20",
             "waiver": {"reason": "seed data only", "approved_by": "martins-vds"}},
            {"id": "mutation-testing", "applies_to": "both", "status": "gap", "ticket": "o/r#18"},
        ]
        issues = [issue(11, "Capability gap: build-run (target)"), issue(15, "Capability gap: coverage (target)"),
                  issue(20, "Capability gap: data-migration (both)"), issue(18, "Capability gap: mutation-testing (both)"),
                  issue(30, "Capability gap: something-else (source)")]
        rc, out, writes = self.run_tool(entries, issues)
        self.assertEqual(rc, 0)
        closes = {int(p.split("/")[-1]): d["state_reason"] for p, a, d in writes if d and "state" in d}
        self.assertEqual(closes, {11: "completed", 15: "completed", 20: "not_planned"})
        comments = [d["body"] for p, a, d in writes if p.endswith("/comments")]
        self.assertTrue(any("`manage.py`" in c for c in comments))
        self.assertTrue(any("waived by martins-vds: seed data only" in c for c in comments))
        self.assertIn("AFS-RESULT gate=gap-issues open=5 closed=3", out)

    def test_dry_run_writes_nothing(self):
        entries = [{"id": "lint-format", "applies_to": "both", "status": "met", "ticket": "o/r#19",
                    "provided_by": [{"kind": "tool", "name": "ruff"}]}]
        rc, out, writes = self.run_tool(entries, [issue(19, "Capability gap: lint-format (both)")], "--dry-run")
        self.assertEqual((rc, writes), (0, []))
        self.assertIn("(dry run)", out)

    def test_the_tool_is_installed_and_runs_on_main_only(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import bootstrap
        self.assertIn("close_gap_issues.py", bootstrap.HARNESS_TOOLS)
        text = (ROOT / "templates/target/afs-harness-check.yml").read_text()
        job = text.split("\n  gap-issues:\n", 1)[1].split("\n  reconciliation:\n", 1)[0]
        self.assertIn("github.event_name == 'push'", job)
        self.assertIn("issues: write", job)


if __name__ == "__main__":
    unittest.main()
