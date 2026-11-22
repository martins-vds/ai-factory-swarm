"""tools/afs-eval: case validation, issue rewriting, grading rubric and run comparison (ADR-0041)."""
import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

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


class RoleMapTest(unittest.TestCase):
    def test_a_folded_role_is_dispatched_and_graded_as_its_successor_without_touching_the_case(self):
        c = case(agent="afs-specialist-migrator", role="afs-specialist-migrator",
                 issue={"title": "t", "body": "**Role:** `afs-specialist-migrator`, `specialty: data`."})
        m = ev.mapped(c, {"afs-specialist-migrator": "afs-migrator"})
        self.assertEqual((m["agent"], m["role"]), ("afs-migrator", "afs-migrator"))
        self.assertIn("`afs-migrator`, `specialty: data`", m["issue"]["body"])
        self.assertEqual(c["agent"], "afs-specialist-migrator", "the case itself is unchanged")


class ReplanTest(unittest.TestCase):
    def test_only_open_tickets_of_a_folded_role_are_re_planned(self):
        with tempfile.TemporaryDirectory() as d:
            plan = pathlib.Path(d, ".migration/plan"); plan.mkdir(parents=True)
            (pathlib.Path(d, ".migration/returns")).mkdir()
            pathlib.Path(d, ".migration/returns/BK-01.afs-specialist-migrator.yaml").write_text("role: x\n")
            (plan / "booking.tickets.yaml").write_text(yaml.safe_dump({"slice": "booking", "tickets": [
                {"id": "BK-01", "role": "afs-specialist-migrator"}, {"id": "BK-02", "role": "afs-specialist-migrator"},
                {"id": "BK-03", "role": "afs-migrator"}]}))
            notes = ev.replan_open_tickets(d, {"afs-specialist-migrator": "afs-migrator"})
            roles = {t["id"]: t["role"] for t in yaml.safe_load((plan / "booking.tickets.yaml").read_text())["tickets"]}
            self.assertEqual(roles, {"BK-01": "afs-specialist-migrator", "BK-02": "afs-migrator", "BK-03": "afs-migrator"})
            self.assertEqual(len(notes), 1)
            self.assertEqual(ev.replan_open_tickets(d, {}), [])


def _run(name, rows):
    return {"run": name, "cases": {cid: dict(r) for cid, r in rows.items()}}


class CompareTest(unittest.TestCase):
    """Majority comparison with usage (adapted from the single-agent-loop kit's compare.py)."""

    def test_a_baseline_majority_pass_that_fails_now_breaks_the_change(self):
        u = {"requests": 100, "output_tokens": 5000, "minutes": 20.0}
        base = [_run(f"b{i}", {"a": {"passed": True, "usage": u}, "b": {"passed": i == 0}}) for i in range(3)]
        now = [_run(f"n{i}", {"a": {"passed": i == 0, "usage": dict(u, requests=80)}, "b": {"passed": True}})
               for i in range(3)]
        text, broken = ev.compare(now, base)
        self.assertEqual(broken, ["a"])
        self.assertIn("does not hold", text)
        self.assertIn("80 (-20%)", text)
        self.assertIn("fail → pass", text)

    def test_the_change_holds_when_no_majority_pass_is_lost(self):
        base = [_run("b", {"a": {"passed": False}})]
        now = [_run("n", {"a": {"passed": True}}), _run("n2", {"a": {"passed": False}})]
        text, broken = ev.compare(now, base)
        self.assertEqual(broken, [])       # 1 of 2 isn't a majority, and the baseline failed anyway
        self.assertIn("the change holds", text)

    def test_runs_that_never_tested_the_case_do_not_count(self):
        """A session that started without its tools, or a case another run file covers, isn't a run (ADR-0054)."""
        base = [_run("b", {"a": {"passed": True}})]
        now = [_run("n", {"a": {"passed": False, "status": "setup-failure"}}),
               _run("n2", {"a": {"passed": False, "status": "not-dispatched"}}),
               _run("n3", {"a": {"passed": True, "status": "graded"}})]
        text, broken = ev.compare(now, base)
        self.assertEqual(broken, [])
        self.assertIn("1/1 pass", text)


class SetupFailureTest(unittest.TestCase):
    def test_a_failed_target_setup_step_is_named_and_copilot_steps_are_not(self):
        steps = [{"name": "Set up job", "conclusion": "failure"},
                 {"name": "Starting User Configured Setup Step (Linux)", "conclusion": "failure"},
                 {"name": "Install RTK 1.1.0 (x.tar.gz)", "conclusion": "failure"}]
        replies = {"runs?": {"workflow_runs": [{"id": 2, "created_at": "b"}, {"id": 1, "created_at": "a"}]},
                   "runs/1/jobs": {"jobs": [{"steps": steps}]}, "runs/2/jobs": {"jobs": []}}
        fake = lambda path: next(v for k, v in replies.items() if k in path)  # noqa: E731
        with mock.patch.object(ev, "gh_api", fake):
            self.assertEqual(ev.setup_failure("o/r", "copilot/x"), "Install RTK 1.1.0 (x.tar.gz)")
        steps[2]["conclusion"] = "success"
        with mock.patch.object(ev, "gh_api", fake):
            self.assertIsNone(ev.setup_failure("o/r", "copilot/x"))


class UsageTest(unittest.TestCase):
    def test_usage_sums_requests_tokens_and_minutes(self):
        recs = [{"models": {"m": {"requests": 3, "output": 100}}, "started_at": "2026-11-17T01:00:00Z",
                 "ended_at": "2026-11-17T01:30:00.000Z"},
                {"models": {"m": {"requests": 2, "output": 50}, "n": {"requests": 1, "output": 5}}}]
        self.assertEqual(ev.session_usage(recs),
                         {"sessions": 2, "requests": 6, "output_tokens": 155, "minutes": 30.0})


class CoverageTest(unittest.TestCase):
    def test_role_chains_from_returns_and_roles_without_a_case(self):
        with tempfile.TemporaryDirectory() as d:
            r = pathlib.Path(d, ".migration/returns"); r.mkdir(parents=True)
            for name in ("BK-01.afs-specialist-migrator", "BK-01.afs-verifier", "BK-02.afs-migrator",
                         "booking.afs-analyst"):
                (r / f"{name}.yaml").write_text("x: 1\n")
            cases = [{"id": "c", "role": "afs-migrator"}, {"id": "v", "role": "afs-verifier"}]
            text, no_case = ev.coverage(cases, [d], {"afs-specialist-migrator": "afs-migrator"})
            self.assertEqual(no_case, ["afs-analyst"])
            self.assertIn("| 1 | afs-migrator, afs-verifier | — |", text)


class CouplingTest(unittest.TestCase):
    """Which roles run one after another (adapted from the single-agent-loop kit's coupling_map.py)."""

    def test_pairs_that_always_follow_are_merge_candidates(self):
        traces = {"BK": ["afs-analyst", "afs-characterizer", "afs-planner"],
                  "DM": ["afs-analyst", "afs-characterizer", "afs-planner", "afs-migrator"],
                  "HR": ["afs-analyst", "afs-planner"], "TC": ["afs-auditor"]}
        text, candidates = ev.coupling(traces, min_coupling=0.8, min_share=0.4)
        self.assertIn(("afs-analyst", "afs-characterizer"), candidates)
        self.assertIn(("afs-characterizer", "afs-planner"), candidates)
        self.assertNotIn(("afs-planner", "afs-migrator"), candidates)   # 1 of 4 traces: below min_share
        self.assertIn("| afs-analyst | 3 | 75% |", text)

    def test_traces_follow_the_order_returns_were_first_committed(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@e", *a],
                               check=True, capture_output=True)
            git("init", "-q")
            r = pathlib.Path(d, ".migration/returns"); r.mkdir(parents=True)
            for i, name in enumerate(["BK-03.afs-characterizer", "BK-02.afs-analyst",
                                      "BK-05A.afs-specialist-migrator", "BK-05A.afs-verifier"]):
                (r / f"{name}.yaml").write_text("x: 1\n")
                git("add", "-A")
                git("commit", "-q", "-m", name, "--date", f"2026-11-0{i + 1}T00:00:00Z")
                subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q",
                                "--amend", "--no-edit"], env={**__import__("os").environ,
                                "GIT_COMMITTER_DATE": f"2026-11-0{i + 1}T00:00:00Z"}, check=True)
            traces = ev.role_traces(d, "slice", {"afs-specialist-migrator": "afs-migrator"})
            self.assertEqual(traces, {"BK": ["afs-characterizer", "afs-analyst", "afs-migrator", "afs-verifier"]})


class WorkCheckTest(unittest.TestCase):
    def test_a_migrator_must_change_more_than_migration_state(self):
        # m3j: BK-05F r1/r2 changed only their return and passed on the base's work.
        self.assertFalse(ev.work_check([".migration/returns/BK-05F.afs-migrator.yaml"])[1])
        self.assertTrue(ev.work_check([".migration/returns/X.yaml", "src/a.py"])[1])


class OracleTest(unittest.TestCase):
    def test_forbidden_calls_find_a_rule_in_a_web_adapter(self):
        # Phase 4a: BK-05F's route-specification check in the view is the defect the oracle looks for.
        with tempfile.TemporaryDirectory() as d:
            view = pathlib.Path(d, "src/cargotracker/booking/interfaces/route_selection/views.py")
            view.parent.mkdir(parents=True)
            view.write_text("def post(cargo, it):\n    if not cargo.route_specification.is_satisfied_by(it):\n"
                            "        return 400\n")
            use_case = pathlib.Path(d, "src/cargotracker/booking/application/routing.py")
            use_case.parent.mkdir(parents=True)
            use_case.write_text("def assign(spec, it):\n    return spec.is_satisfied_by(it)\n")
            spec = [{"files": ["src/cargotracker/*/interfaces/**/*.py"], "call": "is_satisfied_by", "why": "w"}]
            found = ev.forbidden_calls(d, spec)
        self.assertEqual([(p, n) for p, n, _ in found],
                         [("src/cargotracker/booking/interfaces/route_selection/views.py", 2)])

    def test_stripped_args_find_a_stored_strip_but_not_a_blank_check(self):
        # Phase 4a: LL-02 A r2 stored stripped member and ISBN values; the legacy stores them as given.
        with tempfile.TemporaryDirectory() as d:
            svc = pathlib.Path(d, "src/loans/services.py")
            svc.parent.mkdir(parents=True)
            svc.write_text("def a(repo, member, isbn):\n    if not member.strip():\n        raise ValueError\n"
                           "    return repo.lend(member, isbn)\n"
                           "def b(repo, member, isbn):\n    return repo.lend(member.strip(), isbn)\n"
                           "def c(repo, member, isbn):\n    m = member.strip()\n    return repo.lend(member=m, isbn=isbn)\n")
            spec = [{"files": ["src/loans/**/*.py"], "calls": ["lend"], "why": "w"}]
            found = ev.stripped_args(d, spec)
        self.assertEqual([n for _, n, _ in found], [6, 9])

    def test_stripped_args_find_a_model_form_that_strips(self):
        # The live LL-02 and A r2 lend through a ModelForm, whose generated CharFields strip by default.
        with tempfile.TemporaryDirectory() as d:
            forms = pathlib.Path(d, "src/loans/forms.py")
            forms.parent.mkdir(parents=True)
            pathlib.Path(d, "src/loans/models.py").write_text(
                "from django.db import models\nclass Loan(models.Model):\n    member = models.CharField()\n")
            forms.write_text("from django import forms\n"
                             "class A(forms.ModelForm):\n    class Meta:\n        fields = ('member', 'isbn')\n"
                             "class B(forms.Form):\n    member = forms.CharField(strip=False)\n"
                             "    isbn = forms.CharField()\n")
            spec = [{"files": ["src/loans/**/*.py"], "calls": ["lend"], "fields": ["member", "isbn"], "why": "w"}]
            found = ev.stripped_args(d, spec)
        self.assertEqual([(p, n) for p, n, _ in found], [("src/loans/forms.py", 4)] * 2 + [("src/loans/forms.py", 7)])

    def test_chain_body_names_the_ticket_and_pr(self):
        body = ev.CHAIN_BODY.format(ticket="BK-05F", pr=1186)
        self.assertIn("PR #1186", body)
        self.assertIn("BK-05F.afs-verifier.yaml", body)


class RetiredRoleTest(unittest.TestCase):
    def test_prepare_always_re_plans_retired_roles(self):
        # v3e-r1: pilot Verifier cases prepared without --role-map started with open specialist tickets.
        import argparse
        self.assertEqual(ev.prepare_role_map(argparse.Namespace(role_map=None)),
                         {"afs-specialist-migrator": "afs-migrator", "afs-bootstrapper": "afs-program-orchestrator",
                          "afs-slice-coordinator": "afs-program-orchestrator"})
        self.assertEqual(ev.prepare_role_map(argparse.Namespace(role_map=["a=b"]))["a"], "b")


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

    def test_a_verifier_blocked_on_a_gate_is_reported_apart(self):
        # Phase 3e: an interrupted gate run blocks, and the eval reports it apart from a wrong verdict.
        ret = {"verdict": "blocked", "blocked_reason": "mutation_changed: interrupted at 40 of 120"}
        self.assertEqual(ev.blocked_gate(ret, {"verdict": "pass"}), ret["blocked_reason"])
        self.assertIsNone(ev.blocked_gate(ret, {"verdict": ["changes-required", "blocked"]}))
        self.assertIsNone(ev.blocked_gate({"verdict": "blocked"}, {"verdict": "pass"}))
        self.assertIsNone(ev.blocked_gate({"verdict": "changes-required"}, {"verdict": "pass"}))

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

    def test_harness_copy_places_the_agent_and_skills_a_bootstrap_case_needs(self):
        with tempfile.TemporaryDirectory() as h, tempfile.TemporaryDirectory() as t:
            pathlib.Path(h, "skills/afs-bootstrap").mkdir(parents=True)
            pathlib.Path(h, "skills/afs-bootstrap/SKILL.md").write_text("x")
            pathlib.Path(h, "agents").mkdir()
            pathlib.Path(h, "agents/a.agent.md").write_text("y")
            notes = ev.harness_copy(t, h, [{"from": "skills/afs-bootstrap", "to": ".github/skills/afs-bootstrap"},
                                           {"from": "agents/a.agent.md", "to": ".github/agents/a.agent.md"}])
            self.assertEqual(pathlib.Path(t, ".github/skills/afs-bootstrap/SKILL.md").read_text(), "x")
            self.assertEqual(pathlib.Path(t, ".github/agents/a.agent.md").read_text(), "y")
            self.assertEqual(len(notes), 2)

    def test_bootstrap_fields_are_compared_by_file_and_key(self):
        files = {"p.yaml": {"source": {"path": "legacy"}}, "c.yaml": {"characterization": {"tier": "B"}}}
        checks = ev.grade_fields(files, {"fields": {"p.yaml:source.path": "legacy",
                                                    "c.yaml:characterization.tier": "A"}})
        self.assertEqual([ok for _, ok, _ in checks], [False, True])
        self.assertTrue(ev.verdict(ev.grade_fields({"p.yaml": {"source": {"path": "legacy/"}}},
                                                   {"fields": {"p.yaml:source.path": "legacy"}})))

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


class UnderstandGradeTest(unittest.TestCase):
    """Phase 4b: the golden ledger and the characterization's golden values, read from the changed files."""

    def test_rules_and_values_are_found_in_the_changed_files(self):
        with tempfile.TemporaryDirectory() as h:
            led = pathlib.Path(h, ".migration/ledger/billing.total.yaml")
            led.parent.mkdir(parents=True)
            led.write_text("rules:\n- Late fees are capped at 25.00 a month\n- tax 5% rounded HALF_UP once\n")
            ch = pathlib.Path(h, ".migration/characterization/billing/cases.yaml")
            ch.parent.mkdir(parents=True)
            ch.write_text("- observed: 8.14\n- observed: 0.53\n")
            expect = {"ledger_rules": [{"id": "cap", "all_of": [["25.00"], ["cap"]]},
                                       {"id": "tax", "all_of": [["5%"], ["half_up", "half-up"]]},
                                       {"id": "card", "all_of": [["vault"]]}],
                      "characterization_values": ["8.14", "0.53", "29.40"], "min_ledger": 2,
                      "min_characterization": 2}
            checks, metrics = ev.grade_understand(None, h, expect, [
                ".migration/ledger/billing.total.yaml", ".migration/characterization/billing/cases.yaml"])
        self.assertTrue(all(ok for _, ok, _ in checks), checks)
        self.assertEqual(metrics["ledger_missing"], ["card"])
        self.assertEqual(metrics["characterization_found"], 2)


class AcceptanceGradeTest(unittest.TestCase):
    """ADR-0050 fold eval: a slice acceptance graded the same whether the orchestrator or the retired
    Slice Coordinator wrote it."""

    EXPECT = {"slice": "library-info", "epic": 64, "reconciliation_issues": [65, 122, 127], "self_issue": 127,
              "mutation_score": 0.976, "report_keywords": [["42938753426"], ["0.976"], ["/about"]]}

    def tree(self, h, report="Run 42938753426: mutation 0.976. Compare /about side by side.\n", issues=None):
        rep = pathlib.Path(h, ".migration/evidence/library-info/acceptance.md")
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(report)
        rec = pathlib.Path(h, ".migration/evidence/ticket-reconciliation/64.yaml")
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text(yaml.safe_dump({"epic": 64, "issues": issues if issues is not None else [
            {"number": 65, "disposition": "completed"}, {"number": 122, "disposition": "completed"},
            {"number": 127, "disposition": "completed"}]}))

    ORCH = {"role": "afs-program-orchestrator", "ticket": "LI-ACCEPT", "acceptance": {
        "slice": "library-info", "report": ".migration/evidence/library-info/acceptance.md", "gates": "all-green",
        "mutation_score": 0.976, "human_check": "requested"}}
    COORD = {"role": "afs-slice-coordinator", "ticket": "LI-ACCEPT", "slice": "library-info",
             "acceptance": {"report": ".migration/evidence/library-info/acceptance.md", "gates": "all-green",
                            "mutation_score": "n/a: not re-run; see the archive"}, "human_check": "requested"}

    def test_both_return_shapes_pass(self):
        for ret in (self.ORCH, self.COORD):
            with tempfile.TemporaryDirectory() as h:
                self.tree(h)
                checks = ev.grade_acceptance(h, ret, self.EXPECT, [".migration/returns/LI-ACCEPT.x.yaml"])
            self.assertTrue(all(ok for _, ok, _ in checks), (ret["role"], checks))

    def test_a_passed_human_check_a_wrong_score_and_a_missing_issue_fail(self):
        ret = json_copy(self.ORCH)
        ret["acceptance"].update(human_check="passed", mutation_score=0.92)
        with tempfile.TemporaryDirectory() as h:
            self.tree(h, issues=[{"number": 65, "disposition": "completed"},
                                 {"number": 127, "disposition": "completed", "needs_review": "x"}])
            failed = {c for c, ok, _ in ev.grade_acceptance(h, ret, self.EXPECT, ["src/views.py"]) if not ok}
        self.assertEqual(failed, {"human_check requested, not passed", "mutation_score is the run's 0.976",
                                  "changes only .migration/", "ticket reconciliation covers every descendant once"})

    def test_the_case_schema_needs_the_acceptance_expectations(self):
        problems = ev.case_problems(case(kind="acceptance", expect={"slice": "x"}))
        self.assertTrue(any("expect.epic" in p for p in problems), problems)


def json_copy(doc):
    return yaml.safe_load(yaml.safe_dump(doc))


class AgentDriftTest(unittest.TestCase):
    """ADR-0058: Copilot serves custom agents from the eval repo's main, so main must hold the harness's."""

    def test_missing_and_changed_agents_are_named_and_extra_ones_are_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            harness, repo = root / "h", root / "r"
            (harness / "agents").mkdir(parents=True)
            (harness / "evals/variants").mkdir(parents=True)
            (harness / "agents/afs-a.agent.md").write_text("A\n")
            (harness / "agents/afs-b.agent.md").write_text("B new\n")
            (harness / "evals/variants/afs-v.agent.md").write_text("V\n")
            (repo / ".github/agents").mkdir(parents=True)
            (repo / ".github/agents/afs-a.agent.md").write_text("A\n")
            (repo / ".github/agents/afs-b.agent.md").write_text("B old\n")
            (repo / ".github/agents/afs-retired.agent.md").write_text("R\n")
            ev.git(repo, "init", "-q", "-b", "main")
            ev.git(repo, "add", ".")
            ev.git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
            self.assertEqual(ev.agent_drift(repo, "main", harness), ["afs-b.agent.md", "afs-v.agent.md (missing)"])


class ModelPinTest(unittest.TestCase):
    """ADR-0060: Copilot's automatic model choice mixed two models into one run from 2026-11-20."""

    def test_the_assignment_carries_the_pinned_model_only_when_named(self):
        a = mock.Mock(eval_repo="o/e", model="gpt-6-luna", auto_model=False)
        self.assertEqual(ev.assignment(a, "b", "afs-migrator")["model"], "gpt-6-luna")
        a.model = None
        self.assertNotIn("model", ev.assignment(a, "b", "afs-migrator"))

    def test_dispatch_needs_a_model_or_an_explicit_auto(self):
        with self.assertRaises(SystemExit):
            ev.require_model(mock.Mock(model=None, auto_model=False))
        ev.require_model(mock.Mock(model=None, auto_model=True))
        ev.require_model(mock.Mock(model="gpt-6-luna", auto_model=False))

    def test_the_model_is_read_from_the_session_log(self):
        log = "[cca-engine] turn=3 assistant.usage: model=mai-code-2-flash input=1 output=2\n"
        self.assertEqual(ev.MODEL.findall(log), ["mai-code-2-flash"])

    def test_compare_flags_runs_on_different_models(self):
        def run(name, model):
            return {"run": name, "cases": {"c": {"status": "graded", "passed": True, "model": model}}}
        out = ev.compare([run("now", "mai-code-2-flash")], [run("base", "gpt-6-luna")])
        text = out if isinstance(out, str) else "\n".join(out if isinstance(out, list) else [str(out)])
        self.assertIn("More than one model ran", text)


class EvalEnvironmentTest(unittest.TestCase):
    def test_the_note_says_branch_names_are_the_live_runs(self):
        note = ev.eval_note("r", case(source={"repo": "o/p", "base": "0eadc0f669fee330d98b3e"}))
        self.assertIn("Branch and PR names in this issue are the live run's", note)
        self.assertIn("0eadc0f669fe", note)

    def test_a_rate_limited_setup_step_is_a_setup_failure(self):
        log = ("x GITHUB_COPILOT_SETUP_STEP_NAME: Fetch the newest data snapshot\n"
               "x ##[error]gh run list: HTTP 403: API rate limit exceeded for installation\n"
               "x [cca-engine] turn=1 assistant.turn_start\n")
        runs = {"workflow_runs": [{"id": 1, "created_at": "t"}]}
        jobs = {"jobs": [{"id": 2}]}
        with mock.patch.object(ev, "gh_api", side_effect=[runs, jobs]), \
                mock.patch.object(ev, "sh", return_value=mock.Mock(stdout=log)):
            self.assertEqual(ev.rate_limited_setup("o/e", "b"), "Fetch the newest data snapshot (API rate limit)")

    def test_a_rate_limit_inside_the_agents_session_does_not_count(self):
        log = "x [cca-engine] turn=1 start\nx tool: API rate limit exceeded\n"
        with mock.patch.object(ev, "gh_api", side_effect=[{"workflow_runs": [{"id": 1}]}, {"jobs": [{"id": 2}]}]), \
                mock.patch.object(ev, "sh", return_value=mock.Mock(stdout=log)):
            self.assertIsNone(ev.rate_limited_setup("o/e", "b"))


class SelfHealCaseTest(unittest.TestCase):
    def test_a_case_tree_with_the_finish_check_off_is_refused_unless_it_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            prof = pathlib.Path(d, ".migration/profile.yaml")
            prof.parent.mkdir()
            prof.write_text("self_heal: {enabled: false}\n")
            self.assertTrue(ev.self_heal_problems(d, case()))
            self.assertEqual(ev.self_heal_problems(d, case(self_heal="off")), [])
            prof.write_text("self_heal: {enabled: true, max_blocks: 2}\n")
            self.assertEqual(ev.self_heal_problems(d, case()), [])


class RefactorGradeTest(unittest.TestCase):
    """Test-trust plan, step 0.3: a restructuring is graded on being done; modified tests are measured."""

    EXPECT = {"must_exist": ["src/fees/presentation.py"], "must_not_define": {"src/fees/views.py": ["_fee_amount"]}}

    def test_done_restructuring_and_the_coupled_tests_it_needed(self):
        with tempfile.TemporaryDirectory() as h:
            pathlib.Path(h, "src/fees").mkdir(parents=True)
            pathlib.Path(h, "src/fees/presentation.py").write_text("def fee_amount(c):\n    return c\n")
            pathlib.Path(h, "src/fees/views.py").write_text("from .presentation import fee_amount\n")
            changes = [("A", "src/fees/presentation.py"), ("M", "src/fees/views.py"),
                       ("M", "tests/fees/test_views.py"), ("A", "tests/fees/test_presentation.py")]
            checks, metrics = ev.grade_refactor(h, changes, self.EXPECT)
        self.assertTrue(all(ok for _, ok, _ in checks), checks)
        self.assertEqual(metrics, {"tests_modified": ["tests/fees/test_views.py"],
                                   "tests_added": ["tests/fees/test_presentation.py"]})

    def test_an_unfinished_move_a_golden_edit_and_a_deleted_test_fail(self):
        with tempfile.TemporaryDirectory() as h:
            pathlib.Path(h, "src/fees").mkdir(parents=True)
            pathlib.Path(h, "src/fees/views.py").write_text("def _fee_amount(c):\n    return c\n")
            changes = [("M", ".migration/characterization/source/goldens/fees.json"), ("D", "tests/fees/test_x.py")]
            failed = {c for c, ok, _ in ev.grade_refactor(h, changes, self.EXPECT)[0] if not ok}
        self.assertEqual(failed, {"src/fees/presentation.py exists", "src/fees/views.py no longer defines _fee_amount",
                                  "characterization untouched", "no existing test deleted"})

    def test_yaml_append_adds_a_ticket_once(self):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t, "plan.tickets.yaml")
            p.write_text("slice: s\ntickets:\n- id: A\n")
            op = {"yaml_append": {"file": "plan.tickets.yaml", "key": "tickets", "value": {"id": "REF-01"}}}
            self.assertEqual(len(ev.apply_normalize(t, [op, op], None)), 1)
            self.assertEqual([x["id"] for x in yaml.safe_load(p.read_text())["tickets"]], ["A", "REF-01"])
