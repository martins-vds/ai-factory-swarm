"""ADR-0021: session records are expected in agent PRs and append-only (CI guard + contract)."""
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def guard_script():
    doc = yaml.safe_load((ROOT / "templates/target/afs-harness-check.yml").read_text().replace("{{", "{")
                         .replace("}}", "}"))
    steps = [s for job in doc["jobs"].values() for s in job["steps"] if s.get("name") == "Session records are append-only"]
    assert steps, "the harness check must guard session records"
    return steps[0]["run"].replace("${{ github.base_ref }}", "base")


class SessionRecordTest(unittest.TestCase):
    def run_guard(self, change):
        with tempfile.TemporaryDirectory() as d:
            git = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
            git("init", "-q", "-b", "base")
            rec = pathlib.Path(d) / ".migration/costs/s1.json"
            rec.parent.mkdir(parents=True)
            rec.write_text("{}\n")
            git("add", "-A")
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
            git("update-ref", "refs/remotes/origin/base", "HEAD")
            git("checkout", "-qb", "pr")
            change(pathlib.Path(d))
            git("add", "-A")
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "pr", "--allow-empty")
            return subprocess.run(["bash", "-c", guard_script()], cwd=d, capture_output=True, text=True)

    def test_adding_is_fine_changing_or_deleting_fails(self):
        add = self.run_guard(lambda d: (d / ".migration/costs/s2.json").write_text("{}\n"))
        self.assertEqual(add.returncode, 0, add.stdout)
        edit = self.run_guard(lambda d: (d / ".migration/costs/s1.json").write_text('{"x": 1}\n'))
        self.assertEqual(edit.returncode, 1)
        self.assertIn("append-only", edit.stdout)
        delete = self.run_guard(lambda d: (d / ".migration/costs/s1.json").unlink())
        self.assertEqual(delete.returncode, 1)

    def test_the_contract_lists_session_records_as_expected(self):
        text = (ROOT / "skills/afs-migration-contract/SKILL.md").read_text()
        self.assertIn("`.migration/costs/<session>.json`", text)
        self.assertIn("never\nremove or edit one", text)


if __name__ == "__main__":
    unittest.main()
