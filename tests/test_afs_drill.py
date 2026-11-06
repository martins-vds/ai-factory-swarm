"""tools/afs-drill (ADR-0027 amendment): drills are data; operations take paths from the target."""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
_loader = importlib.machinery.SourceFileLoader("afs_drill", str(ROOT / "tools" / "afs-drill"))
_spec = importlib.util.spec_from_loader("afs_drill", _loader)
drill = importlib.util.module_from_spec(_spec)
_loader.exec_module(drill)


class TargetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.put(".migration/profile.yaml",
                 "target:\n  stacks:\n    backend: [python-3.13, django-5]\nthresholds:\n  crap_max_per_method: 30\n"
                 "services:\n  compose: compose.yaml\n  test: [db]\n"
                 "gates:\n  crap: [\"python .migration/harness/tools/crap.py runs/lizard.csv --lcov runs/crap.lcov --max 30\"]\n")
        self.put("compose.yaml", "services:\n  db:\n    image: postgres:16\n    healthcheck:\n      test: [CMD, pg_isready]\n")
        self.put(".migration/harness/installed.json", json.dumps({"entries": [
            {"path": ".github/skills/x", "kind": "skill", "files": {".github/skills/x/SKILL.md": "h"}},
            {"path": ".github/agents/afs-a.agent.md", "kind": "agent", "files": {".github/agents/afs-a.agent.md": "h"}}]}))
        self.put(".github/agents/afs-a.agent.md", "agent\n")
        self.put(".migration/graphs/source/full/SNAPSHOT.txt", "source_sha: abc\nscope: full\n")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, path, text):
        f = self.root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def read(self, path):
        return (self.root / path).read_text()


class OperationsTest(TargetTest):
    def test_edit_installed_edits_an_installed_file_of_that_kind(self):
        self.assertEqual(str(drill.op_edit_installed(self.root, "agent")), ".github/agents/afs-a.agent.md")
        self.assertIn("afs-drill", self.read(".github/agents/afs-a.agent.md"))

    def test_replace_works_on_the_profile_and_refuses_a_miss(self):
        drill.op_replace(self.root, "@profile", r"\bpython-\d+(\.\d+)?\b", **{"with": "python-2.7"})
        self.assertIn("python-2.7", self.read(".migration/profile.yaml"))
        with self.assertRaises(RuntimeError):
            drill.op_replace(self.root, "@profile", "no-such-text", **{"with": "x"})

    def test_drop_healthcheck_uses_the_profile_services(self):
        drill.op_drop_healthcheck(self.root)
        self.assertNotIn("healthcheck", yaml.safe_load(self.read("compose.yaml"))["services"]["db"])
        with self.assertRaises(RuntimeError, msg="nothing left to drop"):
            drill.op_drop_healthcheck(self.root)

    def test_snapshot_set_rewrites_one_key(self):
        drill.op_snapshot_set(self.root, ".migration/graphs/source/*/SNAPSHOT.txt", "source_sha", "000")
        self.assertEqual(self.read(".migration/graphs/source/full/SNAPSHOT.txt"), "source_sha: 000\nscope: full\n")

    def test_every_shipped_drill_applies_to_a_target(self):
        for spec in drill.load():
            with self.subTest(spec["id"]):
                self.setUp()
                drill.apply_ops(self.root, spec["ops"])


class DrillDataTest(unittest.TestCase):
    def test_drills_are_well_formed(self):
        tools = {p.name for p in (ROOT / "tools").iterdir()}
        workflows = {p.name for p in (ROOT / "templates" / "target").glob("*.yml")}
        ids = [d["id"] for d in drill.load()]
        self.assertEqual(len(ids), len(set(ids)), "drill ids are unique")
        for d in drill.load():
            with self.subTest(d["id"]):
                self.assertIn(d["trigger"], {"pr", "stacked_pr", "dispatch"})
                self.assertTrue(all(o["op"] in drill.OPS for o in d["ops"]))
                if "tool" in d["expect"]:
                    self.assertIn(d["expect"]["tool"], tools, "a drill expects a real tool")
                if d["trigger"] == "dispatch":
                    self.assertIn(d["workflow"], workflows)


class VerdictTest(unittest.TestCase):
    def test_caught_by_a_failing_tool_line(self):
        logs = [("check / harness", "x\nAFS-TOOL check_installed.py exit=0\n"),
                ("check / gates", "AFS-TOOL check_installed.py exit=1\n")]
        self.assertEqual(drill.judge({"tool": "check_installed.py"}, [], logs),
                         (True, "check / gates: check_installed.py exit=1"))

    def test_missed_when_the_tool_passed_or_never_ran(self):
        self.assertEqual(drill.judge({"tool": "t.py"}, [], [("a", "AFS-TOOL t.py exit=0")]), (False, "t.py only exited 0"))
        self.assertEqual(drill.judge({"tool": "t.py"}, [], [("a", "AFS-TOOL t2.py exit=1")]), (False, "t.py never ran"))

    def test_workflow_conclusion(self):
        runs = [{"name": "AFS acceptance", "conclusion": "failure"}]
        self.assertTrue(drill.judge({"workflow": "failure"}, runs, [])[0])
        self.assertFalse(drill.judge({"workflow": "failure"}, [{"name": "x", "conclusion": "success"}], [])[0])

    def test_report_marks_each_drill(self):
        text = drill.report([{"id": "a", "caught": True, "evidence": "x|y", "runs": ["u"]},
                             {"id": "b", "caught": False, "evidence": "drill error: boom"}])
        self.assertIn("| `a` | ✅ | x/y | [run](u) |", text)
        self.assertIn("| `b` | ❌ |", text)


if __name__ == "__main__":
    unittest.main()
