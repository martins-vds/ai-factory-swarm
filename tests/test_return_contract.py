"""Return files: the generated schema, validate.py, and the CI check."""
import json
import pathlib
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
                .replace("handoff: null", "handoff: .migration/handoffs/TC-02.md"))
        r = self.validate({"TC-02.afs-migrator.yaml": text})
        self.assertNotIn("in a finished return", r.stderr)

    def test_legacy_returns_are_exempt(self):
        r = self.validate({"TC-02.afs-migrator.yaml": RETURN}, legacy=["TC-02.afs-migrator.yaml"])
        self.assertEqual(r.returncode, 0, r.stderr)

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


if __name__ == "__main__":
    unittest.main()
