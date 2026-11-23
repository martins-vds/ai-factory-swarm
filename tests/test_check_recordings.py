"""ADR-0077: recorded legacy exchanges are append-only."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools/check_recordings.py"
REC = ".migration/characterization/source/goldens/http.json"


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def ex(body, status=200):
    return {"request": {"method": "GET", "path": "/x"}, "response": {"status": status, "body": body}}


class RecordingsTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._d.name)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        self.write({"GET /fees/L1": ex("296 days late"), "group": {"GET /loans": ex("L1\n")}})
        (self.repo / ".migration/profile.yaml").write_text("source: {repo: o/t, sha: aaa, path: legacy}\n")
        (self.repo / ".migration/characterization/notes.json").write_text(json.dumps({"not": "a recording"}))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "branch", "base")

    def tearDown(self):
        self._d.cleanup()

    def write(self, doc, path=REC):
        p = self.repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=2))

    def run_tool(self):
        return subprocess.run([sys.executable, str(TOOL), "--base", "base"], cwd=self.repo,
                              capture_output=True, text=True)

    def test_adding_exchanges_and_recordings_passes(self):
        self.write({"GET /fees/L1": ex("296 days late"), "group": {"GET /loans": ex("L1\n"), "GET /holds": ex("\n")},
                    "POST /holds": ex("H2", 201)})
        self.write({"POST /holds limit": ex("hold limit reached\n", 409)},
                   ".migration/characterization/source/goldens/hold-limit.json")
        (self.repo / ".migration/characterization/notes.json").write_text("{}")   # not a recording
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_re_recording_an_existing_exchange_fails(self):
        self.write({"GET /fees/L1": ex("311 days late"), "group": {"GET /loans": ex("L1\n")}})
        r = self.run_tool()
        self.assertEqual(r.returncode, 1)
        self.assertIn("exchange 'GET /fees/L1' changed", r.stdout)

    def test_removing_a_nested_exchange_or_a_recording_fails(self):
        self.write({"GET /fees/L1": ex("296 days late"), "group": {}})
        self.assertIn("'group / GET /loans' was removed", self.run_tool().stdout)
        (self.repo / REC).unlink()
        self.assertIn("a recording was deleted", self.run_tool().stdout)

    def test_a_change_that_moves_the_source_pin_may_re_record(self):
        self.write({"GET /fees/L1": ex("311 days late"), "group": {"GET /loans": ex("L1\n")}})
        (self.repo / ".migration/profile.yaml").write_text("source: {repo: o/t, sha: bbb, path: legacy}\n")
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("skipped=source-pin-moved", r.stdout)


if __name__ == "__main__":
    unittest.main()
