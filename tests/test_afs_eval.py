"""tools/afs-eval: case validation, issue rewriting, grading rubric and run comparison (ADR-0041)."""
import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("afs_eval", str(ROOT / "tools/afs-eval"))
spec = importlib.util.spec_from_loader("afs_eval", loader)
ev = importlib.util.module_from_spec(spec)
loader.exec_module(ev)

SHA = "a" * 40


def case(**over):
    c = {"id": "x-01", "kind": "migrator", "agent": "afs-migrator", "ticket": "X-01", "role": "afs-migrator",
         "source": {"repo": "o/r", "base": SHA}, "issue": {"title": "t", "body": "b"}, "expect": {"gates": "success"}}
    c.update(over)
    return c


class CaseTest(unittest.TestCase):
    def test_a_complete_migrator_case_is_valid(self):
        self.assertEqual(ev.case_problems(case()), [])

    def test_a_verifier_case_needs_the_work_commit_and_a_known_verdict(self):
        problems = ev.case_problems(case(kind="verifier", expect={"verdict": "maybe"}))
        self.assertTrue(any("source.work" in p for p in problems))
        self.assertTrue(any("expect.verdict" in p for p in problems))

    def test_expected_findings_need_a_severity_and_something_to_match(self):
        c = case(kind="verifier", source={"repo": "o/r", "base": SHA, "work": SHA},
                 expect={"verdict": "changes-required", "findings": [{"severity_min": "huge"}]})
        problems = ev.case_problems(c)
        self.assertTrue(any("severity_min" in p for p in problems))
        self.assertTrue(any("any_of" in p for p in problems))

    def test_ids_name_branches_and_shas_are_full(self):
        problems = ev.case_problems(case(id="Bad Id", source={"repo": "o/r", "base": "abc"}))
        self.assertTrue(any("id:" in p for p in problems))
        self.assertTrue(any("40-character" in p for p in problems))

    def test_load_cases_rejects_duplicates_and_unknown_selections(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("a", "b"):
                pathlib.Path(d, f"{name}.yaml").write_text(yaml.safe_dump(case()))
            with self.assertRaisesRegex(ev.CaseError, "duplicate"):
                ev.load_cases(d)
            pathlib.Path(d, "b.yaml").write_text(yaml.safe_dump(case(id="x-02")))
            self.assertEqual([c["id"] for c in ev.load_cases(d, ["x-02"])], ["x-02"])
            with self.assertRaisesRegex(ev.CaseError, "no such case"):
                ev.load_cases(d, ["nope"])

    def test_a_disabled_case_is_listed_but_never_run(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "a.yaml").write_text(yaml.safe_dump(case()))
            pathlib.Path(d, "b.yaml").write_text(yaml.safe_dump(case(id="x-02", disabled="base invalid")))
            self.assertEqual([c["id"] for c in ev.load_cases(d)], ["x-01"])
            self.assertEqual(len(ev.load_cases(d, include_disabled=True)), 2)

    def test_the_shipped_cases_are_valid(self):
        cases = ev.load_cases(ROOT / "evals/cases")
        self.assertGreaterEqual(len(cases), 10, "the guidance's minimum is ten golden cases")
        kinds = {c["kind"] for c in cases}
        self.assertTrue({"migrator", "verifier"} <= kinds)
        self.assertTrue(any(c["kind"] == "verifier" and c["expect"]["verdict"] == "pass" for c in cases),
                        "clean Verifier cases keep a folded topology from passing by rejecting everything")


class BranchTest(unittest.TestCase):
    def test_a_work_branch_is_a_sibling_never_nested_under_the_case_branch(self):
        c = case()
        base, work = ev.branch("r1", c), ev.branch("r1", c, "work")
        self.assertFalse(work.startswith(base + "/"), "git can't hold refs X and X/Y together")
        self.assertEqual(work, "eval/r1/x-01-work")


class NormalizeTest(unittest.TestCase):
    def test_yaml_set_adds_a_nested_key_once(self):
        with tempfile.TemporaryDirectory() as d:
            prof = pathlib.Path(d, ".migration/profile.yaml")
            prof.parent.mkdir()
            prof.write_text(yaml.safe_dump({"target": {"repo": "o/r"}}))
            op = {"yaml_set": {"file": ".migration/profile.yaml", "key": "target.shared_test_files",
                               "value": ["tests/conftest.py"]}}
            self.assertEqual(len(ev.apply_normalize(d, [op], None)), 1)
            self.assertEqual(yaml.safe_load(prof.read_text())["target"],
                             {"repo": "o/r", "shared_test_files": ["tests/conftest.py"]})
            self.assertEqual(ev.apply_normalize(d, [op], None), [], "already set: no change")


class IssueTest(unittest.TestCase):
    def test_bare_references_point_at_the_source_repo_and_the_work_pr_is_filled_in(self):
        body = "Verify {work_pr}. See #89, o/x#3 and [#4](u). Rule #1 stays."
        out = ev.rewrite_body(body, "own/src", work_pr=12)
        self.assertIn("Verify #12.", out)
        self.assertIn("own/src#89", out)
        self.assertIn("o/x#3", out)
        self.assertNotIn("own/srco/x", out)
        self.assertIn("[#4](u)", out)


class GradeTest(unittest.TestCase):
    def test_a_defect_case_passes_only_when_a_serious_matching_finding_is_reported(self):
        expect = {"verdict": "changes-required",
                  "findings": [{"severity_min": "major", "any_of": ["change log"], "label": "logs"}]}
        caught = {"verdict": "changes-required",
                  "findings": [{"severity": "major", "where": "a.py:1", "what": "Omits the Change Log entry"}]}
        self.assertTrue(ev.verdict(ev.grade_verifier(caught, expect)))
        too_mild = {"verdict": "changes-required",
                    "findings": [{"severity": "minor", "what": "change log missing"}]}
        self.assertFalse(ev.verdict(ev.grade_verifier(too_mild, expect)))
        missed = {"verdict": "pass", "findings": []}
        self.assertFalse(ev.verdict(ev.grade_verifier(missed, expect)))

    def test_a_where_prefix_also_identifies_the_defect(self):
        expect = {"verdict": "changes-required", "findings": [{"severity_min": "major", "where": "src/views"}]}
        ret = {"verdict": "changes-required", "findings": [{"severity": "blocker", "where": "src/views.py:9",
                                                            "what": "x"}]}
        self.assertTrue(ev.verdict(ev.grade_verifier(ret, expect)))

    def test_a_clean_case_fails_on_a_serious_finding_even_with_a_pass_verdict(self):
        expect = {"verdict": "pass"}
        self.assertTrue(ev.verdict(ev.grade_verifier({"verdict": "pass", "findings": [
            {"severity": "minor", "what": "nit"}]}, expect)))
        self.assertFalse(ev.verdict(ev.grade_verifier({"verdict": "pass", "findings": [
            {"severity": "major", "what": "invented"}]}, expect)))

    def test_a_case_may_accept_several_verdicts(self):
        expect = {"verdict": ["blocked", "changes-required"],
                  "findings": [{"severity_min": "major", "any_of": ["timed out"]}]}
        for v in ("blocked", "changes-required"):
            ret = {"verdict": v, "findings": [{"severity": "blocker", "what": "Full suite timed out"}]}
            self.assertTrue(ev.verdict(ev.grade_verifier(ret, expect)))
        self.assertFalse(ev.verdict(ev.grade_verifier({"verdict": "pass", "findings": [
            {"severity": "major", "what": "timed out"}]}, expect)))

    def test_a_missing_return_fails_every_verifier_check(self):
        self.assertFalse(ev.verdict(ev.grade_verifier(None, {"verdict": "pass"})))

    def test_migrator_needs_green_gates_and_the_mutation_threshold(self):
        ok = {"gates": {"mutation_changed": 0.82}}
        self.assertTrue(ev.verdict(ev.grade_migrator(ok, "success", 0.8)))
        self.assertFalse(ev.verdict(ev.grade_migrator(ok, "failure", 0.8)))
        self.assertFalse(ev.verdict(ev.grade_migrator({"gates": {"mutation_changed": 0.7}}, "success", 0.8)))
        self.assertFalse(ev.verdict(ev.grade_migrator({"gates": {}}, "success", 0.8)))
        na = {"gates": {"mutation_changed": "n/a: no mutable code changed"}}
        self.assertTrue(ev.verdict(ev.grade_migrator(na, "success", 0.8)))
        self.assertFalse(ev.verdict(ev.grade_migrator(na, "failure", 0.8)), "only with a green Gates")
        self.assertFalse(ev.verdict(ev.grade_migrator({"gates": {"mutation_changed": "n/a: runner failed"}},
                                                      "success", 0.8)))

    def test_bootstrap_fields_are_compared_by_file_and_key(self):
        files = {"p.yaml": {"source": {"path": "legacy"}}, "c.yaml": {"characterization": {"tier": "B"}}}
        checks = ev.grade_fields(files, {"fields": {"p.yaml:source.path": "legacy",
                                                    "c.yaml:characterization.tier": "A"}})
        self.assertEqual([ok for _, ok, _ in checks], [False, True])

    def test_only_errors_the_agent_added_count(self):
        self.assertEqual(ev.new_errors(["old"], ["old", "new"]), ["new"])
        self.assertEqual(ev.new_errors(["old", "gone"], ["old"]), [])


class ReportTest(unittest.TestCase):
    def results(self, run, passed):
        return {"run": run, "cases": {c: {"kind": "migrator", "must_pass": m, "passed": p, "status": "graded",
                                          "checks": [], "skills": {"tdd": 1}}
                                      for c, (p, m) in passed.items()}}

    def test_flips_name_the_cases_that_changed_and_must_pass_regressions_fail(self):
        base = self.results("b", {"a": (True, True), "b": (False, True), "c": (True, False)})
        new = self.results("n", {"a": (False, True), "b": (True, True), "c": (False, False)})
        self.assertEqual(ev.flips(new, base), [("a", "pass → fail", True), ("b", "fail → pass", True),
                                               ("c", "pass → fail", False)])
        self.assertEqual(ev.must_pass_regressions(new, base), ["a"])
        text = ev.report(new, base)
        self.assertIn("`a`: pass → fail **(must pass)**", text)
        self.assertIn("`tdd`: 3", text)

    def test_skills_by_agent_sums_loads_from_cost_records(self):
        recs = [{"agent": "afs-migrator", "skills_invoked": [{"skill": "tdd", "count": 2}]},
                {"agent": "afs-migrator", "skills_invoked": [{"skill": "tdd", "count": 1}]},
                {"skills_invoked": []}]
        self.assertEqual(ev.skills_by_agent(recs), {"afs-migrator": {"tdd": 3}, "unknown": {}})


if __name__ == "__main__":
    unittest.main()
