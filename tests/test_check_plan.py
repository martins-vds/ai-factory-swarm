"""tools/check_plan.py: plan ticket checks before dispatch (harness #98)."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_plan  # noqa: E402

SCHEMAS = ROOT / "schemas"


def ticket(tid, files, role="afs-migrator", blocked_by=(), capabilities=None):
    t = {"id": tid, "role": role, "files": list(files), "blocked_by": list(blocked_by)}
    if capabilities is not None:
        t["capabilities"] = capabilities
    return t


class CheckPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.mig = self.root / ".migration"
        (self.mig / "plan").mkdir(parents=True)
        (self.mig / "returns").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, name, tickets, cross_slice=None):
        (self.mig / "plan" / f"{name}.md").write_text(f"# {name}\n")
        doc = {"slice": name, "tickets": tickets}
        if cross_slice:
            doc["cross_slice"] = cross_slice
        (self.mig / "plan" / f"{name}.tickets.yaml").write_text(yaml.safe_dump(doc))

    def touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

    def errors(self):
        errs = []
        check_plan.check(self.mig, SCHEMAS, errs)
        return errs

    def test_a_clean_plan_passes(self):
        self.plan("booking", [
            ticket("BK-05A", ["src/booking/a.py", "tests/booking/test_a.py", ".migration/ledger/booking.a.yaml"],
                   capabilities=["booking.a"]),
            ticket("BK-05B", ["src/booking/a.py"], blocked_by=["BK-05A"]),
        ])
        self.assertEqual(self.errors(), [])

    def test_plan_without_tickets_file(self):
        (self.mig / "plan" / "booking.md").write_text("# booking\n")
        self.assertIn("no booking.tickets.yaml", "\n".join(self.errors()))

    def test_reused_id_from_another_role(self):
        self.plan("booking", [ticket("BK-03", ["src/x.py"])])
        self.touch(".migration/returns/BK-03.afs-characterizer.yaml")
        self.assertIn("BK-03 is already used by afs-characterizer", "\n".join(self.errors()))

    def test_verifier_return_on_the_same_id_is_fine(self):
        self.plan("booking", [ticket("BK-05A", ["src/x.py"])])
        self.touch(".migration/returns/BK-05A.afs-verifier.yaml")
        self.assertEqual(self.errors(), [])

    def test_unknown_blocker_and_no_files(self):
        self.plan("booking", [ticket("BK-05A", [], blocked_by=["BK-99"])])
        text = "\n".join(self.errors())
        self.assertIn("blocked by BK-99, which no plan lists", text)
        self.assertIn("BK-05A (afs-migrator) names no files", text)

    def test_shared_file_needs_a_blocking_edge(self):
        self.plan("booking", [ticket("BK-05A", ["templates/booking/"]), ticket("BK-05B", ["templates/booking/x.html"])])
        self.assertIn("BK-05A and BK-05B both change templates/booking/x.html", "\n".join(self.errors()))

    def test_transitive_edge_is_enough(self):
        self.plan("booking", [ticket("A-1", ["f.py"]), ticket("A-2", ["g.py"], blocked_by=["A-1"]),
                              ticket("A-3", ["f.py"], blocked_by=["A-2"])])
        self.assertEqual(self.errors(), [])

    def test_done_tickets_are_not_held_to_the_open_checks(self):
        self.plan("booking", [ticket("BK-05A", ["f.py"]), ticket("BK-05B", ["f.py"])])
        self.touch(".migration/returns/BK-05A.afs-migrator.yaml")
        self.assertEqual(self.errors(), [])

    def test_done_before_returns_skips_the_open_checks(self):
        t = ticket("TC-01", [])
        t["done_before_returns"] = True
        self.plan("track-cargo", [t])
        self.assertEqual(self.errors(), [])
        self.touch(".migration/returns/TC-01.afs-migrator.yaml")
        self.assertIn("drop done_before_returns", "\n".join(self.errors()))

    def test_file_shared_across_slices_must_be_listed(self):
        self.plan("booking", [ticket("BK-05H", ["src/urls.py"])])
        self.plan("admin-live-map", [ticket("AM-04A", ["src/urls.py"], blocked_by=["BK-05H"])])
        self.assertEqual(sum("list it under cross_slice" in e for e in self.errors()), 2)
        shared = [{"file": "src/urls.py", "slices": ["admin-live-map", "booking"]}]
        self.plan("booking", [ticket("BK-05H", ["src/urls.py"])], shared)
        self.plan("admin-live-map", [ticket("AM-04A", ["src/urls.py"], blocked_by=["BK-05H"])], shared)
        self.assertEqual(self.errors(), [])

    def test_test_name_clash_needs_a_package_init(self):
        # pilot BK-05C: tests/pathfinder/test_routing.py already existed
        self.touch("tests/pathfinder/test_routing.py")
        self.plan("booking", [ticket("BK-05C", ["tests/booking/application/test_routing.py"])])
        self.assertIn("add tests/booking/application/__init__.py", "\n".join(self.errors()))
        self.plan("booking", [ticket("BK-05C", ["tests/booking/application/test_routing.py",
                                                "tests/booking/application/__init__.py"])])
        self.assertEqual(self.errors(), [])

    def test_capability_needs_its_ledger_entry(self):
        self.plan("booking", [ticket("BK-05C", ["src/r.py"], capabilities=["booking.routing-assign"])])
        self.assertIn("add .migration/ledger/booking.routing-assign.yaml", "\n".join(self.errors()))

    def test_schema_errors_and_duplicate_ids(self):
        self.plan("booking", [ticket("BK-05A", ["a.py"]), ticket("BK-05A", ["b.py"])])
        self.assertIn("BK-05A is also planned", "\n".join(self.errors()))
        (self.mig / "plan" / "booking.tickets.yaml").write_text("slice: booking\ntickets: [{id: x}]\n")
        self.assertTrue(any("tickets/0" in e for e in self.errors()))

    def test_ticket_files_lookup(self):
        self.plan("booking", [ticket("BK-05A", ["a.py", "b/"])])
        self.assertEqual(check_plan.ticket_files(self.mig, "BK-05A"), ["a.py", "b/"])
        self.assertIsNone(check_plan.ticket_files(self.mig, "BK-99"))

    def test_validate_runs_the_plan_check(self):
        self.plan("booking", [ticket("BK-05A", [])])
        (self.mig / "capabilities.yaml").write_text("")
        out = subprocess.run([sys.executable, str(ROOT / "tools/validate.py"), str(self.mig)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("names no files", out.stderr)


if __name__ == "__main__":
    unittest.main()
