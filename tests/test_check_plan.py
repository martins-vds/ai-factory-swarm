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

    def test_the_retired_specialist_role_is_refused_on_open_tickets_and_kept_on_finished_ones(self):
        self.plan("booking", [ticket("BK-01", ["src/a.py"], role="afs-specialist-migrator"),
                              ticket("BK-02", ["src/b.py"], role="afs-specialist-migrator")])
        self.touch(".migration/returns/BK-02.afs-specialist-migrator.yaml")
        errs = self.errors()
        self.assertTrue(any("BK-01 uses the retired role afs-specialist-migrator" in e and "ADR-0042" in e
                            for e in errs), errs)
        self.assertFalse(any("BK-02 uses the retired role" in e for e in errs), "finished tickets keep history")

    def test_rework_of_a_retired_role_ticket_by_its_successor_keeps_the_id(self):
        # eval fold-r1..r3: the Migrator reworks BK-05F, which the Specialist Migrator finished before the fold.
        self.plan("booking", [ticket("BK-05F", ["src/a.py"], role="afs-specialist-migrator"),
                              ticket("BK-05H", ["src/b.py"])])
        self.touch(".migration/returns/BK-05F.afs-specialist-migrator.yaml")
        self.touch(".migration/returns/BK-05F.afs-migrator.yaml")
        self.touch(".migration/returns/BK-05H.afs-specialist-migrator.yaml")
        errs = "\n".join(self.errors())
        self.assertNotIn("already used", errs)

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


class PlannerChecksTest(CheckPlanTest):
    """ADR-0048: the planner checks phase 3b adds, each with the run that showed the loss."""

    def spec(self, name, anchors):
        (self.mig / "slices").mkdir(exist_ok=True)
        (self.mig / "slices" / f"{name}.yaml").write_text(yaml.safe_dump({"data_paths": {"target": anchors}}))

    def test_a_new_slices_target_anchors_are_built_by_its_tickets(self):
        # Synthetic #77, #89, #99: the spec named routes the code never had.
        self.spec("loans", ["endpoint=GET /loans", "endpoint=/ui/loans/"])
        t = ticket("LL-01", ["src/loans/views.py"])
        t["builds"] = ["endpoint=GET /loans"]
        self.plan("loans", [t])
        errs = self.errors()
        self.assertTrue(any("endpoint=/ui/loans/" in e and "builds" in e for e in errs), errs)
        t["builds"].append("endpoint=/ui/loans/")
        self.plan("loans", [t])
        self.assertEqual(self.errors(), [])

    def test_a_started_slice_isnt_held_to_builds(self):
        self.spec("loans", ["endpoint=GET /loans"])
        self.plan("loans", [ticket("LL-01", ["src/loans/views.py"]), ticket("LL-02", ["src/loans/forms.py"])])
        (self.mig / "returns" / "LL-01.afs-migrator.yaml").write_text("role: afs-migrator\n")
        self.assertEqual(self.errors(), [])

    def test_a_planned_page_is_under_target_paths(self):
        # Synthetic #76: templates/ wasn't in target_paths, so the target graph never saw the pages.
        (self.mig / "profile.yaml").write_text(yaml.safe_dump({"graph": {"target_paths": ["src"]}}))
        self.plan("loans", [ticket("LL-01", ["src/loans/views.py", "templates/loans/list.html"])])
        errs = self.errors()
        self.assertTrue(any("templates/loans/list.html" in e and "target_paths" in e for e in errs), errs)
        (self.mig / "profile.yaml").write_text(yaml.safe_dump({"graph": {"target_paths": ["src", "templates"]}}))
        self.assertEqual(self.errors(), [])

    def test_removing_a_module_needs_its_importing_tests(self):
        self.touch("src/loans/old.py")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_old.py").write_text("from loans.old import thing\n")
        t = ticket("LL-03", ["src/loans/old.py"])
        t["removes"] = ["src/loans/old.py"]
        self.plan("loans", [t])
        errs = self.errors()
        self.assertTrue(any("tests/test_old.py imports" in e for e in errs), errs)
        owner = ticket("LL-02", ["tests/test_old.py"])
        t["blocked_by"] = ["LL-02"]
        self.plan("loans", [owner, t])
        self.assertEqual(self.errors(), [])

    def test_an_issue_that_drifts_from_the_plan_fails(self):
        # LL-01 #71, LL-04 #107: the issue's file list drifted, and the session followed the issue.
        self.plan("loans", [ticket("LL-04", ["src/a.py", "tests/test_a.py", ".migration/returns/LL-04.afs-migrator.yaml"])])
        body = ("- **Files** (touch only these):\n  - `src/a.py`\n  - `src/b.py`\n"
                "  - `.migration/returns/LL-04.afs-migrator.yaml`\n\nAFS-SCOPE: src/c.py\n")
        errs = []
        plans = check_plan.load_plans(self.mig, SCHEMAS, errs)
        check_plan.check_issue_drift(plans, {}, [{"number": 107, "title": "LL-04 · Report", "body": body}], errs)
        self.assertEqual(len(errs), 1)
        self.assertIn("not planned: src/b.py", errs[0])
        self.assertIn("planned but not listed: tests/test_a.py", errs[0])
        ok = body.replace("`src/b.py`", "`tests/test_a.py`")
        errs = []
        check_plan.check_issue_drift(plans, {}, [{"number": 107, "title": "LL-04 · Report", "body": ok}], errs)
        self.assertEqual(errs, [])


class SpecOwnerTest(CheckPlanTest):
    """ADR-0062: the Characterizer writes the customer spec, before the Migrator builds what it describes."""

    LEDGER = ".migration/ledger/fees.calc.yaml"

    def require_specs(self):
        (self.mig / "profile.yaml").write_text(yaml.safe_dump({"spec": {"adapter": "django", "required": True}}))

    def test_only_a_characterizer_ticket_plans_spec_files(self):
        self.plan("fees", [ticket("FE-01", ["src/fees.py", ".migration/spec/fees/late.yaml"]),
                           ticket("FE-02", [".migration/spec/fees/"], role="afs-characterizer", blocked_by=["FE-01"])])
        errs = self.errors()
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("FE-01 (afs-migrator) plans .migration/spec/fees/late.yaml: only an afs-characterizer", errs[0])

    def test_with_specs_required_a_build_ticket_waits_for_its_slice_spec(self):
        self.require_specs()
        self.plan("fees", [ticket("FE-01", ["src/fees.py", self.LEDGER], capabilities=["fees.calc"])])
        self.assertIn("FE-01 builds fees.calc, which has no spec yet: block it on an afs-characterizer ticket "
                      "that plans .migration/spec/fees/", "\n".join(self.errors()))
        self.plan("fees", [ticket("FE-00", [".migration/spec/fees/", self.LEDGER], role="afs-characterizer"),
                           ticket("FE-01", ["src/fees.py", self.LEDGER], capabilities=["fees.calc"],
                                  blocked_by=["FE-00"])])
        self.assertEqual(self.errors(), [])

    def test_a_committed_spec_is_enough_and_without_the_flag_nothing_is_required(self):
        self.plan("fees", [ticket("FE-01", ["src/fees.py", self.LEDGER], capabilities=["fees.calc"])])
        self.assertEqual(self.errors(), [])
        self.require_specs()
        spec = self.mig / "spec/fees/late.yaml"
        spec.parent.mkdir(parents=True)
        spec.write_text(yaml.safe_dump({"capability": "fees.calc", "cases": []}))
        self.assertEqual(self.errors(), [])
