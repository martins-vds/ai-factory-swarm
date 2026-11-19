#!/usr/bin/env python3
"""Schema tests: the samples are valid, and every invalid fixture fails with its expected error."""
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATE = ROOT / "tools" / "validate.py"
INVALID = ROOT / "tests" / "fixtures" / "invalid"


def run(folder, *extra):
    return subprocess.run([sys.executable, str(VALIDATE), *extra, str(folder)], capture_output=True, text=True)


class ValidateTest(unittest.TestCase):
    def test_samples_are_valid(self):
        r = run(ROOT / "templates" / "migration", "--sample")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_invalid_fixtures_fail_for_the_right_reason(self):
        cases = [line.split("\t", 1) for line in (INVALID / "expected.tsv").read_text().splitlines() if line]
        self.assertTrue(cases)
        listed = {name for name, _ in cases}
        on_disk = {p.name for p in INVALID.iterdir() if p.is_dir()}
        self.assertEqual(listed, on_disk, "every fixture folder needs an expected.tsv row")
        for name, expected in cases:
            with self.subTest(fixture=name):
                r = run(INVALID / name, "--sample")
                self.assertEqual(r.returncode, 1, f"{name} should be invalid")
                self.assertIn(expected, r.stderr)



sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import validate as validate_mod  # noqa: E402


class ThresholdTest(unittest.TestCase):
    """A gate command's own limit must equal the profile threshold (pilot drill: --max 30 hid a threshold of 0)."""
    CMD = "python .migration/harness/tools/crap.py runs/lizard.csv --lcov runs/crap.lcov --max {}"

    def errors(self, limit, cmd_max):
        errs = []
        validate_mod.check_thresholds("profile.yaml", {"thresholds": {"crap_max_per_method": limit},
                                                       "gates": {"crap": ["lizard --csv src", self.CMD.format(cmd_max)]}}, errs)
        return errs

    def test_equal_limits_pass(self):
        self.assertEqual(self.errors(30, 30), [])

    def test_different_limits_fail(self):
        self.assertEqual(len(self.errors(0, 30)), 1)

    def test_a_gate_without_its_own_limit_passes(self):
        errs = []
        validate_mod.check_thresholds("p", {"thresholds": {"crap_max_per_method": 30}, "gates": {"crap": ["crap.py x"]}}, errs)
        self.assertEqual(errs, [])


class TierAttemptTest(unittest.TestCase):
    """ADR-0005 amendment: tier C only after the tier-B recipe was tried (SY-01B rated a source C from a failed
    `mvn package` alone, though its tested code compiles from source)."""
    def errs(self, **doc):
        out = []
        validate_mod.check_tier_attempt("r.yaml", {"role": "afs-bootstrapper", **doc}, out)
        return out

    def test_tier_c_without_an_attempt_is_rejected(self):
        self.assertTrue(self.errs(characterization_tier="C"))
        self.assertTrue(self.errs(characterization_tier="C", tier_b_attempt=None))
        self.assertTrue(self.errs(characterization_tier="C", tier_b_attempt="mvn package failed"))
        self.assertIn("tier-B recipe", self.errs(characterization_tier="C")[0])

    def test_tier_c_with_an_attempt_or_no_code_passes(self):
        self.assertEqual(self.errs(characterization_tier="C",
                                   tier_b_attempt="ran: javac -sourcepath src -implicit:class T.java -> 40 errors"), [])
        self.assertEqual(self.errs(characterization_tier="C", tier_b_attempt="no code: specs and CSV samples"), [])

    def test_other_tiers_and_roles_are_not_affected(self):
        self.assertEqual(self.errs(characterization_tier="A"), [])
        self.assertEqual(self.errs(characterization_tier="B"), [])
        out = []
        validate_mod.check_tier_attempt("r.yaml", {"role": "afs-verifier", "characterization_tier": "C"}, out)
        self.assertEqual(out, [])


class ShallowHistoryTest(unittest.TestCase):
    """A shallow clone can't prove a pre-rule return's exemption; the error must say so (pilot BK-04 restart)."""
    def test_detects_a_shallow_clone(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a, cwd: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                                 check=True, capture_output=True)
            src, dst = pathlib.Path(d) / "src", pathlib.Path(d) / "dst"
            src.mkdir()
            run("init", "-q", "-b", "main", cwd=src)
            for i in range(3):
                run("commit", "-q", "--allow-empty", "-m", f"c{i}", cwd=src)
            run("clone", "-q", "--depth", "1", src.as_uri(), str(dst), cwd=d)
            self.assertTrue(validate_mod.shallow_history(dst))
            self.assertFalse(validate_mod.shallow_history(src))


class ComponentReferenceTest(unittest.TestCase):
    """ADR-0018 amendment: a migrated ledger entry's target components name code that exists. Synthetic LL-02
    moved its use cases behind ports and left `src.loans.services.lend_loan` in the ledger; the circulation
    audit (LC-AUDIT) found it as `misplaced`, and nothing failed on the PR that caused it."""
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        files = {
            "src/loans/__init__.py": "",
            "src/loans/services.py": "class LoanApplication:\n    def lend(self):\n        pass\n\nVALUE = 1\n",
            "src/shop/views.py": "def create_dialog_views(x):\n    return x\n",
            "templates/tracking/result.html": "<p/>\n",
            "Makefile": "run:\n\tpython manage.py runserver\n",
        }
        for name, text in files.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text)

    def problems(self, *components, status="migrated"):
        errors = []
        validate_mod.check_components(self.root, "ledger/x.yaml",
                                      {"status": status, "target": {"components": list(components)}}, errors)
        return errors

    def test_existing_references_in_every_form_pass(self):
        self.assertEqual(self.problems(
            "src.loans.services.LoanApplication.lend", "loans.services.LoanApplication", "loans.services.VALUE",
            "loans", "templates.tracking.result", "templates/tracking/", "src/shop/views.py:create_dialog_views",
            "src/shop/views.py::create_dialog_views", "Makefile.run", "Leaflet 1.7.1 with OpenStreetMap tiles"), [])

    def test_a_function_moved_behind_a_port_is_stale(self):
        errors = self.problems("src.loans.services.lend_loan")
        self.assertEqual(len(errors), 1)
        self.assertIn("no 'lend_loan' in src/loans/services.py (stale reference)", errors[0])

    def test_a_missing_method_module_or_file_is_stale(self):
        errors = self.problems("src.loans.services.LoanApplication.return_loan", "src.loans.repository.Repo",
                               "templates/missing.html", "src/shop/views.py:gone", "Makefile.deploy")
        self.assertEqual(len(errors), 5, errors)

    def test_entries_not_yet_migrated_are_not_held_to_their_components(self):
        self.assertEqual(self.problems("src.loans.services.future_thing", status="in-progress"), [])

class VerifierVerdictTest(unittest.TestCase):
    """Phase 3e: the verdict follows the findings, and a serious finding carries evidence."""

    def setUp(self):
        import tempfile
        sys.path.insert(0, str(ROOT / "tools"))
        import validate
        self.validate = validate
        self.tmp = tempfile.TemporaryDirectory()
        self.mig = pathlib.Path(self.tmp.name) / ".migration"
        (self.mig / "evidence/runs").mkdir(parents=True)
        (self.mig / "returns").mkdir()
        (self.mig / "evidence/runs/T-1.md").write_text(
            "# Run journal: T-1\n\n| UTC | Gate | Exit | Seconds | Command | Log SHA-256 | First highlight | Result |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 2026-11-17T01:00:00+00:00 | layering | 1 | 0.2 | `python check_layers.py` | `abc` | x | |\n"
            "| 2026-11-17T01:01:00+00:00 | tests | 0 | 3.0 | `pytest -q` | `def` | | |\n")

    def tearDown(self):
        self.tmp.cleanup()

    def errors(self, **doc):
        ret = {"role": "afs-verifier", "ticket": "T-1", "verdict": "pass", "findings": [], "tests_added": []}
        ret.update(doc)
        path = self.mig / "returns/T-1.afs-verifier.yaml"
        path.write_text("x\n")
        errs = []
        self.validate.check_verifier_return(self.mig, path, ret, errs)
        return errs

    def test_pass_with_no_serious_finding_is_fine(self):
        self.assertEqual(self.errors(findings=[{"severity": "minor", "where": "a.py:1", "what": "naming"}]), [])

    def test_pass_with_a_major_finding_is_refused(self):
        errs = self.errors(findings=[{"severity": "major", "where": "a.py:1", "what": "x", "evidence": "run: layering"}])
        self.assertTrue(any("verdict pass with 1" in e for e in errs), errs)

    def test_changes_required_needs_a_serious_finding(self):
        # eval b3c LL-04 r1: changes-required with no major or blocker finding.
        errs = self.errors(verdict="changes-required",
                           findings=[{"severity": "minor", "where": "a.py:1", "what": "x"}])
        self.assertTrue(any("no blocker or major finding" in e for e in errs), errs)

    def test_a_serious_finding_needs_evidence(self):
        errs = self.errors(verdict="changes-required",
                           findings=[{"severity": "major", "where": "a.py:1", "what": "htmx doesn't swap 4xx"}])
        self.assertTrue(any("has no `evidence`" in e for e in errs), errs)

    def test_evidence_by_test_or_failing_run(self):
        ok = self.errors(verdict="changes-required", tests_added=["tests/x/test_a.py::test_rejects_ineligible"],
                         findings=[{"severity": "major", "where": "views.py:40", "what": "eligibility in the view",
                                    "evidence": "tests/x/test_a.py::test_rejects_ineligible"},
                                   {"severity": "blocker", "where": "routing.py:1", "what": "Http404 in a use case",
                                    "evidence": "run: layering"}])
        self.assertEqual(ok, [])
        errs = self.errors(verdict="changes-required",
                           findings=[{"severity": "major", "where": "a.py:1", "what": "x", "evidence": "run: tests"},
                                     {"severity": "major", "where": "b.py:1", "what": "y",
                                      "evidence": "tests/test_b.py::test_y"}])
        self.assertTrue(any("no failing run" in e for e in errs), errs)
        self.assertTrue(any("isn't in tests_added" in e for e in errs), errs)

    def test_blocked_names_the_gate(self):
        errs = self.errors(verdict="blocked", findings=[])
        self.assertTrue(any("blocked_reason" in e for e in errs), errs)
        errs = self.errors(verdict="blocked", blocked_reason="a serious defect")
        self.assertTrue(any("blocked_reason" in e for e in errs), errs)
        self.assertEqual(self.errors(verdict="blocked",
                                     blocked_reason="mutation_changed: the run was interrupted at 40 of 120 mutants"),
                         [])

    def test_inherited_defects_are_reported_apart(self):
        # Operator ruling 2026-11-17 (eval v3e LL-04): a defect from an earlier ticket never changes the verdict.
        ok = self.errors(verdict="pass", inherited=[{"where": "config/settings.py:117", "origin": "LL-01",
                                                     "what": "STATICFILES_DIRS unset; tailwind.css 404s",
                                                     "evidence": "run: about-stylesheet"}])
        self.assertEqual(ok, [])
        errs = self.errors(verdict="pass", inherited=[{"where": "config/settings.py:117", "what": "x"}])
        self.assertTrue(any("`origin`" in e for e in errs), errs)

    def test_a_handoff_or_another_role_is_not_checked(self):
        self.assertEqual(self.errors(verdict="changes-required", handoff=".migration/handoffs/T-1.md"), [])
        self.assertEqual(self.errors(role="afs-migrator", verdict="changes-required"), [])


class VerifierRulesTest(unittest.TestCase):
    """Phase 3e: the Verifier proves where each business rule is enforced (eval v3h, BK-05F)."""

    def setUp(self):
        import tempfile
        sys.path.insert(0, str(ROOT / "tools"))
        import validate
        self.validate = validate
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        self.mig = self.repo / ".migration"
        (self.mig / "plan").mkdir(parents=True)
        (self.mig / "returns").mkdir()
        (self.mig / "plan/booking.tickets.yaml").write_text(
            "slice: booking\ntickets:\n  - id: BK-05F\n    capabilities: [booking.routing-assign, booking.screen-route]\n")
        t = self.repo / "tests/booking/test_routing.py"
        t.parent.mkdir(parents=True)
        t.write_text("def test_assign_route_rejects_out_of_spec_itinerary():\n    pass\n")

    def tearDown(self):
        self.tmp.cleanup()

    TEST = "tests/booking/test_routing.py::test_assign_route_rejects_out_of_spec_itinerary"

    def errors(self, **doc):
        ret = {"role": "afs-verifier", "ticket": "BK-05F", "verdict": "pass", "findings": []}
        ret.update(doc)
        errs = []
        self.validate.check_verifier_rules(self.mig, self.mig / "returns/BK-05F.afs-verifier.yaml", ret, errs)
        return errs

    def rule(self, **kw):
        r = {"capability": "booking.routing-assign", "rule": "only an itinerary that satisfies the route "
             "specification is assigned", "use_case": "CargoRouting.assign_route", "test": self.TEST,
             "enforced": True}
        r.update(kw)
        return r

    def test_every_capability_is_covered(self):
        self.assertEqual(self.errors(rules=[self.rule()], no_rules={"booking.screen-route": "renders only"}), [])
        errs = self.errors(rules=[self.rule()])
        self.assertTrue(any("booking.screen-route" in e for e in errs), errs)

    def test_rules_are_required(self):
        errs = self.errors()
        self.assertTrue(any("list `rules`" in e for e in errs), errs)

    def test_an_unenforced_rule_needs_a_serious_finding_citing_its_test(self):
        # eval v3h BK-05F: the eligibility rule sat in the view.
        nr = {"booking.screen-route": "renders only"}
        errs = self.errors(rules=[self.rule(enforced=False)], no_rules=nr)
        self.assertTrue(any("isn't enforced" in e for e in errs), errs)
        ok = self.errors(verdict="changes-required", rules=[self.rule(enforced=False)], no_rules=nr,
                         findings=[{"severity": "major", "where": "views.py:36", "what": "eligibility in the view",
                                    "evidence": self.TEST}])
        self.assertEqual(ok, [])

    def test_the_test_must_exist(self):
        errs = self.errors(rules=[self.rule(test="tests/booking/test_routing.py::test_missing")],
                           no_rules={"booking.screen-route": "renders only"})
        self.assertTrue(any("isn't in the repository" in e for e in errs), errs)

    def test_the_migrator_proves_its_own_rules(self):
        # ADR-0045: no Verifier follows the Migrator, so its return carries the use-case tests itself.
        nr = {"booking.screen-route": "renders only"}
        errs = self.errors(role="afs-migrator")
        self.assertTrue(any("list `rules`" in e for e in errs), errs)
        self.assertEqual(self.errors(role="afs-migrator", rules=[self.rule()], no_rules=nr), [])

    def test_the_migrator_moves_an_unenforced_rule_instead_of_reporting_it(self):
        errs = self.errors(role="afs-migrator", rules=[self.rule(enforced=False)],
                           no_rules={"booking.screen-route": "renders only"},
                           findings=[{"severity": "major", "evidence": self.TEST}])
        self.assertTrue(any("move the rule into the use case" in e for e in errs), errs)

    def test_blocked_handoff_and_unplanned_tickets_are_not_checked(self):
        self.assertEqual(self.errors(verdict="blocked"), [])
        self.assertEqual(self.errors(handoff=".migration/handoffs/BK-05F.md"), [])
        self.assertEqual(self.errors(ticket="HR-04A"), [])


class LedgerRulesTest(unittest.TestCase):
    """Phase 3e: the Migrator records business rules in the ledger; the Verifier covers each (eval v3i, BK-05F)."""

    def setUp(self):
        import tempfile
        sys.path.insert(0, str(ROOT / "tools"))
        import validate
        self.validate = validate
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        self.mig = self.repo / ".migration"
        for d in ("plan", "returns", "ledger"):
            (self.mig / d).mkdir(parents=True)
        (self.mig / "plan/booking.tickets.yaml").write_text(
            "slice: booking\ntickets:\n  - id: BK-05F\n    capabilities: [booking.routing-assign, booking.screen-route]\n")
        t = self.repo / "tests/booking/test_routing.py"
        t.parent.mkdir(parents=True)
        t.write_text("def test_assign_route_rejects_out_of_spec_itinerary():\n    pass\n")

    def tearDown(self):
        self.tmp.cleanup()

    def ledger(self, cap, **extra):
        import yaml
        (self.mig / "ledger" / f"{cap}.yaml").write_text(yaml.safe_dump({"id": cap, **extra}))

    def run_check(self, fn, **doc):
        errs = []
        getattr(self.validate, fn)(self.mig, self.mig / "returns/BK-05F.x.yaml", doc, errs)
        return errs

    def test_the_migrator_records_rules_or_says_why_not(self):
        self.ledger("booking.routing-assign")
        self.ledger("booking.screen-route", no_rules="renders the route only")
        errs = self.run_check("check_migrator_ledger_rules", role="afs-migrator", ticket="BK-05F")
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("booking.routing-assign", errs[0])
        self.ledger("booking.routing-assign", rules=[{"id": "satisfies-spec", "rule": "the itinerary satisfies "
                                                      "the route specification"}])
        self.assertEqual(self.run_check("check_migrator_ledger_rules", role="afs-migrator", ticket="BK-05F"), [])
        self.assertEqual(self.run_check("check_migrator_ledger_rules", role="afs-migrator", ticket="BK-05F",
                                        handoff=".migration/handoffs/BK-05F.md"), [])

    def test_the_verifier_covers_every_ledger_rule(self):
        self.ledger("booking.routing-assign", rules=[{"id": "satisfies-spec", "rule": "the itinerary satisfies "
                                                      "the route specification"}])
        self.ledger("booking.screen-route", no_rules="renders the route only")
        test = "tests/booking/test_routing.py::test_assign_route_rejects_out_of_spec_itinerary"
        other = {"capability": "booking.routing-assign", "rule": "unknown tracking ID is refused",
                 "use_case": "CargoRouting.assign_route", "test": test, "enforced": True}
        doc = {"role": "afs-verifier", "ticket": "BK-05F", "verdict": "pass", "findings": [],
               "rules": [other], "no_rules": {"booking.screen-route": "renders only"}}
        errs = self.run_check("check_verifier_rules", **doc)
        self.assertTrue(any("satisfies-spec" in e for e in errs), errs)
        covered = dict(other, rule="the itinerary satisfies the route specification", enforced=False,
                       ledger_rule="satisfies-spec")
        doc.update(verdict="changes-required", rules=[other, covered],
                   findings=[{"severity": "major", "where": "views.py:36", "what": "spec checked in the view",
                              "evidence": test}])
        self.assertEqual(self.run_check("check_verifier_rules", **doc), [])

    def test_the_ledger_schema_takes_rules(self):
        import json

        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "schemas/ledger-entry.schema.json").read_text())
        props = Draft202012Validator(schema["properties"]["rules"])
        props.validate([{"id": "satisfies-spec", "rule": "x", "source": "plan"}])
        self.assertFalse(props.is_valid([{"id": "Bad Id", "rule": "x"}]))


if __name__ == "__main__":
    unittest.main()


class MutationBaseTest(unittest.TestCase):
    """A hardcoded --changed-since defeats CI's $AFS_BASE (eval 4f: pilot Gates mutated the whole codebase)."""

    def errs(self, cmd):
        out = []
        validate_mod.check_mutation_base("profile.yaml", {"gates": {"mutation_changed": [cmd]}}, out)
        return out

    def test_a_hardcoded_base_is_rejected(self):
        self.assertTrue(self.errs("python .migration/harness/tools/afs-mutation --changed-since origin/main"))
        self.assertEqual(self.errs("python .migration/harness/tools/afs-mutation"), [])
