"""ADR-0047: concurrent work never owns the same file, and no new module shadows a package (or back)."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_dispatch_paths as cdp  # noqa: E402

PLAN = """slice: s
tickets:
  - id: A
    files: [src/x/views.py, templates/a.html, .migration/returns/A.afs-migrator.yaml]
  - id: B
    files: [src/x/forms.py, templates/a.html]
  - id: C
    files: [src/x/views/__init__.py, .migration/returns/C.afs-migrator.yaml]
"""


class DispatchPathsTest(unittest.TestCase):
    def test_a_file_owned_twice_is_named(self):
        found = cdp.conflicts({"A": ["templates/a.html", "src/x/views.py"], "#9": ["templates/a.html"]})
        self.assertEqual(len(found), 1)
        self.assertIn("`templates/a.html` is owned by both A and #9", found[0])

    def test_each_sessions_own_records_dont_count(self):
        self.assertEqual(cdp.conflicts({"A": [".migration/evidence/runs/x.md"], "B": [".migration/evidence/runs/x.md"]}), [])

    def test_a_package_that_shadows_a_module_is_named(self):
        found = cdp.conflicts({"C": ["src/x/views/__init__.py"]}, base_files=["src/x/views.py"])
        self.assertTrue(any("`src.x.views` is both a module" in f for f in found), found)
        self.assertEqual(cdp.conflicts({}, base_files=["src/x/views.py", "src/x/views/__init__.py"]), [],
                         "what main already has isn't this dispatch's doing")
        self.assertEqual(cdp.conflicts({"A": ["templates/views/a.html"]}, base_files=["templates/views.py"]), [])

    def test_ci_reports_only_this_prs_conflicts_and_skips_its_own_stack(self):
        work = {"#1": ["a.py"], "#2": ["b.py"], "#3": ["b.py"]}
        self.assertEqual(cdp.conflicts(work, focus="#1"), [])
        self.assertEqual(len(cdp.conflicts({**work, "#4": ["a.py"]}, focus="#1")), 1)
        prs = [{"number": 1, "head": {"ref": "w"}, "base": {"ref": "main"}},
               {"number": 2, "head": {"ref": "v"}, "base": {"ref": "w"}},
               {"number": 3, "head": {"ref": "u"}, "base": {"ref": "main"}}]
        self.assertEqual(cdp.stack_of("o/t", 2, prs), {"#1", "#2"})

    def test_the_cli_checks_tickets_from_the_plan(self):
        with tempfile.TemporaryDirectory() as d:
            plan = pathlib.Path(d, ".migration/plan")
            plan.mkdir(parents=True)
            (plan / "s.tickets.yaml").write_text(PLAN)
            subprocess.run(["git", "init", "-q", d], check=True)
            self.assertEqual(cdp.main(["--tickets", "A,C", "--root", d]), 1)   # src.x.views module + package
            self.assertEqual(cdp.main(["--tickets", "A,B", "--root", d]), 1)   # templates/a.html twice
            pathlib.Path(d, "prs.json").write_text("[]")
            self.assertEqual(cdp.main(["--tickets", "B", "--root", d, "--open-prs", str(pathlib.Path(d, "prs.json"))]), 0)


if __name__ == "__main__":
    unittest.main()
