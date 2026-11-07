"""Return files: the generated schema, validate.py, and the CI check."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_return_contract as crc  # noqa: E402

RETURN = """role: afs-migrator
ticket: TC-02
issue: martins-vds/ai-factory-pilot-target#22
pr: martins-vds/ai-factory-pilot-target#38
gates: {build: 0, behavior: 0, idiom: 0, crap: 0, mutation_changed: 1.0, regression: 0}
evidence_logs: [.migration/evidence/runs/TC-02.md]
ledger_updated: [track-cargo.data-location]
quirk_tickets: []
new_tickets: []
handoff: null
"""


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class ReturnFileTest(unittest.TestCase):
    def test_schema_is_generated_from_the_agents(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools/gen_return_schema.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def validate(self, files, journals=None, gates=None, legacy=None):
        """files: returns/<name> → text; journals: ticket → rows (gate, command, result); gates: profile gates."""
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            (root / "returns").mkdir()
            for name, text in files.items():
                (root / "returns" / name).write_text(text)
            for ticket, rows in (journals or {}).items():
                (root / "evidence/runs").mkdir(parents=True, exist_ok=True)
                body = "".join(f"| 2026-11-02T00:00:0{i}+00:00 | {g} | 0 | 1.0 | `{c}` | `abc` |  | {r} |\n"
                               for i, (g, c, r) in enumerate(rows))
                (root / "evidence/runs" / f"{ticket}.md").write_text(
                    "# Run journal\n\n| UTC | Gate | Exit | Seconds | Command | Log SHA-256 | First highlight | Result |\n"
                    "|---|---|---|---|---|---|---|---|\n" + body)
            if gates is not None:
                # Only the gates matter here; validate.py checks the profile against its schema too, so skip it.
                (root / "harness").mkdir(exist_ok=True)
                (root / "profile.yaml").write_text(json.dumps({"gates": gates}))
            if legacy is not None:
                (root / "harness").mkdir(exist_ok=True)
                (root / "harness/legacy-returns.json").write_text(json.dumps({"rule": "ADR-0017", "returns": legacy}))
            return subprocess.run([sys.executable, str(ROOT / "tools/validate.py"), t], capture_output=True, text=True)

    MUT = "python .migration/harness/tools/afs-mutation --changed-since origin/main"
    GATES = {"mutation_changed": [MUT]}

    def mutation_run(self, score="1.000", command=None):
        return {"TC-02": [("mutation", command or self.MUT, f"gate=mutation score={score} threshold=0.8")]}

    def errors(self, r):
        """validate.py's errors, ignoring the minimal test profile's own schema errors."""
        return [l for l in r.stderr.splitlines() if "profile.yaml" not in l and not l.startswith("AFS-TOOL ")]

    def test_validate_accepts_a_complete_return_file(self):
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN}, self.mutation_run(), self.GATES)
        self.assertEqual(self.errors(r), [])

    def test_finished_return_requires_a_meaningful_pr_reference(self):
        for text in (RETURN.replace("martins-vds/ai-factory-pilot-target#38", "null"),
                     RETURN.replace("pr: martins-vds/ai-factory-pilot-target#38\n", ""),
                     RETURN.replace("martins-vds/ai-factory-pilot-target#38", "work in progress")):
            with self.subTest(pr=text.split("pr:", 1)[1].splitlines()[0] if "pr:" in text else "missing"):
                r = self.validate({"TC-02.afs-migrator.yaml": text}, self.mutation_run(), self.GATES)
                self.assertIn("finished return requires a meaningful PR reference", r.stderr)
                self.assertIn("fill `pr:` before finishing", r.stderr)

    def test_roles_without_a_pr_contract_do_not_need_pr_attribution(self):
        orchestrator = (
            "role: afs-program-orchestrator\nticket: TC-02\nissue: martins-vds/ai-factory-pilot-target#22\n"
            "phase: 5\ndecisions: []\ndispatched: []\nawaiting_human: []\nnext_step: continue\n"
        )
        r = self.validate({"TC-02.afs-program-orchestrator.yaml": orchestrator})
        self.assertEqual(self.errors(r), [])

    def test_a_later_role_cannot_invalidate_a_committed_return(self):
        """Pilot HR-04C: the Verifier's failing runs appended to the shared journal must not break the
        Migrator's committed return; a return's score is checked as of its own last commit."""
        import tempfile as tf
        with tf.TemporaryDirectory() as d:
            root = pathlib.Path(d) / ".migration"
            (root / "returns").mkdir(parents=True)
            (root / "evidence/runs").mkdir(parents=True)
            (root / "profile.yaml").write_text(json.dumps({"gates": self.GATES}))
            head = ("# Run journal\n\n| UTC | Gate | Exit | Seconds | Command | Log SHA-256 | First highlight | Result |\n"
                    "|---|---|---|---|---|---|---|---|\n")
            row = lambda i, code, res: f"| 2026-11-02T00:00:0{i}+00:00 | mutation | {code} | 1.0 | `{self.MUT}` | `x` |  | {res} |\n"
            journal = root / "evidence/runs/TC-02.md"
            journal.write_text(head + row(1, 0, "gate=mutation score=1.000 threshold=0.8"))
            ret = root / "returns/TC-02.afs-migrator.yaml"
            ret.write_text(RETURN)
            git = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
            git("init", "-q")
            git("add", "-A")
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "migrator")
            journal.write_text(journal.read_text() + row(2, 2, "gate=mutation score=n/a error=mutmut-failed"))
            git("add", "-A")
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "verifier runs")
            run = lambda: subprocess.run([sys.executable, str(ROOT / "tools/validate.py"), str(root)],
                                         capture_output=True, text=True)
            self.assertEqual(self.errors(run()), [], "checked against the journal as of the return's commit")
            ret.write_text(RETURN + "\n")                    # edited now: checked against the journal now
            self.assertIn("does not match the last mutation gate run", run().stderr)

    def test_scores_must_match_the_last_trusted_mutation_run(self):
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN}, self.mutation_run("0.912"), self.GATES)
        self.assertIn("does not match the last mutation gate run", r.stderr)
        self.assertIn("score=0.912", r.stderr)

    def test_result_lines_from_other_commands_are_ignored(self):
        fake = "echo AFS-RESULT gate=mutation score=1.000"
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN}, self.mutation_run(command=fake), self.GATES)
        self.assertIn("has no mutation gate run with a result", r.stderr)

    def test_gate_run_through_bash_c_counts(self):
        cmd = "bash -c '" + self.MUT + "'"
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN}, self.mutation_run(command=cmd), self.GATES)
        self.assertEqual(self.errors(r), [])

    def test_score_without_a_journal_fails(self):
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN}, gates=self.GATES)
        self.assertIn("has no mutation gate run with a result", r.stderr)

    def test_finished_return_needs_every_gate_or_a_reason(self):
        text = RETURN.replace("crap: 0", "crap: null")
        r = self.validate({"TC-02.afs-migrator.yaml": text}, self.mutation_run(), self.GATES)
        self.assertIn("gates.crap is null in a finished return", r.stderr)
        text = RETURN.replace("crap: 0", "'crap': 'n/a: no production code changed'")
        r = self.validate({"TC-02.afs-migrator.yaml": text}, self.mutation_run(), self.GATES)
        self.assertEqual(self.errors(r), [])
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN.replace("crap: 0", "crap: 'n/a'")},
                          self.mutation_run(), self.GATES)
        self.assertIn("gates/crap", r.stderr)

    def test_null_gates_are_fine_with_a_handoff(self):
        text = (RETURN.replace("mutation_changed: 1.0", "mutation_changed: null")
                .replace("pr: martins-vds/ai-factory-pilot-target#38", "pr: null")
                .replace("handoff: null", "handoff: .migration/handoffs/TC-02.md"))
        r = self.validate({"TC-02.afs-migrator.yaml": text})
        self.assertNotIn("in a finished return", r.stderr)
        self.assertNotIn("finished return requires a meaningful PR reference", r.stderr)

    def test_legacy_returns_are_exempt(self):
        historical = RETURN.replace("pr: martins-vds/ai-factory-pilot-target#38", "pr: null")
        r = self.validate({"TC-02.afs-migrator.yaml": historical}, legacy=["TC-02.afs-migrator.yaml"])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_committed_null_pr_history_is_grandfathered_until_the_return_changes(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            migration = root / ".migration"
            ret = migration / "returns/TC-02.afs-migrator.yaml"
            ret.parent.mkdir(parents=True)
            ret.write_text(RETURN.replace("pr: martins-vds/ai-factory-pilot-target#38", "pr: null"))
            shutil.copy(ROOT / "templates/migration/profile.yaml", migration / "profile.yaml")
            (migration / "evidence/runs").mkdir(parents=True)
            (migration / "evidence/runs/TC-02.md").write_text(
                "# Run journal\n\n| UTC | Gate | Exit | Seconds | Command | Log SHA-256 | First highlight | Result |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2026-11-02T00:00:00+00:00 | mutation | 0 | 1.0 | `" + self.MUT +
                "` | `abc` |  | gate=mutation score=1.000 threshold=0.8 |\n"
            )
            (migration / "harness").mkdir()
            (migration / "harness/legacy-returns.json").write_text(
                '{"rule":"ADR-0017","returns":[]}', encoding="utf-8")
            git(root, "init", "-q", "-b", "main")
            git(root, "add", "-A")
            git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "historical return")

            harness = migration / "harness"
            (harness / "tools").mkdir()
            shutil.copytree(ROOT / "schemas", harness / "schemas")
            for name in ("validate.py", "afs_trace.py"):
                shutil.copy(ROOT / "tools" / name, harness / "tools" / name)
            git(root, "add", "-A")
            git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "install PR rule")
            validate = lambda: subprocess.run(
                [sys.executable, str(harness / "tools/validate.py"), str(migration)],
                capture_output=True, text=True,
            )
            self.assertNotIn("finished return requires a meaningful PR reference", validate().stderr)

            ret.write_text(ret.read_text().replace("new_tickets: []", "new_tickets: [o/r#23]"))
            git(root, "add", "-A")
            git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "update return")
            self.assertIn("finished return requires a meaningful PR reference", validate().stderr)

    def test_validate_rejects_missing_keys_bad_gates_and_wrong_names(self):
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN.replace("handoff: null\n", "")})
        self.assertIn("'handoff' is a required property", r.stderr)
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN.replace("build: 0", "build: [0]")})
        self.assertIn("gates/build", r.stderr)
        r = self.validate({"tc2.yaml": RETURN})
        self.assertIn("file name must be 'TC-02.afs-migrator.yaml'", r.stderr)

    def test_validate_enforces_contract_values(self):
        verifier = ("role: afs-verifier\nticket: TC-14\nissue: o/r#34\npr: o/r#61\nverdict: passed\n"
                    "gates: {build: 0, behavior: 0, idiom: 0, crap: 14, mutation_changed: n/a, regression: 0}\n"
                    "evidence_logs: []\nfindings: [{severity: resolved, where: x, what: y}]\n"
                    "tests_added: []\nledger_issues: []\nquirk_tickets: []\n")
        r = self.validate({"TC-14.afs-verifier.yaml": verifier})
        self.assertIn("verdict", r.stderr)
        self.assertIn("gates/mutation_changed", r.stderr)
        self.assertIn("findings/0/severity", r.stderr)
        fixed = (verifier.replace("verdict: passed", "verdict: pass")
                 .replace("mutation_changed: n/a", "'mutation_changed': 'n/a: covered by the builder run'")
                 .replace("severity: resolved", "severity: minor"))
        r = self.validate({"TC-14.afs-verifier.yaml": fixed})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_ci_check_wants_a_changed_return_file_for_the_closed_issue(self):
        with tempfile.TemporaryDirectory() as t:
            repo = pathlib.Path(t)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
            git(repo, "checkout", "-q", "-b", "copilot/tc-02")
            self.assertEqual(crc.changed_return_files("main", repo), [])
            self.assertFalse(crc.check("Fixes #22", [], repo)[0])
            (repo / ".migration/returns").mkdir(parents=True)
            (repo / ".migration/returns/TC-02.afs-migrator.yaml").write_text(RETURN)
            git(repo, "add", "-A")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "work")
            files = crc.changed_return_files("main", repo)
            self.assertEqual(files, [".migration/returns/TC-02.afs-migrator.yaml"])
            self.assertTrue(crc.check("Fixes #22", files, repo)[0])
            ok, msg = crc.check("Fixes #23", files, repo)
            self.assertFalse(ok)
            self.assertIn("#23", msg)
            # A fix or Verifier on its own issue (#147, a sub-issue of ticket #22) names the ticket.
            parent = {"147": "22"}.get
            self.assertTrue(crc.check("Fixes #147", files, repo, parent_of=parent)[0], "the parent ticket counts")
            self.assertFalse(crc.check("Fixes #148", files, repo, parent_of=parent)[0], "no parent: no match")

    def test_pasted_contract_is_detected(self):
        self.assertTrue(crc.pasted_contract("Done.\n\n```yaml\n" + RETURN + "```\n"))
        self.assertFalse(crc.pasted_contract("Return file: `.migration/returns/TC-02.afs-migrator.yaml`"))
        self.assertFalse(crc.pasted_contract("```yaml\nfoo: 1\n```"))

    def test_only_agent_prs_are_checked(self):
        self.assertFalse(crc.is_agent_pr({"head": {"ref": "harness/x"}, "user": {"login": "martins-vds"}}))
        self.assertTrue(crc.is_agent_pr({"head": {"ref": "copilot/tc-03"}, "user": {"login": "Copilot"}}))


class SupersededReturnTest(unittest.TestCase):
    PATH = ".migration/returns/TC-02.afs-migrator.yaml"
    PR = "https://github.com/martins-vds/ai-factory-pilot-target/pull/38"
    LATEST = RETURN.replace("#22", "#23").replace("#38", "#39")

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = pathlib.Path(temp.name)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-q", "--allow-empty", "-m", "base")
        git(self.repo, "checkout", "-q", "-b", "copilot/work")

    def commit(self, text):
        path = self.repo / self.PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "return")

    def check(self, body="Fixes #22", **kwargs):
        return crc.check(body, crc.changed_return_files("main", self.repo), self.repo,
                         base="main", pr_url=self.PR, **kwargs)

    def revision(self, ref):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", ref], text=True).strip()

    def actions_event_result(self, head, base):
        event = self.repo / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "head": {"ref": "copilot/work", "sha": head},
            "base": {"ref": "main", "sha": base},
            "body": "Fixes #22", "html_url": self.PR,
        }}), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(ROOT / "tools/check_return_contract.py"),
             "--base", "main", "--event", str(event)], cwd=self.repo,
            env={**os.environ, "GITHUB_REPOSITORY": ""},
            capture_output=True, text=True,
        )

    def test_superseded_return_preserves_this_prs_attribution(self):
        self.commit(RETURN)
        self.commit(self.LATEST)
        ok, message = self.check()
        self.assertTrue(ok, message)
        self.assertIn("superseded attribution", message)
        self.assertIn(self.PATH + "@", message)
        self.assertIn("not a passing verdict", message)
        self.assertEqual((self.repo / self.PATH).read_text(), self.LATEST)
        self.assertTrue(self.check("Fixes #147", parent_of={"147": "22"}.get)[0])

    def test_cli_passes_event_identity_and_base_to_history_check(self):
        self.commit(RETURN)
        self.commit(self.LATEST)
        event = self.repo / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "head": {"ref": "copilot/work", "sha": self.revision("HEAD")},
            "base": {"ref": "main", "sha": self.revision("main")},
            "body": "Fixes #22", "html_url": self.PR,
        }}), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/check_return_contract.py"),
             "--base", "main", "--event", str(event)], cwd=self.repo,
            env={**os.environ, "GITHUB_REPOSITORY": ""}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("superseded attribution", result.stdout)
        self.assertIn("AFS-TOOL check_return_contract.py exit=0", result.stderr)

    def advance_main(self):
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "later on main")
        git(self.repo, "checkout", "-q", "copilot/work")

    def test_cli_accepts_a_base_that_moved_on_since_the_event(self):
        """Pilot #243, #229, #260: a merge to main after the PR's last event must not fail every open PR."""
        self.commit(RETURN)
        self.commit(self.LATEST)
        stale = self.revision("main")
        self.advance_main()
        result = self.actions_event_result(self.revision("HEAD"), stale)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("base moved on since the PR's last event", result.stdout)

    def test_cli_still_rejects_a_base_the_event_commit_is_not_part_of(self):
        self.commit(RETURN)
        unrelated = self.revision("HEAD")             # the PR's own head is not part of main's history
        result = self.actions_event_result(self.revision("HEAD"), unrelated)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not resolve to event base.sha", result.stdout)

    def stacked_event(self, base_ref):
        event = self.repo / "event.json"
        event.write_text(json.dumps({"repository": {"default_branch": "main"}, "pull_request": {
            "head": {"ref": "copilot/fix", "sha": self.revision("HEAD")},
            "base": {"ref": base_ref, "sha": self.revision(base_ref)},
            "body": "Fixes #320", "html_url": "https://github.com/martins-vds/ai-factory-pilot-target/pull/321",
        }}), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(ROOT / "tools/check_return_contract.py"), "--base", base_ref, "--event", str(event)],
            cwd=self.repo, env={**os.environ, "GITHUB_REPOSITORY": ""}, capture_output=True, text=True)

    def test_stacked_pr_needs_a_return_but_not_its_own_identity(self):
        """Pilot BK-05A: a fix session on another PR's branch can't name a PR that doesn't exist yet."""
        self.commit(RETURN)                                   # the work PR's return, naming #38
        git(self.repo, "branch", "copilot/verify")
        git(self.repo, "checkout", "-q", "-b", "copilot/fix")
        self.commit(self.LATEST)                              # the fix session's edit names #39, not #321
        result = self.stacked_event("copilot/verify")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checked on the PR into main", result.stdout)

    def test_stacked_pr_without_a_return_still_fails(self):
        self.commit(RETURN)
        git(self.repo, "branch", "copilot/verify")
        git(self.repo, "checkout", "-q", "-b", "copilot/fix")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "no return")
        result = self.stacked_event("copilot/verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no return file in this PR", result.stdout)

    def test_cli_fails_explicitly_when_event_shas_are_missing(self):
        self.commit(RETURN)
        event = self.repo / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "head": {"ref": "copilot/work"}, "base": {"ref": "main"},
            "body": "Fixes #22", "html_url": self.PR,
        }}), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/check_return_contract.py"),
             "--base", "main", "--event", str(event)], cwd=self.repo,
            env={**os.environ, "GITHUB_REPOSITORY": ""},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must include head.sha and base.sha", result.stdout)

    def test_event_pr_must_match_the_completed_return_it_owns(self):
        self.commit(RETURN.replace("#38", "#40"))
        ok, message = self.check()
        self.assertFalse(ok)
        self.assertIn("must identify this PR", message)

    def test_one_correct_return_does_not_attest_another_new_wrong_pr_return(self):
        self.commit(RETURN)
        other = self.repo / ".migration/returns/TC-03.afs-migrator.yaml"
        other.write_text(RETURN.replace("TC-02", "TC-03").replace("#38", "#40"), encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "add another return directly on this PR")
        ok, message = self.check()
        self.assertFalse(ok, message)
        self.assertIn("TC-03.afs-migrator.yaml", message)

    def test_superseded_proof_does_not_excuse_an_unrelated_new_wrong_pr_return(self):
        self.commit(RETURN)
        self.commit(self.LATEST)
        other = self.repo / ".migration/returns/TC-03.afs-migrator.yaml"
        other.write_text(RETURN.replace("TC-02", "TC-03").replace("#22", "#24").replace("#38", "#40"),
                         encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "add unrelated return after superseding the first")
        ok, message = self.check()
        self.assertFalse(ok, message)
        self.assertIn("TC-03.afs-migrator.yaml", message)

    def test_stacked_pr_does_not_revalidate_inherited_return_identity(self):
        self.commit(RETURN)
        git(self.repo, "branch", "work-base")
        git(self.repo, "checkout", "-q", "-b", "copilot/verifier")
        verifier_path = ".migration/returns/TC-02.afs-verifier.yaml"
        verifier = (
            "role: afs-verifier\nticket: TC-02\nissue: martins-vds/ai-factory-pilot-target#34\n"
            "pr: martins-vds/ai-factory-pilot-target#61\nverdict: pass\n"
            "gates: {build: 0, behavior: 0, idiom: 0, crap: 0, mutation_changed: 1.0, regression: 0}\n"
            "evidence_logs: []\nfindings: []\ntests_added: []\nledger_issues: []\nquirk_tickets: []\n"
        )
        path = self.repo / verifier_path
        path.write_text(verifier, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "verifier return")
        files = crc.changed_return_files("work-base", self.repo)
        self.assertEqual(files, [verifier_path])
        ok, message = crc.check(
            "Fixes #34", files, self.repo, base="work-base",
            pr_url="https://github.com/martins-vds/ai-factory-pilot-target/pull/61",
        )
        self.assertTrue(ok, message)

    def test_default_branch_pr_preserves_a_merged_childs_original_pr(self):
        git(self.repo, "checkout", "-q", "-b", "completed-child")
        self.commit(RETURN.replace("#38", "#61"))
        git(self.repo, "checkout", "-q", "copilot/work")
        own = self.repo / ".migration/returns/TC-02.afs-program-orchestrator.yaml"
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text(
            "role: afs-program-orchestrator\nticket: TC-02\n"
            "issue: martins-vds/ai-factory-pilot-target#22\nphase: 5\n"
            "decisions: []\ndispatched: []\nawaiting_human: []\nnext_step: continue\n",
            encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "coordinator owns only its own return")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "merge", "--no-ff", "-qm", "integrate completed child", "completed-child")
        ok, message = self.check()
        self.assertTrue(ok, message)

    def test_parent_edit_after_child_merge_is_not_mistaken_for_inheritance(self):
        git(self.repo, "checkout", "-q", "-b", "completed-child")
        self.commit(RETURN.replace("#38", "#61"))
        git(self.repo, "checkout", "-q", "copilot/work")
        own = self.repo / ".migration/returns/TC-02.afs-program-orchestrator.yaml"
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text(
            "role: afs-program-orchestrator\nticket: TC-02\n"
            "issue: martins-vds/ai-factory-pilot-target#22\nphase: 5\n"
            "decisions: []\ndispatched: []\nawaiting_human: []\nnext_step: continue\n",
            encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "coordinator owns only its own return")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "merge", "--no-ff", "-qm", "integrate completed child", "completed-child")
        inherited = self.repo / self.PATH
        inherited.write_text(inherited.read_text().replace("#61", "#62"), encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "change the child return on the parent PR")
        ok, message = self.check()
        self.assertFalse(ok, message)
        self.assertIn("TC-02.afs-migrator.yaml", message)

    def test_actions_synthetic_merge_uses_event_head_for_owned_return_identity(self):
        self.commit(RETURN.replace("#38", "#40"))
        head = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        base = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "main"], text=True).strip()
        git(self.repo, "checkout", "-q", "-b", "actions-test-merge", "main")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "merge", "--no-ff", "-qm", "GitHub Actions test merge", "copilot/work")
        result = self.actions_event_result(head, base)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("must identify this PR", result.stdout)

    def test_actions_synthetic_merge_accepts_correct_event_owned_return(self):
        self.commit(RETURN)
        head = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        base = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "main"], text=True).strip()
        git(self.repo, "checkout", "-q", "-b", "actions-test-merge", "main")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "merge", "--no-ff", "-qm", "GitHub Actions test merge", "copilot/work")
        result = self.actions_event_result(head, base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actions_synthetic_merge_preserves_a_child_return_inherited_by_event_head(self):
        base = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "main"], text=True).strip()
        git(self.repo, "checkout", "-q", "-b", "completed-child")
        self.commit(RETURN.replace("#38", "#61"))
        git(self.repo, "checkout", "-q", "copilot/work")
        own = self.repo / ".migration/returns/TC-02.afs-program-orchestrator.yaml"
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text(
            "role: afs-program-orchestrator\nticket: TC-02\n"
            "issue: martins-vds/ai-factory-pilot-target#22\nphase: 5\n"
            "decisions: []\ndispatched: []\nawaiting_human: []\nnext_step: continue\n",
            encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "coordinator owns only its own return")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "merge", "--no-ff", "-qm", "integrate completed child", "completed-child")
        head = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        git(self.repo, "checkout", "-q", "-b", "actions-test-merge", "main")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "merge", "--no-ff", "-qm", "GitHub Actions test merge", "copilot/work")
        result = self.actions_event_result(head, base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_pr_cannot_borrow_history(self):
        self.commit(RETURN.replace("#38", "#40"))
        self.commit(self.LATEST)
        self.assertFalse(self.check()[0])

    def test_wrong_repository_cannot_borrow_an_issue_number(self):
        self.commit(RETURN.replace("issue: martins-vds/ai-factory-pilot-target",
                                   "issue: other/repository"))
        self.commit(self.LATEST)
        self.assertFalse(self.check()[0])

    def test_wrong_ticket_or_role_cannot_borrow_history(self):
        for old in (RETURN.replace("ticket: TC-02", "ticket: TC-03"),
                    RETURN.replace("role: afs-migrator", "role: afs-verifier")):
            with self.subTest(old=old):
                self.commit(old)
                self.commit(self.LATEST)
                ok, message = self.check()
                self.assertFalse(ok)
                self.assertIn("ticket/role differs", message)

    def test_invalid_historical_schema_cannot_prove_attribution(self):
        self.commit(RETURN.replace("handoff: null\n", ""))
        self.commit(self.LATEST)
        ok, message = self.check()
        self.assertFalse(ok)
        self.assertIn("historical return is not schema-valid", message)

    def test_invalid_current_return_cannot_borrow_valid_history(self):
        self.commit(RETURN)
        self.commit(self.LATEST.replace("handoff: null\n", ""))
        ok, message = self.check()
        self.assertFalse(ok)
        self.assertIn("current return is not schema-valid", message)

    def test_malformed_historical_yaml_does_not_replace_valid_proof(self):
        self.commit(RETURN)
        self.commit("issue: [\n")
        self.commit(self.LATEST)
        self.assertTrue(self.check()[0])

    def test_base_only_return_cannot_prove_attribution(self):
        git(self.repo, "checkout", "-q", "main")
        self.commit(RETURN)
        git(self.repo, "checkout", "-q", "copilot/work")
        git(self.repo, "merge", "--ff-only", "main")
        self.commit(self.LATEST)
        self.assertFalse(self.check()[0])

    def test_unrelated_branch_cannot_prove_attribution(self):
        git(self.repo, "checkout", "-q", "-b", "unrelated", "main")
        self.commit(RETURN)
        git(self.repo, "checkout", "-q", "copilot/work")
        self.commit(self.LATEST)
        self.assertFalse(self.check()[0])

    def test_deleted_return_cannot_prove_attribution(self):
        self.commit(RETURN)
        (self.repo / self.PATH).unlink()
        path = self.repo / ".migration/returns/TC-03.afs-migrator.yaml"
        path.write_text(self.LATEST.replace("TC-02", "TC-03"), encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "replace")
        self.assertFalse(self.check()[0])


class ShallowHistorySetupTest(unittest.TestCase):
    def ancestry_preflight(self):
        skill = (ROOT / "skills/afs-setup-check/SKILL.md").read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^# BEGIN AFS target ancestry preflight\n(.*?)^# END AFS target ancestry preflight$",
            skill,
        )
        self.assertIsNotNone(match, "setup skill must bracket the executable ancestry preflight")
        return skill, match.group(1)

    def run_preflight(self, repo, script):
        return subprocess.run(
            ["bash", "-c", script + '\nprintf "VALIDATION_SENTINEL_REACHED\\n"\n'],
            cwd=repo, capture_output=True, text=True,
        )

    def test_setup_ancestry_preflight_is_executable_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            origin = root / "origin"
            origin.mkdir()
            git(origin, "init", "-q", "-b", "main")
            (origin / "history.txt").write_text("first\n", encoding="utf-8")
            git(origin, "add", "history.txt")
            git(origin, "-c", "user.name=test", "-c", "user.email=test@example.com",
                "commit", "-qm", "first")
            (origin / "history.txt").write_text("first\nsecond\n", encoding="utf-8")
            git(origin, "add", "history.txt")
            git(origin, "-c", "user.name=test", "-c", "user.email=test@example.com",
                "commit", "-qm", "second")
            skill, preflight = self.ancestry_preflight()
            self.assertIn('input "is not present" without check 4', skill)

            shallow = root / "shallow"
            git(root, "clone", "-q", "--depth", "1", origin.as_uri(), str(shallow))
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(shallow), "rev-parse", "--is-shallow-repository"], text=True).strip(),
                "true")
            prepared = self.run_preflight(shallow, preflight)
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            self.assertIn("VALIDATION_SENTINEL_REACHED", prepared.stdout)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(shallow), "rev-parse", "--is-shallow-repository"], text=True).strip(),
                "false")

            complete = root / "complete"
            git(root, "clone", "-q", origin.as_uri(), str(complete))
            git(complete, "remote", "remove", "origin")
            no_op = self.run_preflight(complete, preflight)
            self.assertEqual(no_op.returncode, 0, no_op.stdout + no_op.stderr)
            self.assertIn("VALIDATION_SENTINEL_REACHED", no_op.stdout)

            missing_origin = root / "missing-origin"
            git(root, "clone", "-q", "--depth", "1", origin.as_uri(), str(missing_origin))
            git(missing_origin, "remote", "remove", "origin")
            unavailable = self.run_preflight(missing_origin, preflight)
            self.assertNotEqual(unavailable.returncode, 0)
            self.assertNotIn("VALIDATION_SENTINEL_REACHED", unavailable.stdout)
            self.assertIn("setup is blocked", unavailable.stdout)

            shallow_origin = root / "shallow-origin.git"
            git(root, "clone", "-q", "--bare", "--depth", "1", origin.as_uri(), str(shallow_origin))
            remains_shallow = root / "remains-shallow"
            git(root, "clone", "-q", "--depth", "1", shallow_origin.as_uri(), str(remains_shallow))
            still_shallow = self.run_preflight(remains_shallow, preflight)
            self.assertNotEqual(still_shallow.returncode, 0)
            self.assertNotIn("VALIDATION_SENTINEL_REACHED", still_shallow.stdout)
            self.assertIn("remains shallow", still_shallow.stdout)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(remains_shallow), "rev-parse", "--is-shallow-repository"],
                    text=True).strip(),
                "true")

            not_git = root / "not-git"
            not_git.mkdir()
            outside_git = self.run_preflight(not_git, preflight)
            self.assertNotEqual(outside_git.returncode, 0)
            self.assertNotIn("VALIDATION_SENTINEL_REACHED", outside_git.stdout)
            self.assertIn("cannot inspect target Git history", outside_git.stdout)

    def test_inherited_null_pr_return_passes_after_required_history_is_prepared(self):
        return_text = """role: afs-verifier
ticket: T-1
issue: example/target#1
pr: null
verdict: blocked
gates:
  build: "n/a: setup did not run"
  behavior: "n/a: setup did not run"
  idiom: "n/a: setup did not run"
  crap: "n/a: setup did not run"
  mutation_changed: "n/a: setup did not run"
  regression: "n/a: setup did not run"
evidence_logs: []
findings: []
tests_added: []
ledger_issues: []
quirk_tickets: []
"""
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            origin, clone = root / "origin", root / "clone"
            origin.mkdir()
            git(origin, "init", "-q", "-b", "main")
            tools = origin / ".migration/harness/tools"
            returns = origin / ".migration/returns"
            tools.mkdir(parents=True)
            returns.mkdir(parents=True)
            validate = (ROOT / "tools/validate.py").read_text(encoding="utf-8")
            (tools / "validate.py").write_text(
                validate.replace('PR_ATTRIBUTION_RULE_V1 = "PR_ATTRIBUTION_RULE_V1"',
                                 'PR_ATTRIBUTION_RULE_V1 = "OLD_RULE_MARKER"'),
                encoding="utf-8")
            shutil.copyfile(ROOT / "tools/afs_trace.py", tools / "afs_trace.py")
            return_path = returns / "T-1.afs-verifier.yaml"
            return_path.write_text(return_text, encoding="utf-8")
            git(origin, "add", "-A")
            git(origin, "-c", "user.name=test", "-c", "user.email=test@example.com",
                "commit", "-qm", "historical return")
            (tools / "validate.py").write_text(validate, encoding="utf-8")
            git(origin, "add", str(tools / "validate.py"))
            git(origin, "-c", "user.name=test", "-c", "user.email=test@example.com",
                "commit", "-qm", "introduce PR attribution rule")
            git(clone.parent, "clone", "-q", "--depth", "1", origin.as_uri(), str(clone))

            def validate_state():
                return subprocess.run(
                    [sys.executable, str(clone / ".migration/harness/tools/validate.py"),
                     str(clone / ".migration"), "--schemas", str(ROOT / "schemas")],
                    capture_output=True, text=True)

            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(clone), "rev-parse", "--is-shallow-repository"], text=True).strip(),
                "true")
            before_fetch = validate_state()
            self.assertEqual(before_fetch.returncode, 1)
            self.assertIn("the clone's history is shallow", before_fetch.stderr)

            setup_skill, preflight = self.ancestry_preflight()
            self.assertIn("write a blocking handoff", setup_skill)
            prepared = self.run_preflight(clone, preflight)
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            self.assertIn("VALIDATION_SENTINEL_REACHED", prepared.stdout)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(clone), "rev-parse", "--is-shallow-repository"], text=True).strip(),
                "false")
            after_fetch = validate_state()
            self.assertEqual(after_fetch.returncode, 0, after_fetch.stderr)

            inherited = clone / ".migration/returns/T-1.afs-verifier.yaml"
            inherited.write_text(inherited.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
            edited = validate_state()
            self.assertEqual(edited.returncode, 1)
            self.assertIn("finished return requires a meaningful PR reference", edited.stderr)
            git(clone, "checkout", "--", ".migration/returns/T-1.afs-verifier.yaml")

            new_return = clone / ".migration/returns/T-2.afs-verifier.yaml"
            new_return.write_text(return_text.replace("T-1", "T-2"), encoding="utf-8")
            added = validate_state()
            self.assertEqual(added.returncode, 1)
            self.assertIn("finished return requires a meaningful PR reference", added.stderr)


if __name__ == "__main__":
    unittest.main()
