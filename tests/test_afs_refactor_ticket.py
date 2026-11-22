"""afs-refactor-ticket (ADR-0072): a periodic behaviour-preserving refactor, chosen the same way every time."""
import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("afs_refactor_ticket", str(ROOT / "tools/afs-refactor-ticket"))
spec = importlib.util.spec_from_loader("afs_refactor_ticket", loader)
rt = importlib.util.module_from_spec(spec)
loader.exec_module(rt)

FEES = """slice: fees
# The fee slice: LL-03 built it.
tickets:
  - id: LL-03
    role: afs-migrator
    files: [src/fees/, tests/fees/]
    blocked_by: []

cross_slice:
  - file: config/urls.py
    slices: [fees, loans]
"""


class RefactorTicketTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._d.name)
        mig = self.root / ".migration"
        for sub in ("plan", "returns"):
            (mig / sub).mkdir(parents=True)
        (mig / "plan/fees.tickets.yaml").write_text(FEES)
        (mig / "plan/loans.tickets.yaml").write_text(yaml.safe_dump({"slice": "loans", "tickets": [
            {"id": "LL-01", "role": "afs-migrator", "files": ["src/loans/"], "blocked_by": []}]}))
        (mig / "plan/reports.tickets.yaml").write_text(yaml.safe_dump({"slice": "reports", "tickets": [
            {"id": "LL-05", "role": "afs-migrator", "files": ["src/reports/"], "blocked_by": []}]}))
        for tid in ("LL-03", "LL-01"):                              # LL-05 isn't finished: reports is skipped
            (mig / f"returns/{tid}.afs-migrator.yaml").write_text("ticket: x\n")
        for pkg, files in {"fees": {"views.py": "def _a(): pass\ndef _b(): pass\ndef _c(): pass\ndef page(): pass\n",
                                    "gateway.py": "def _open(): pass\ndef _x(): pass\n",
                                    "__init__.py": "def _hidden(): pass\ndef _also(): pass\ndef _more(): pass\n"},
                           "loans": {"views.py": "def _one(): pass\ndef _two(): pass\n"},
                           "reports": {"service.py": "def _p(): pass\ndef _q(): pass\ndef _r(): pass\ndef _s(): pass\n"}}.items():
            (self.root / "src" / pkg).mkdir(parents=True)
            for name, text in files.items():
                (self.root / "src" / pkg / name).write_text(text)

    def tearDown(self):
        self._d.cleanup()

    def test_the_slice_and_module_are_chosen_the_same_way_every_time(self):
        name, _, doc, module, helpers = rt.choose(self.root)
        self.assertEqual(name, "fees")                               # no refactor yet; fees before loans by name
        self.assertEqual(module.relative_to(self.root).as_posix(), "src/fees/views.py")   # 3 helpers beat 2
        self.assertEqual(helpers, ["_a", "_b", "_c"])

    def test_written_ticket_keeps_the_plan_text_and_the_next_one_goes_to_another_slice(self):
        self.assertEqual(rt.main(["propose", "--root", str(self.root), "--date", "2026-11-22", "--write",
                                  "--issue-out", str(self.root / "issue.md")]), 0)
        text = (self.root / ".migration/plan/fees.tickets.yaml").read_text()
        self.assertTrue(text.startswith(FEES.split("\ncross_slice")[0]))
        self.assertIn("# The fee slice: LL-03 built it.", text)
        self.assertTrue(text.rstrip().endswith("slices: [fees, loans]"))
        ticket = yaml.safe_load(text)["tickets"][-1]
        self.assertEqual((ticket["id"], ticket["files"], ticket["refactor"]),
                         ("REF-20261122-FEES", ["src/fees/", "tests/fees/"], True))
        issue = (self.root / "issue.md").read_text()
        self.assertIn("`src/fees/views.py` keeps 3 private helpers: `_a`, `_b`, `_c`", issue)
        self.assertIn("Change an existing test only if the restructuring", issue)
        self.assertIn("## REF-20261122-FEES", (self.root / ".migration/plan/fees.md").read_text())
        self.assertEqual(rt.choose(self.root, None)[0], "loans")     # fees was refactored; loans hasn't been
        self.assertEqual(rt.main(["propose", "--root", str(self.root), "--slice", "fees", "--date", "2026-11-22",
                                  "--write"]), 0)
        self.assertEqual(yaml.safe_load((self.root / ".migration/plan/fees.tickets.yaml").read_text())["tickets"][-1]["id"],
                         "REF-20261122-FEES")                        # the same day's ticket isn't planned twice
        self.assertEqual(len(yaml.safe_load((self.root / ".migration/plan/fees.tickets.yaml").read_text())["tickets"]), 2)
