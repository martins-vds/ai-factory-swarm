"""tools/ticket_guard.py (ADR-0029): a ticket closed before its work reached the default branch is reopened."""
import pathlib
import sys
import unittest
import base64
import contextlib
import io
import os
import subprocess
import tempfile
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import ticket_guard  # noqa: E402
import check_slice_returns  # noqa: E402
import fog_rewalk  # noqa: E402
import validate  # noqa: E402


class TicketGuardTest(unittest.TestCase):
    def run_guard(self, issue, pulls):
        calls = []

        def gh(path, *args, data=None):
            calls.append((path, args, data))
            if path == "repos/o/r/issues/129":
                return issue if not args else {}
            if path == "repos/o/r":
                return {"default_branch": "main"}
            if path.startswith("repos/o/r/pulls?"):
                return pulls
            return {}
        orig, ticket_guard.gh = ticket_guard.gh, gh
        try:
            self.assertEqual(ticket_guard.main(["--repo", "o/r", "--issue", "129"]), 0)
        finally:
            ticket_guard.gh = orig
        return [c for c in calls if c[1][:2] == ("-X", "PATCH")]

    CLOSED = {"state": "closed", "state_reason": "completed"}

    def test_reopens_when_an_open_pr_into_main_still_fixes_it(self):
        reopened = self.run_guard(self.CLOSED, [{"number": 141, "state": "open", "body": "Work.\n\n- Fixes #129"}])
        self.assertEqual(reopened, [("repos/o/r/issues/129", ("-X", "PATCH"), {"state": "open"})])

    def test_leaves_it_closed_otherwise(self):
        self.assertEqual(self.run_guard(self.CLOSED, [{"number": 7, "state": "open", "body": "Fixes #1290"}]), [],
                         "another issue number")
        self.assertEqual(self.run_guard(self.CLOSED, [{"number": 7, "state": "open", "body": "Mentions #129"}]), [],
                         "a mention is not a fix")
        self.assertEqual(self.run_guard({"state": "closed", "state_reason": "not_planned"},
                                        [{"number": 141, "state": "open", "body": "Fixes #129"}]), [],
                         "closed as not planned")
        self.assertEqual(self.run_guard(self.CLOSED, []), [], "its work PR already merged")

    def test_closing_keywords(self):
        for body in ("fixes #129", "Closes: #129", "resolved o/r#129", "FIX #129"):
            self.assertTrue(ticket_guard.open_fixers([{"state": "open", "body": body}], 129), body)


class TicketReconciliationTest(unittest.TestCase):
    RETURN = """role: afs-verifier
ticket: T1
issue: o/r#1
pr: o/r#101
verdict: pass
gates: null
evidence_logs: []
findings: []
tests_added: []
ledger_issues: []
quirk_tickets: []
"""
    FAILED_RETURN = RETURN.replace("ticket: T1", "ticket: T3").replace("issue: o/r#1", "issue: o/r#3") \
        .replace("pr: o/r#101", "pr: o/r#103").replace("verdict: pass", "verdict: changes-required")
    REPORT = ".migration/evidence/ticket-reconciliation/99.yaml"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)
        self.git("init", "-q", "--initial-branch=fixture-base")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def write_report(self, issues):
        path = self.root / self.REPORT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"epic": 99, "scope": "slice-epic-descendants", "issues": issues}),
                        encoding="utf-8")

    def setup_completed_stack(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "work-pr")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        (returns / "T1.afs-verifier.yaml").write_text(self.RETURN, encoding="utf-8")
        (returns / "T2.afs-verifier.yaml").write_text(
            self.RETURN.replace("ticket: T1", "ticket: T2").replace("issue: o/r#1", "issue: o/r#2")
            .replace("pr: o/r#101", "pr: o/r#102"), encoding="utf-8")
        (self.root / "work.txt").write_text("accepted work\n", encoding="utf-8")
        head = self.commit("accepted work head")
        self.git("checkout", "-qb", "accepted-main", base)
        (self.root / "carrier.txt").write_text("carried by another PR\n", encoding="utf-8")
        self.git("add", "carrier.txt")
        self.git("commit", "-qm", "carrier changes")
        self.git("merge", "--no-ff", "work-pr", "-m", "carrier PR integration")
        main = self.git("rev-parse", "HEAD")
        self.write_report([
            {"number": 1, "disposition": "completed", "pull_requests": [101],
             "returns": [".migration/returns/T1.afs-verifier.yaml"]},
            {"number": 2, "disposition": "completed", "pull_requests": [101, 102],
             "returns": [".migration/returns/T2.afs-verifier.yaml"]},
        ])
        self.commit("reconciliation evidence")
        return head, main

    def children(self, issues):
        return {f"repos/o/r/issues/{number}/sub_issues?per_page=100&page=1": []
                for number in [99, *(i["number"] for i in issues)]}

    def run_reconciliation(self, issues, pulls, contents=None, *, report_exists=True, labels=None,
                           report_issues=None, issue_details=None):
        if report_exists:
            self.write_report(report_issues if report_issues is not None else issues)
            self.commit("reconciliation evidence")
        calls = []
        children = self.children(issues)

        def gh(endpoint, *args, data=None):
            calls.append((endpoint, args, data))
            if endpoint == "repos/o/r/issues/99":
                return {"number": 99, "state": "closed", "labels": [{"name": "afs:slice"}]}
            if endpoint.endswith("/comments") or args:
                return {}
            if endpoint in children:
                if endpoint.endswith("/99/sub_issues?per_page=100&page=1"):
                    return labels if labels is not None else [
                        {"number": i["number"], "title": f"T{i['number']}", "state": "closed",
                         "state_reason": "completed", "labels": []} for i in issues
                    ]
                return []
            if endpoint.startswith("repos/o/r/issues/") and "/sub_issues?" not in endpoint:
                number = int(endpoint.rsplit("/", 1)[1])
                if issue_details and number in issue_details:
                    return issue_details[number]
                if number == 4:
                    return {"number": number, "state": "closed", "state_reason": "completed", "title": f"T{number}"}
                return {"number": number, "state": "open", "title": f"T{number}"}
            if endpoint.startswith("repos/o/r/pulls/"):
                pull_number = int(endpoint.split("/")[4].split("?", 1)[0])
                if "/files?" in endpoint:
                    return pulls[pull_number].get("files", [])
                return pulls[pull_number]
            if endpoint.startswith("repos/o/r/contents/"):
                return contents[endpoint]
            return {}

        output = io.StringIO()
        with mock.patch.object(ticket_guard, "gh", side_effect=gh), \
                contextlib.redirect_stdout(output):
            result = ticket_guard.main(["--repo", "o/r", "--reconcile-epic", "99", "--reopen"])
        return result, output.getvalue(), calls

    def pull(self, number, *, head, merged=False, body=""):
        return {"number": number, "state": "closed", "merged_at": "2026-11-05T00:00:00Z" if merged else None,
                "merge_commit_sha": head if merged else None, "head": {"sha": head}, "body": body}

    def historical_null_pr_return(self, *, changed=False, rule=True, superseded=False):
        path = self.root / ".migration/returns/T1.afs-verifier.yaml"
        path.parent.mkdir(parents=True)
        doc = yaml.safe_load(self.RETURN)
        doc["pr"] = None
        doc["gates"] = {"build": 0, "behavior": 0, "idiom": 0, "crap": 15,
                        "mutation_changed": 0.855, "regression": 0}
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        installed_tools = self.root / ".migration/harness/tools"
        installed_tools.mkdir(parents=True)
        validator = installed_tools / "validate.py"
        validator.write_text("# Historical installed validator.\n", encoding="utf-8")
        owner = self.commit("historical completed return")
        if superseded:
            doc["issue"] = "o/r#2"
            path.write_text(yaml.safe_dump(doc), encoding="utf-8")
            owner = self.commit("historical sibling re-verification")
        if rule:
            validator.write_text('PR_ATTRIBUTION_RULE_V1 = "PR_ATTRIBUTION_RULE_V1"\n', encoding="utf-8")
            self.commit("introduce existing PR attribution rule")
        if changed:
            path.write_text(path.read_text(encoding="utf-8") + "# Later edit.\n", encoding="utf-8")
            self.commit("edit return after rule")
        issue = {"number": 1, "disposition": "completed", "pull_requests": [101],
                 "returns": [path.relative_to(self.root).as_posix()]}
        with mock.patch.object(validate, "HERE", installed_tools):
            self.assertEqual(validate.pre_rule_null_pr(path, self.root / ".migration"), rule and not changed)
            return self.run_reconciliation(
                [issue], {101: self.pull(101, head=owner, merged=True)},
                issue_details={
                    1: {"number": 1, "parent_issue_url": "https://api.github.com/repos/o/r/issues/99"},
                    2: {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/99"},
                },
            )

    def test_superseded_unchanged_null_pr_return_retains_historical_exemption(self):
        result, output, _ = self.historical_null_pr_return(superseded=True)
        self.assertEqual(result, 0, output)
        self.assertIn("superseded attribution", output)
        self.assertIn("unchanged pre-rule null-PR return", output)

    def test_superseded_null_pr_return_edited_after_rule_requires_owning_pr(self):
        result, output, _ = self.historical_null_pr_return(superseded=True, changed=True)
        self.assertEqual(result, 1, output)
        self.assertIn("no owning PR reference", output)

    def test_completed_unchanged_null_pr_return_retains_existing_historical_exemption(self):
        result, output, _ = self.historical_null_pr_return()
        self.assertEqual(result, 0, output)
        self.assertIn("unchanged pre-rule null-PR return", output)

    def test_completed_null_pr_return_edited_after_rule_requires_owning_pr(self):
        result, output, _ = self.historical_null_pr_return(changed=True)
        self.assertEqual(result, 1, output)
        self.assertIn("no owning PR reference", output)

    def test_completed_null_pr_return_without_rule_history_requires_owning_pr(self):
        result, output, _ = self.historical_null_pr_return(rule=False)
        self.assertEqual(result, 1, output)
        self.assertIn("no owning PR reference", output)

    def test_completed_return_cannot_be_borrowed_from_another_issue(self):
        _, main = self.setup_completed_stack()
        issues = [
            {"number": 1, "disposition": "completed", "pull_requests": [101],
             "returns": [".migration/returns/T2.afs-verifier.yaml"]},
            {"number": 2, "disposition": "completed", "pull_requests": [101, 102],
             "returns": [".migration/returns/T2.afs-verifier.yaml"]},
        ]
        result, output, _ = self.run_reconciliation(issues, {
            101: self.pull(101, head=main, merged=True),
            102: self.pull(102, head=main),
        })
        self.assertEqual(result, 1, output)
        self.assertIn("does not attribute", output)

    def test_completed_return_requires_its_own_landed_pr_not_a_carrier_copy(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "work-pr-101")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        (returns / "T1.afs-verifier.yaml").write_text(self.RETURN, encoding="utf-8")
        (self.root / "work.txt").write_text("work from PR 101\n", encoding="utf-8")
        work_head = self.commit("work and verifier return")
        self.git("checkout", "-qb", "default-branch", base)
        (self.root / "docs.txt").write_text("unrelated docs\n", encoding="utf-8")
        self.git("add", "docs.txt")
        self.git("commit", "-qm", "unrelated PR 201")
        returns.mkdir(parents=True, exist_ok=True)
        (self.root / ".migration/returns/T1.afs-verifier.yaml").write_text(self.RETURN, encoding="utf-8")
        self.git("add", ".migration/returns/T1.afs-verifier.yaml")
        self.git("commit", "-qm", "copy return without PR 101 work")
        carrier = self.git("rev-parse", "HEAD")
        issue = {"number": 1, "disposition": "completed", "pull_requests": [201],
                 "returns": [".migration/returns/T1.afs-verifier.yaml"]}
        result, output, _ = self.run_reconciliation([issue], {
            101: self.pull(101, head=work_head),
            201: self.pull(201, head=carrier, merged=True),
        })
        self.assertEqual(result, 1, output)
        self.assertIn("owning PR #101", output)

    def test_carrier_copy_regression_is_independent_of_initial_branch_setting(self):
        for branch in ("main", "master", "default-branch"):
            with self.subTest(branch=branch), mock.patch.dict(os.environ, {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "init.defaultBranch",
                    "GIT_CONFIG_VALUE_0": branch,
            }):
                result = unittest.TestResult()
                type(self)("test_completed_return_requires_its_own_landed_pr_not_a_carrier_copy").run(result)
                self.assertEqual(result.testsRun, 1)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_bootstrapper_blocked_validation_is_not_completed_evidence(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        blocked = """role: afs-bootstrapper
ticket: B1
issue: o/r#1
setup_pr: o/r#101
characterization_tier: B
tier_evidence: Isolated regression fixture.
capabilities: {met: 0, gap: 1, waived: 0, not_applicable: 0}
gap_tickets: []
validation: "blocked: normal installation was not attempted"
"""
        self.assertIsNotNone(ticket_guard._valid_return(blocked, ".migration/returns/B1.afs-bootstrapper.yaml"))
        (returns / "B1.afs-bootstrapper.yaml").write_text(blocked, encoding="utf-8")
        main = self.commit("blocked bootstrapper return")
        issue = {"number": 1, "disposition": "completed", "pull_requests": [101],
                 "returns": [".migration/returns/B1.afs-bootstrapper.yaml"]}
        result, output, _ = self.run_reconciliation([issue], {
            101: self.pull(101, head=main, merged=True),
        })
        self.assertEqual(result, 1, output)
        self.assertIn("Bootstrapper validation is not an explicit pass", output)

    def test_bootstrapper_pass_with_limitations_remains_a_passing_outcome(self):
        returned = """role: afs-bootstrapper
ticket: B1
issue: o/r#1
setup_pr: o/r#101
characterization_tier: B
tier_evidence: Isolated regression fixture.
capabilities: {met: 1, gap: 0, waived: 0, not_applicable: 0}
gap_tickets: []
validation: "pass with limitations: optional service is unavailable"
"""
        doc = ticket_guard._valid_return(returned, ".migration/returns/B1.afs-bootstrapper.yaml")
        self.assertIsNotNone(doc)
        self.assertIsNone(ticket_guard._role_outcome_problem(doc))

    def test_migrator_outcomes_use_its_gate_results_instead_of_verifier_fields(self):
        gates = {"build": 0, "behavior": 0, "idiom": 0, "crap": 4,
                 "mutation_changed": 0.9, "regression": 0}
        passing = {"role": "afs-migrator", "gates": gates, "handoff": None}
        failing = {"role": "afs-migrator", "gates": {**gates, "behavior": 1}, "handoff": None}
        self.assertIsNone(ticket_guard._role_outcome_problem(passing))
        self.assertIsNone(ticket_guard._role_outcome_problem(failing, failed=True))
        self.assertIn("no passing result", ticket_guard._role_outcome_problem(failing))

    def test_migrator_none_handoff_and_reasoned_na_follow_the_return_contract(self):
        gates = {"build": 0, "behavior": 0, "idiom": 0, "crap": 4,
                 "mutation_changed": "n/a: no mutable code changed", "regression": 0}
        passing = {"role": "afs-specialist-migrator", "gates": gates, "handoff": "none"}
        self.assertIsNone(ticket_guard._role_outcome_problem(passing))
        self.assertIsNotNone(ticket_guard._role_outcome_problem(passing, failed=True))
        returned = """role: afs-migrator
ticket: HR-04A
issue: o/r#1
pr: o/r#101
gates:
  build: 0
  behavior: 0
  idiom: 0
  crap: 4
  mutation_changed: "n/a: no mutable code changed"
  regression: 0
evidence_logs: []
ledger_updated: []
quirk_tickets: []
new_tickets: []
handoff: none
"""
        schema_valid = ticket_guard._valid_return(
            returned, ".migration/returns/HR-04A.afs-migrator.yaml")
        self.assertIsNotNone(schema_valid)
        self.assertIsNone(ticket_guard._role_outcome_problem(schema_valid))
        for invalid in (
                {**gates, "mutation_changed": "n/a: "},
                {**gates, "mutation_changed": None},
                {**gates, "mutation_changed": 1.1},
                {**gates, "mutation_changed": float("nan")},
                {**gates, "crap": -1},
                {**gates, "crap": float("inf")},
                {**gates, "crap": float("nan")},
                {**gates, "regression": None},
                {**gates, "build": 1},
        ):
            with self.subTest(gates=invalid):
                self.assertIsNotNone(ticket_guard._role_outcome_problem(
                    {"role": "afs-migrator", "gates": invalid, "handoff": "none"}))
        for handoff in ("", None, "none", "   "):
            with self.subTest(handoff=handoff):
                self.assertIsNotNone(ticket_guard._role_outcome_problem(
                    {"role": "afs-migrator", "gates": gates, "handoff": handoff}, failed=True))
        blocked = {"role": "afs-migrator", "gates": gates, "handoff": "blocked: external dependency"}
        self.assertIn("outstanding handoff", ticket_guard._role_outcome_problem(blocked))
        self.assertIsNone(ticket_guard._role_outcome_problem(blocked, failed=True))

    def test_completed_parent_ticket_return_is_attributed_to_its_actual_child_pr(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = ".migration/returns/T1.afs-verifier.yaml"
        passed = self.RETURN.replace("verdict: pass", "verdict: pass").replace("pr: o/r#101", "pr: o/r#102")
        (self.root / path).write_text(passed, encoding="utf-8")
        landed = self.commit("child work and parent-owned return")
        issue = {"number": 2, "disposition": "completed", "pull_requests": [102], "returns": [path]}
        child_pull = self.pull(102, head=landed, merged=True, body="Fixes #2")
        child_pull["files"] = [{"filename": path, "status": "modified"}]
        result, output, _ = self.run_reconciliation(
            [issue], {102: child_pull},
            labels=[{"number": 2, "title": "child", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={2: {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}},
        )
        self.assertEqual(result, 0, output)

    def test_parent_ticket_return_cannot_borrow_a_parent_or_unrelated_pr(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = ".migration/returns/T1.afs-verifier.yaml"
        passed = self.RETURN.replace("pr: o/r#101", "pr: o/r#102")
        (self.root / path).write_text(passed, encoding="utf-8")
        landed = self.commit("unrelated carrier return")
        issue = {"number": 2, "disposition": "completed", "pull_requests": [102], "returns": [path]}
        result, output, _ = self.run_reconciliation(
            [issue], {102: self.pull(102, head=landed, merged=True, body="Updates #2")},
            labels=[{"number": 2, "title": "child", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={2: {"number": 2, "parent_issue_url":
                               "https://api.github.com/repos/o/r/issues/1"}},
        )
        self.assertEqual(result, 1, output)
        self.assertIn("child-work PR #102 does not close child issue #2", output)
        result, output, _ = self.run_reconciliation(
            [issue], {102: self.pull(102, head=landed, merged=True, body="Fixes #2")},
            report_exists=False,
            labels=[{"number": 2, "title": "child", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={2: {"number": 2, "parent_issue_url":
                               "https://api.github.com/repos/o/r/issues/3"}},
        )
        self.assertEqual(result, 1, output)
        self.assertIn("not the parent or a sibling of the child", output)

    def test_parent_ticket_returns_accept_separate_changed_child_work_and_current_owner_prs(self):
        cases = (
            (147, 129, 148, 154, "afs-migrator", 129, 0.795, "none", None),
            (149, 130, 150, 163, "afs-specialist-migrator", 130, 0.8, "none", 162),
            (155, 129, 156, 154, "afs-migrator", 129, 0.855, "none", None),
            (168, 131, 169, 177, "afs-verifier", 176, None, None, 176),
        )
        for child, parent, work_pr, owner_pr, role, artifact_issue, mutation, handoff, closes_current in cases:
            with self.subTest(child=child):
                (self.root / "base.txt").write_text(f"base {child}\n", encoding="utf-8")
                returns = self.root / ".migration/returns"
                returns.mkdir(parents=True, exist_ok=True)
                ticket = f"T{child}"
                path = f".migration/returns/{ticket}.{role}.yaml"
                if role.endswith("migrator"):
                    gates = {"build": 0, "behavior": 0, "idiom": 0, "crap": 4,
                             "mutation_changed": mutation, "regression": 0}
                    current_doc = {
                        "role": role, "ticket": ticket, "issue": f"o/r#{artifact_issue}",
                        "pr": f"o/r#{owner_pr}", "gates": gates, "evidence_logs": [],
                        "ledger_updated": [], "quirk_tickets": [], "new_tickets": [],
                        "handoff": handoff,
                    }
                    if role == "afs-specialist-migrator":
                        current_doc.update(specialty="data", specialty_evidence=[])
                    historical_doc = dict(current_doc)
                    if child == 147:
                        historical_doc["gates"] = {**gates, "mutation_changed": 0.795}
                else:
                    current_doc = yaml.safe_load(
                        self.RETURN.replace("ticket: T1", f"ticket: {ticket}")
                        .replace("issue: o/r#1", f"issue: o/r#{artifact_issue}")
                        .replace("pr: o/r#101", f"pr: o/r#{owner_pr}"))
                    historical_doc = dict(current_doc)
                if child == 147:
                    historical_doc["issue"] = f"o/r#{parent}"
                    historical_doc["pr"] = f"o/r#{work_pr}"
                    historical_doc["handoff"] = "blocked: prior mutation gate"
                returns_path = self.root / path
                returns_path.write_text(yaml.safe_dump(historical_doc), encoding="utf-8")
                work_head = self.commit(f"child {child} work return")
                current_text = yaml.safe_dump(current_doc)
                if yaml.safe_dump(historical_doc) == current_text:
                    current_head = work_head
                else:
                    returns_path.write_text(current_text, encoding="utf-8")
                    current_head = self.commit(f"current owner for child {child}")
                pulls = {
                    work_pr: self.pull(work_pr, head=work_head, body=f"Fixes #{child}"),
                    owner_pr: self.pull(
                        owner_pr, head=current_head, merged=True,
                        body=f"Fixes #{closes_current}" if closes_current else "Carries the current return"),
                }
                pulls[work_pr]["files"] = [{"filename": path, "status": "modified"}]
                issue_details = {
                    child: {"number": child,
                            "parent_issue_url": f"https://api.github.com/repos/o/r/issues/{parent}"},
                }
                if artifact_issue not in {child, parent}:
                    issue_details[artifact_issue] = {
                        "number": artifact_issue,
                        "parent_issue_url": f"https://api.github.com/repos/o/r/issues/{parent}",
                    }
                issue = {"number": child, "disposition": "completed",
                         "pull_requests": sorted({work_pr, owner_pr}), "returns": [path]}
                labels = [{"number": child, "title": f"child {child}", "state": "closed",
                           "state_reason": "completed", "labels": []}]
                result, output, _ = self.run_reconciliation(
                    [issue], pulls, labels=labels, issue_details=issue_details)
                self.assertEqual(result, 0, output)
                self.assertIn(f"verified by current PR #{owner_pr} and child PR #{work_pr}", output)

    def test_parent_ticket_child_work_pr_must_change_the_role_return_file(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = ".migration/returns/T1.afs-verifier.yaml"
        current = self.RETURN.replace("issue: o/r#1", "issue: o/r#3").replace(
            "pr: o/r#101", "pr: o/r#103")
        (returns / pathlib.Path(path).name).write_text(current, encoding="utf-8")
        current_head = self.commit("current sibling return")
        child_pr, owner_pr = 102, 103
        issue = {"number": 2, "disposition": "completed", "pull_requests": [child_pr, owner_pr],
                 "returns": [path]}
        result, output, _ = self.run_reconciliation(
            [issue], {
                child_pr: self.pull(child_pr, head=current_head, body="Fixes #2"),
                owner_pr: self.pull(owner_pr, head=current_head, merged=True, body="Fixes #3"),
            },
            labels=[{"number": 2, "title": "child", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={
                2: {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"},
                3: {"number": 3, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"},
            },
        )
        self.assertEqual(result, 1, output)
        self.assertIn("did not change the exact role return file", output)

    def test_parent_ticket_return_accepts_same_path_supersession_with_cited_child_pr(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = ".migration/returns/T1.afs-verifier.yaml"
        failed = self.RETURN.replace("pr: o/r#101", "pr: o/r#102").replace("verdict: pass",
                                                                           "verdict: changes-required")
        (self.root / path).write_text(failed, encoding="utf-8")
        failed_head = self.commit("failed child verifier return")
        passed = self.RETURN.replace("issue: o/r#1", "issue: o/r#3").replace("pr: o/r#101", "pr: o/r#103")
        (self.root / path).write_text(passed, encoding="utf-8")
        current_head = self.commit("current passing parent-owned return")
        issue = {"number": 2, "disposition": "completed", "pull_requests": [102, 103], "returns": [path]}
        child_pull = self.pull(102, head=failed_head, body="Fixes #2")
        child_pull["files"] = [{"filename": path, "status": "modified"}]
        result, output, _ = self.run_reconciliation(
            [issue], {
                102: child_pull,
                103: self.pull(103, head=current_head, merged=True, body="Fixes #3"),
            },
            labels=[{"number": 2, "title": "child", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={
                2: {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"},
                3: {"number": 3, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"},
            },
        )
        self.assertEqual(result, 0, output)

    def test_parent_ticket_history_does_not_replace_an_unlanded_current_owner(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = ".migration/returns/T1.afs-verifier.yaml"
        failed = self.RETURN.replace("pr: o/r#101", "pr: o/r#102")
        (self.root / path).write_text(failed, encoding="utf-8")
        failed_head = self.commit("landed child return")
        passed = self.RETURN.replace("pr: o/r#101", "pr: o/r#103")
        (self.root / path).write_text(passed, encoding="utf-8")
        self.commit("current pass from open owner")
        issue = {"number": 2, "disposition": "completed", "pull_requests": [102, 103], "returns": [path]}
        result, output, _ = self.run_reconciliation(
            [issue], {
                102: self.pull(102, head=failed_head, body="Fixes #2"),
                103: {"number": 103, "state": "open", "merged_at": None, "head": {"sha": "f" * 40},
                      "body": "Fixes #1"},
            },
            labels=[{"number": 2, "title": "child", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={2: {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}},
        )
        self.assertEqual(result, 1, output)
        self.assertIn("PR #103 is still open", output)

    def test_ordinary_history_accepts_canonical_ticket_with_real_epic_parent(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = ".migration/returns/T1.afs-verifier.yaml"
        canonical = self.RETURN.replace("pr: o/r#101", "pr: o/r#102")
        (self.root / path).write_text(canonical, encoding="utf-8")
        canonical_head = self.commit("canonical ticket return")
        current_child = self.RETURN.replace("issue: o/r#1", "issue: o/r#3").replace(
            "pr: o/r#101", "pr: o/r#103")
        (self.root / path).write_text(current_child, encoding="utf-8")
        current_head = self.commit("sub-issue re-verification")
        issue = {"number": 1, "disposition": "completed", "pull_requests": [103], "returns": [path]}
        result, output, _ = self.run_reconciliation(
            [issue], {103: self.pull(103, head=current_head, merged=True, body="Fixes #3")},
            labels=[{"number": 1, "title": "canonical", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={
                1: {"number": 1, "parent_issue_url": "https://api.github.com/repos/o/r/issues/99"},
                3: {"number": 3, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"},
            },
        )
        self.assertEqual(result, 0, output)
        self.assertIn("Historical attribution is not a passing verdict", output)
        self.assertTrue(canonical_head)

    def test_generic_history_cannot_bypass_parent_child_pr_proof(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = ".migration/returns/T1.afs-verifier.yaml"
        child_return = self.RETURN.replace("issue: o/r#1", "issue: o/r#2").replace(
            "pr: o/r#101", "pr: o/r#102")
        (self.root / path).write_text(child_return, encoding="utf-8")
        self.commit("historical child return")
        passed = self.RETURN.replace("pr: o/r#101", "pr: o/r#103")
        (self.root / path).write_text(passed, encoding="utf-8")
        current_head = self.commit("parent return without child proof")
        issue = {"number": 2, "disposition": "completed", "pull_requests": [103], "returns": [path]}
        result, output, _ = self.run_reconciliation(
            [issue], {103: self.pull(103, head=current_head, merged=True, body="Fixes #1")},
            labels=[{"number": 2, "title": "child", "state": "closed", "state_reason": "completed",
                     "labels": []}],
            issue_details={2: {"number": 2, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}},
        )
        self.assertEqual(result, 1, output)
        self.assertIn("parent-ticket continuation for issue #2 is not verified", output)

    def test_superseded_parent_owned_verifier_failure_and_completed_replacement(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "failed-child-verifier")
        failed_path = ".migration/returns/T1.afs-verifier.yaml"
        (self.root / failed_path).parent.mkdir(parents=True)
        failed = self.RETURN.replace("pr: o/r#101", "pr: o/r#103").replace("verdict: pass",
                                                                           "verdict: changes-required")
        (self.root / failed_path).write_text(failed, encoding="utf-8")
        failed_head = self.commit("failed child verifier")
        self.git("checkout", "-q", "--detach", base)
        replacement_path = ".migration/returns/T4.afs-verifier.yaml"
        (self.root / replacement_path).parent.mkdir(parents=True)
        passing = self.RETURN.replace("ticket: T1", "ticket: T4").replace("issue: o/r#1", "issue: o/r#4") \
            .replace("pr: o/r#101", "pr: o/r#104")
        (self.root / replacement_path).write_text(passing, encoding="utf-8")
        replacement_head = self.commit("replacement verifier passes")
        report = [
            {"number": 3, "disposition": "superseded", "replacement": 4,
             "failure": {"pull_request": 103, "return": failed_path}},
            {"number": 4, "disposition": "completed", "pull_requests": [104], "returns": [replacement_path]},
        ]
        result, output, _ = self.run_reconciliation(
            [{"number": 3, "disposition": "superseded"}, {"number": 4, "disposition": "completed"}], {
                103: self.pull(103, head=failed_head, body="Fixes #3"),
                104: self.pull(104, head=replacement_head, merged=True),
            }, contents={
                f"repos/o/r/contents/{failed_path}?ref={failed_head}": {
                    "encoding": "base64", "content": base64.b64encode(failed.encode()).decode()},
            },
            report_issues=report,
            labels=[
                {"number": 3, "title": "failed child", "state": "closed", "state_reason": "not_planned",
                 "labels": []},
                {"number": 4, "title": "replacement", "state": "closed", "state_reason": "completed",
                 "labels": []},
            ],
            issue_details={3: {"number": 3, "parent_issue_url": "https://api.github.com/repos/o/r/issues/1"}},
        )
        self.assertEqual(result, 0, output)

    def test_failed_parent_owned_return_requires_the_actual_child_and_closing_pr(self):
        path = ".migration/returns/T3.afs-verifier.yaml"
        failed = self.FAILED_RETURN.replace("issue: o/r#3", "issue: o/r#1")
        encoded = {"encoding": "base64", "content": base64.b64encode(failed.encode()).decode()}
        pull = {"number": 103, "state": "closed", "merged_at": None, "head": {"sha": "a" * 40},
                "body": "Fixes #3"}
        cases = (
            ("https://api.github.com/repos/o/r/issues/4", "Fixes #3", "not a child"),
            ("https://api.github.com/repos/o/r/issues/1", "Updates #3", "does not close child"),
        )
        for parent_url, body, problem in cases:
            with self.subTest(parent=parent_url, body=body):
                def gh(endpoint, *args, **kwargs):
                    if endpoint == f"repos/o/r/contents/{path}?ref={'a' * 40}":
                        return encoded
                    if endpoint == "repos/o/r/issues/3":
                        return {"number": 3, "parent_issue_url": parent_url}
                    return {}

                with mock.patch.object(ticket_guard, "gh", side_effect=gh):
                    with self.assertRaisesRegex(ValueError, problem):
                        ticket_guard._failed_role_return(
                            "o/r", 3, 103, path, {**pull, "body": body})

    def test_superseded_bootstrapper_failure_can_preserve_its_own_blocked_return(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "bootstrap-attempt")
        failed_path = ".migration/returns/B3.afs-bootstrapper.yaml"
        (self.root / failed_path).parent.mkdir(parents=True)
        failed = """role: afs-bootstrapper
ticket: B3
issue: o/r#3
setup_pr: o/r#103
characterization_tier: B
tier_evidence: Isolated regression fixture.
capabilities: {met: 0, gap: 1, waived: 0, not_applicable: 0}
gap_tickets: []
validation: "blocked: worker transport could not install dependencies"
"""
        self.assertIsNotNone(ticket_guard._valid_return(failed, failed_path))
        (self.root / failed_path).write_text(failed, encoding="utf-8")
        failed_head = self.commit("blocked bootstrapper attempt")
        self.git("checkout", "-q", "--detach", base)
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True, exist_ok=True)
        passing = """role: afs-verifier
ticket: T4
issue: o/r#4
pr: o/r#104
verdict: pass
gates: null
evidence_logs: []
findings: []
tests_added: []
ledger_issues: []
quirk_tickets: []
"""
        (returns / "T4.afs-verifier.yaml").write_text(passing, encoding="utf-8")
        replacement_head = self.commit("replacement passes")
        report = [
            {"number": 3, "disposition": "superseded", "replacement": 4,
             "failure": {"pull_request": 103, "return": failed_path}},
            {"number": 4, "disposition": "completed", "pull_requests": [104],
             "returns": [".migration/returns/T4.afs-verifier.yaml"]},
        ]
        issues = [{"number": 3, "disposition": "superseded"}, {"number": 4, "disposition": "completed"}]
        content_path = f"repos/o/r/contents/{failed_path}?ref={failed_head}"
        result, output, _ = self.run_reconciliation(issues, {
            103: self.pull(103, head=failed_head),
            104: self.pull(104, head=replacement_head, merged=True),
        }, contents={content_path: {"encoding": "base64",
                                    "content": base64.b64encode(failed.encode()).decode()}},
           report_issues=report, labels=[
               {"number": 3, "title": "failed bootstrap", "state": "closed", "state_reason": "not_planned",
                "labels": []},
               {"number": 4, "title": "replacement", "state": "closed", "state_reason": "completed",
                "labels": []},
           ])
        self.assertEqual(result, 0, output)

    def test_superseded_failure_return_cannot_be_borrowed_from_replacement_issue(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "failed-verification")
        borrowed_path = ".migration/returns/T4.afs-verifier.yaml"
        (self.root / borrowed_path).parent.mkdir(parents=True)
        borrowed = self.FAILED_RETURN.replace("ticket: T3", "ticket: T4").replace("issue: o/r#3", "issue: o/r#4")
        (self.root / borrowed_path).write_text(borrowed, encoding="utf-8")
        failed_head = self.commit("failed attempt with replacement return")
        self.git("checkout", "-q", "--detach", base)
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True, exist_ok=True)
        (returns / "T4.afs-verifier.yaml").write_text(
            self.RETURN.replace("ticket: T1", "ticket: T4").replace("issue: o/r#1", "issue: o/r#4")
            .replace("pr: o/r#101", "pr: o/r#104"), encoding="utf-8")
        replacement_head = self.commit("replacement passes")
        report = [
            {"number": 3, "disposition": "superseded", "replacement": 4,
             "failure": {"pull_request": 103, "return": borrowed_path}},
            {"number": 4, "disposition": "completed", "pull_requests": [104],
             "returns": [".migration/returns/T4.afs-verifier.yaml"]},
        ]
        content_path = f"repos/o/r/contents/{borrowed_path}?ref={failed_head}"
        result, output, _ = self.run_reconciliation(
            [{"number": 3, "disposition": "superseded"}, {"number": 4, "disposition": "completed"}], {
                103: self.pull(103, head=failed_head),
                104: self.pull(104, head=replacement_head, merged=True),
            }, contents={content_path: {"encoding": "base64",
                                        "content": base64.b64encode(borrowed.encode()).decode()}},
            report_issues=report,
            labels=[
                {"number": 3, "title": "failed verification", "state": "closed", "state_reason": "not_planned",
                 "labels": []},
                {"number": 4, "title": "replacement", "state": "closed", "state_reason": "completed",
                 "labels": []},
            ])
        self.assertEqual(result, 1, output)
        self.assertIn("does not belong to issue #3", output)

    def test_superseded_characterizer_failure_uses_exact_pr_head_without_pr_field(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "failed-characterization")
        failed_path = ".migration/returns/C3.afs-characterizer.yaml"
        (self.root / failed_path).parent.mkdir(parents=True)
        failed = """role: afs-characterizer
ticket: C3
issue: o/r#3
tier_used: {A: 0, B: 1, C: 0}
suite: {path: tests/fixture, cases: 2, passing: 1, run_log: .migration/evidence/runs/C3.md}
predicted_vs_observed: {match: 1, differs: 1}
ledger_updated: []
quirk_tickets: []
review_only_requests: []
"""
        self.assertIsNotNone(ticket_guard._valid_return(failed, failed_path))
        (self.root / failed_path).write_text(failed, encoding="utf-8")
        failed_head = self.commit("failed characterization")
        self.git("checkout", "-q", "--detach", base)
        replacement_path = ".migration/returns/T4.afs-verifier.yaml"
        (self.root / replacement_path).parent.mkdir(parents=True, exist_ok=True)
        passing = self.RETURN.replace("ticket: T1", "ticket: T4").replace("issue: o/r#1", "issue: o/r#4") \
            .replace("pr: o/r#101", "pr: o/r#104")
        (self.root / replacement_path).write_text(passing, encoding="utf-8")
        replacement_head = self.commit("replacement accepted")
        report = [
            {"number": 3, "disposition": "superseded", "replacement": 4,
             "failure": {"pull_request": 103, "return": failed_path}},
            {"number": 4, "disposition": "completed", "pull_requests": [104], "returns": [replacement_path]},
        ]
        content_path = f"repos/o/r/contents/{failed_path}?ref={failed_head}"
        result, output, _ = self.run_reconciliation(
            [{"number": 3, "disposition": "superseded"}, {"number": 4, "disposition": "completed"}], {
                103: self.pull(103, head=failed_head),
                104: self.pull(104, head=replacement_head, merged=True),
            }, contents={content_path: {"encoding": "base64",
                                        "content": base64.b64encode(failed.encode()).decode()}},
            report_issues=report,
            labels=[
                {"number": 3, "title": "failed characterization", "state": "closed",
                 "state_reason": "not_planned", "labels": []},
                {"number": 4, "title": "replacement", "state": "closed", "state_reason": "completed",
                 "labels": []},
            ])
        self.assertEqual(result, 0, output)

    def test_superseded_characterizer_return_from_another_issue_is_rejected(self):
        char_return = """role: afs-characterizer
ticket: C4
issue: o/r#4
tier_used: {A: 0, B: 1, C: 0}
suite: {path: tests/fixture, cases: 2, passing: 1, run_log: .migration/evidence/runs/C4.md}
predicted_vs_observed: {match: 1, differs: 1}
ledger_updated: []
quirk_tickets: []
review_only_requests: []
"""
        self.assertIsNotNone(ticket_guard._valid_return(char_return, ".migration/returns/C4.afs-characterizer.yaml"))
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / ".migration/returns/C4.afs-characterizer.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(char_return)
            with mock.patch.object(ticket_guard, "gh", return_value={
                    "encoding": "base64", "content": base64.b64encode(char_return.encode()).decode()}):
                with self.assertRaisesRegex(ValueError, "does not belong to issue #3"):
                    ticket_guard._failed_role_return("o/r", 3, 103, path.relative_to(d).as_posix(),
                                                     {"head": {"sha": "a" * 40}})

    def test_real_gate_sequence_blocks_fog_for_open_nested_descendant(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        (returns / "T1.afs-verifier.yaml").write_text(self.RETURN, encoding="utf-8")
        main = self.commit("completed work and return")
        report = [
            {"number": 1, "disposition": "completed", "pull_requests": [101],
             "returns": [".migration/returns/T1.afs-verifier.yaml"]},
            {"number": 5, "disposition": "retained-open", "outstanding": "Finish the wrapper task.",
             "blocker": "Waiting on its owner."},
        ]
        self.write_report(report)
        self.commit("ticket dispositions")
        issues = {
            99: {"number": 99, "title": "slice", "html_url": "https://example.invalid/issues/99",
                "state": "closed", "labels": [{"name": "afs:slice"}]},
            1: {"number": 1, "title": "work", "state": "closed", "state_reason": "completed",
                "closed_at": "2026-11-05T12:00:00Z", "labels": []},
            5: {"number": 5, "title": "wrapper", "state": "open", "state_reason": None, "labels": []},
        }
        responses = {
            "repos/o/r/issues/99/sub_issues?per_page=100&page=1": [issues[1]],
            "repos/o/r/issues/1/sub_issues?per_page=100&page=1": [issues[5]],
            "repos/o/r/issues/5/sub_issues?per_page=100&page=1": [],
        }
        calls = []

        def gh(endpoint, *args, data=None):
            calls.append((endpoint, args, data))
            if endpoint == "repos/o/r/issues/99":
                return issues[99]
            if endpoint == "repos/o/r/issues/1":
                return issues[1]
            if endpoint == "repos/o/r/issues/5":
                return issues[5]
            if endpoint.startswith("repos/o/r/pulls/"):
                return self.pull(101, head=main, merged=True)
            if endpoint in responses:
                return responses[endpoint]
            if endpoint == "repos/o/r/issues?labels=wayfinder:map&state=open&per_page=10":
                return [{"number": 3, "title": "map", "body": "## Not yet specified\n- future question",
                         "html_url": "https://example.invalid/map"}]
            if endpoint == "repos/o/r/issues/3/sub_issues?per_page=100":
                return []
            if endpoint == "repos/o/r/issues":
                return {"id": 505, "html_url": "fixture-only-created"}
            return {}

        outputs = []
        output = io.StringIO()
        with mock.patch.object(ticket_guard, "gh", side_effect=gh), \
                mock.patch.object(check_slice_returns.fog_rewalk, "gh", side_effect=gh), \
                mock.patch.object(fog_rewalk, "gh", side_effect=gh), \
                mock.patch.object(check_slice_returns, "rule_since", return_value="2026-11-03T00:00:00Z"), \
                contextlib.redirect_stdout(output):
            reconciliation = ticket_guard.main(["--repo", "o/r", "--reconcile-epic", "99", "--reopen"])
            outputs.append(reconciliation)
            if reconciliation == 0:
                returns_result = check_slice_returns.main(["--repo", "o/r", "--epic", "99", "--reopen"])
                outputs.append(returns_result)
                if returns_result == 0:
                    outputs.append(fog_rewalk.main(["--repo", "o/r", "--epic", "99", "--closed-by", "alice"]))
        self.assertEqual(outputs, [0, 1])
        self.assertIn("#5 disposition=retained-open", output.getvalue())
        self.assertIn("#5 wrapper: still open", output.getvalue())
        self.assertFalse(any(c[0] == "repos/o/r/issues" for c in calls),
                         "the actual fog workflow function must not run after either failed gate")
        self.assertTrue(any(c[0] == "repos/o/r/issues/99" and c[1] == ("-X", "PATCH")
                            and c[2] == {"state": "open"} for c in calls),
                        "the existing return gate must reopen the epic")

    def test_same_path_historical_return_attributes_superseded_issue_but_current_pass_is_required(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = returns / "T1.afs-verifier.yaml"
        path.write_text(self.FAILED_RETURN.replace("ticket: T3", "ticket: T1")
                        .replace("issue: o/r#3", "issue: o/r#1")
                        .replace("pr: o/r#103", "pr: o/r#101"), encoding="utf-8")
        original_head = self.commit("original failed return")
        path.write_text(self.RETURN.replace("issue: o/r#1", "issue: o/r#2")
                        .replace("pr: o/r#101", "pr: o/r#102"), encoding="utf-8")
        current_head = self.commit("later passing re-verification return")
        report = [
            {"number": 1, "disposition": "completed", "pull_requests": [101, 102],
             "returns": [".migration/returns/T1.afs-verifier.yaml"]},
            {"number": 2, "disposition": "completed", "pull_requests": [102],
             "returns": [".migration/returns/T1.afs-verifier.yaml"]},
        ]
        result, output, _ = self.run_reconciliation(
            [{"number": 1, "disposition": "completed"}, {"number": 2, "disposition": "completed"}], {
                101: self.pull(101, head=original_head),
                102: self.pull(102, head=current_head, merged=True),
            }, report_issues=report,
            labels=[
                {"number": 1, "title": "original", "state": "closed", "state_reason": "completed", "labels": []},
                {"number": 2, "title": "re-verification", "state": "closed", "state_reason": "completed",
                 "labels": []},
            ])
        self.assertEqual(result, 0, output)
        self.assertIn("Historical attribution is not a passing verdict", output)

    def test_historical_failure_return_does_not_satisfy_completed_pass_evidence(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        path = returns / "T1.afs-verifier.yaml"
        failed = self.FAILED_RETURN.replace("ticket: T3", "ticket: T1").replace("issue: o/r#3", "issue: o/r#1") \
            .replace("pr: o/r#103", "pr: o/r#101")
        path.write_text(failed, encoding="utf-8")
        head = self.commit("failed verifier return")
        issue = {"number": 1, "disposition": "completed", "pull_requests": [101],
                 "returns": [".migration/returns/T1.afs-verifier.yaml"]}
        result, output, _ = self.run_reconciliation([issue], {
            101: self.pull(101, head=head, merged=True),
        })
        self.assertEqual(result, 1, output)
        self.assertIn("Verifier verdict is not pass", output)

    def test_completed_stacked_wrappers_accept_merged_and_exact_unmerged_integrated_heads(self):
        head, main = self.setup_completed_stack()
        issues = [
            {"number": 1, "disposition": "completed", "pull_requests": [101],
             "returns": [".migration/returns/T1.afs-verifier.yaml"]},
            {"number": 2, "disposition": "completed", "pull_requests": [101, 102],
             "returns": [".migration/returns/T2.afs-verifier.yaml"]},
        ]
        result, output, calls = self.run_reconciliation(issues, {
            101: self.pull(101, head=main, merged=True),
            102: self.pull(102, head=head),
        }, report_exists=False)
        self.assertEqual(result, 0, output)
        self.assertIn("gate=ticket-reconciliation epic=99 verdict=pass", output)
        self.assertFalse(any(c[1][:2] == ("-X", "PATCH") for c in calls), "check does not close work issues")

    def test_closed_unmerged_pr_without_its_exact_head_in_main_is_not_landing_evidence(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "unmerged-work")
        (self.root / "unmerged.txt").write_text("not on main\n", encoding="utf-8")
        unmerged_head = self.commit("unmerged work")
        self.git("checkout", "-q", "--detach", base)
        returns = self.root / ".migration/returns"
        returns.mkdir(parents=True)
        (returns / "T1.afs-verifier.yaml").write_text(self.RETURN, encoding="utf-8")
        (self.root / "main.txt").write_text("default branch\n", encoding="utf-8")
        self.commit("default branch")
        issue = {"number": 1, "disposition": "completed", "pull_requests": [101],
                 "returns": [".migration/returns/T1.afs-verifier.yaml"]}
        result, output, _ = self.run_reconciliation([issue], {101: self.pull(101, head=unmerged_head)})
        self.assertEqual(result, 1, output)
        self.assertIn("no verified landing", output)

    def test_skipped_reconciliation_reopens_epic_and_fails(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        result, output, calls = self.run_reconciliation([], {}, report_exists=False)
        self.assertEqual(result, 1, output)
        self.assertIn("missing", output)
        self.assertTrue(any(c[2] == {"state": "open"} for c in calls))
        self.assertTrue(any(c[0] == "repos/o/r/issues/99/comments" for c in calls))

    def test_superseded_failure_requires_replacement_and_preserved_failed_verifier_return(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        base = self.commit("base")
        self.git("checkout", "-qb", "failed-verification")
        failed_path = self.root / ".migration/returns/T3.afs-verifier.yaml"
        failed_path.parent.mkdir(parents=True)
        failed_path.write_text(self.FAILED_RETURN, encoding="utf-8")
        failed_head = self.commit("failed verifier return")
        self.git("checkout", "-q", "--detach", base)
        replacement_path = self.root / ".migration/returns/T4.afs-verifier.yaml"
        replacement_path.parent.mkdir(parents=True, exist_ok=True)
        replacement_path.write_text(
            self.RETURN.replace("ticket: T1", "ticket: T4").replace("issue: o/r#1", "issue: o/r#4")
            .replace("pr: o/r#101", "pr: o/r#104"), encoding="utf-8")
        (self.root / "main.txt").write_text("replacement landed\n", encoding="utf-8")
        main = self.commit("replacement accepted")
        report = [
            {"number": 3, "disposition": "superseded", "replacement": 4,
             "failure": {"pull_request": 103, "return": ".migration/returns/T3.afs-verifier.yaml"}},
            {"number": 4, "disposition": "completed", "pull_requests": [104],
             "returns": [".migration/returns/T4.afs-verifier.yaml"]},
        ]
        issues = [{"number": 3, "disposition": "superseded"}, {"number": 4, "disposition": "completed"}]
        content_path = ("repos/o/r/contents/.migration/returns/T3.afs-verifier.yaml"
                        f"?ref={failed_head}")
        encoded = base64.b64encode(self.FAILED_RETURN.encode()).decode()
        result, output, _ = self.run_reconciliation(issues, {
            103: self.pull(103, head=failed_head),
            104: self.pull(104, head=main, merged=True),
        }, contents={content_path: {"encoding": "base64", "content": encoded}}, report_issues=report,
           labels=[
               {"number": 3, "title": "failed verification", "state": "closed", "state_reason": "not_planned",
                "labels": []},
               {"number": 4, "title": "replacement verification", "state": "closed",
                "state_reason": "completed", "labels": []},
           ])
        self.assertEqual(result, 0, output)
        self.assertIn("superseded", output)
        self.assertNotEqual(failed_head, main)

    def test_explicit_retained_open_work_is_not_reported_as_stale(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        issue = {"number": 5, "disposition": "retained-open", "outstanding": "Finish the data import.",
                 "blocker": "Waiting for the operator-owned production snapshot."}
        result, output, _ = self.run_reconciliation([issue], {}, labels=[
            {"number": 5, "title": "data import", "state": "open", "state_reason": None, "labels": []}
        ])
        self.assertEqual(result, 0, output)
        self.assertIn("retained-open", output)

    def test_decision_map_research_and_issues_outside_the_epic_are_excluded(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        issue = {"number": 1, "disposition": "retained-open", "outstanding": "Work remains.",
                 "blocker": "Blocked by a concrete external dependency."}
        result, output, _ = self.run_reconciliation([issue], {}, labels=[
            {"number": 1, "title": "unfinished slice task", "state": "open", "labels": []},
            {"number": 2, "title": "decision research", "state": "open",
             "labels": [{"name": "wayfinder:research"}]},
        ])
        self.assertEqual(result, 0, output)
        self.assertIn("tickets=1", output)

    def test_unavailable_api_fails_explicitly(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        self.commit("base")
        with mock.patch.object(ticket_guard, "gh", side_effect=SystemExit("gh api unavailable")):
            with self.assertRaisesRegex(SystemExit, "unavailable"):
                ticket_guard.main(["--repo", "o/r", "--reconcile-epic", "99"])

    def test_shallow_history_fails_closed(self):
        (self.root / "base.txt").write_text("base\n", encoding="utf-8")
        head = self.commit("base")
        (self.root / ".git/shallow").write_text(head + "\n", encoding="utf-8")
        issue = {"number": 1, "disposition": "retained-open", "outstanding": "Work remains.",
                 "blocker": "Blocked by a concrete external dependency."}
        result, output, _ = self.run_reconciliation([issue], {}, labels=[
            {"number": 1, "title": "unfinished slice task", "state": "open", "labels": []}
        ])
        self.assertEqual(result, 1, output)
        self.assertIn("history unavailable", output)


if __name__ == "__main__":
    unittest.main()
