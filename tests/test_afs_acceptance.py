"""Durable acceptance executes real afs-run records in isolated repositories; gates are small stubs."""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("afs_acceptance", str(ROOT / "tools/afs-acceptance"))
spec = importlib.util.spec_from_loader("afs_acceptance", loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
RESULT = "AFS-RESULT gate=mutation score=0.900 threshold=0.8 killed=9 survived=1 files=3 base=all"


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        self.tools = self.repo / ".migration/harness/tools"
        self.tools.mkdir(parents=True)
        for name in ("afs-acceptance", "afs-run", "afs_trace.py"):
            shutil.copyfile(ROOT / "tools" / name, self.tools / name)
        for name in ("check_graph_fresh.py", "graph_gate.py", "check_runtime.py", "check_installed.py", "afs-services"):
            (self.tools / name).write_text('print("AFS-RESULT gate=graph status=passed")\n')
        (self.repo / ".gitignore").write_text(".migration/runs/\n")
        (self.repo / "src").mkdir()
        (self.repo / "src/app.py").write_text("value = 1\n")
        self.profile = {"target": {"repo": "example/target"},
                        "gates": {gate: ["echo passed"] for gate in m.GATES},
                        "thresholds": {"mutation_score_min": 0.8}}
        self.profile["gates"]["mutation_full"] = [f"echo '{RESULT}'"]
        (self.repo / ".migration/source.lock").write_text("sha: source-pin\n")
        (self.repo / ".migration/harness/installed.json").write_text(json.dumps({"harness_commit": "a" * 40}))
        self.save_profile()
        self.git("init", "-q")
        self.git("config", "user.email", "acceptance@example.invalid")
        self.git("config", "user.name", "Acceptance fixture")
        self.commit()
        self.out = self.repo / ".migration/runs/acceptance-123-1"
        self.env = {**os.environ, "GITHUB_SHA": self.sha, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_REPOSITORY": "example/target", "GITHUB_SERVER_URL": "https://github.com"}
        # ADR-0035: the workflow's graph job builds the target graph for this commit (gitignored download).
        self.build = self.repo / ".migration/runs/graph-build"
        self.build.mkdir(parents=True)
        (self.build / "SNAPSHOT.txt").write_text(f"side: target\ntarget_commit: {self.sha}\n"
                                                 f"tree.src: {self.git('rev-parse', 'HEAD:src')}\n")
        (self.build / "knowledge-graph.json").write_text("{}")
        self.env["AFS_GRAPH_TARGET_BUILD"] = str(self.build)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo).decode().strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.sha = self.git("rev-parse", "HEAD")

    def save_profile(self):
        (self.repo / ".migration/profile.yaml").write_text(yaml.safe_dump(self.profile))

    def configure(self, gate, command):
        self.profile["gates"][gate] = [command]
        self.save_profile()
        self.commit()
        self.env["GITHUB_SHA"] = self.sha

    def execute(self, *args):
        return subprocess.run([sys.executable, str(self.tools / "afs-acceptance"), *args],
                              cwd=self.repo, env=self.env, capture_output=True, text=True)

    def run_gates(self):
        return self.execute("run", "--ticket", "T-1", "--out", str(self.out))

    def verify(self, sha=None, run_id="123", attempt="1"):
        return self.execute("verify", str(self.out), "--commit", sha or self.sha,
                            "--run-id", run_id, "--attempt", attempt)

    def result(self):
        return json.loads((self.out / "result.json").read_text())

    def write_result(self, value):
        (self.out / "result.json").write_text(json.dumps(value))

    def test_complete_run_exact_commands_and_portable_artifact(self):
        run = self.run_gates()
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        result = self.result()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["steps"]), 11)
        self.assertEqual(result["steps"][-1]["command"], ["bash", "-c", self.profile["gates"]["mutation_full"][0]])
        self.assertEqual(result["steps"][-1]["result"]["killed"], "9")
        self.assertFalse((self.repo / ".migration/evidence/runs/T-1.md").exists())
        self.assertTrue((self.out / "journals/T-1.md").exists())
        # A downloaded artifact no longer has the runner's absolute filesystem location.
        original = self.out
        self.out = self.repo / ".migration/runs/download"
        original.rename(self.out)
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("status=verified", verified.stdout)
        self.assertNotEqual(self.run_gates().returncode, 0, "existing artifacts must not be overwritten")

    def publish(self, origin):
        """What the workflow's publish job does: the artifact's files as the tree of afs/acceptance/<run>-<attempt>."""
        work = pathlib.Path(self.tmp.name + "-publish")
        shutil.copytree(self.out, work)
        self.addCleanup(shutil.rmtree, work, True)
        for cmd in (["init", "-q", "-b", "afs/acceptance/123-1"], ["add", "-A"],
                    ["-c", "user.name=bot", "-c", "user.email=bot@x", "commit", "-qm", "evidence"],
                    ["push", "-q", str(origin), "HEAD:refs/heads/afs/acceptance/123-1"]):
            subprocess.run(["git", *cmd], cwd=work, check=True, capture_output=True)

    def test_evidence_fetched_from_the_publish_branch_verifies_like_the_artifact(self):
        # pilot BK-ACCEPT: Copilot's firewall blocked the artifact's storage host; git reaches the branch
        self.assertEqual(self.run_gates().returncode, 0)
        origin = pathlib.Path(self.tmp.name + "-origin.git")
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        self.addCleanup(shutil.rmtree, origin, True)
        self.git("remote", "add", "origin", str(origin))
        self.publish(origin)
        shutil.rmtree(self.out)
        self.out = self.repo / ".migration/runs/fetched"
        fetched = self.execute("fetch", "--run-id", "123", "--attempt", "1", "--dest", str(self.out))
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("status=verified", verified.stdout)
        again = self.execute("fetch", "--run-id", "123", "--attempt", "1", "--dest", str(self.out))
        self.assertEqual(again.returncode, 2, "a non-empty destination is refused")
        missing = self.execute("fetch", "--run-id", "124", "--attempt", "1", "--dest", str(self.repo / ".migration/runs/x"))
        self.assertEqual(missing.returncode, 2)
        self.assertIn("no evidence branch afs/acceptance/124-1", missing.stderr)

    def test_the_workflow_publishes_evidence_from_a_write_job_that_runs_no_target_code(self):
        text = (ROOT / "templates/target/afs-acceptance.yml").read_text()
        publish = text.split("\n  publish:\n", 1)[1]
        self.assertIn("needs: acceptance", publish)
        self.assertIn("afs/acceptance/${{{{ github.run_id }}}}-${{{{ github.run_attempt }}}}", publish)
        self.assertNotIn("actions/checkout", publish, "the write job never checks out or runs target code")
        acceptance = text.split("\n  acceptance:\n", 1)[1].split("\n  publish:\n", 1)[0]
        self.assertNotIn("contents: write", acceptance, "the gate job stays read-only")

    def test_the_run_gates_its_own_target_graph_for_its_commit(self):
        run = self.run_gates()
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        graph = self.result()["target_graph"]
        self.assertEqual(graph["dir"], "graph/target/full")
        self.assertIn("graph/target/full/SNAPSHOT.txt", self.result()["files"])
        self.assertEqual(self.result()["plan"][5]["command"][-1], "--enforce-ownership")

    def test_no_graph_or_a_graph_of_other_code_is_refused(self):
        env = dict(self.env)
        del self.env["AFS_GRAPH_TARGET_BUILD"]
        self.assertIn("no target graph built", self.run_gates().stderr)
        self.env = env
        (self.build / "SNAPSHOT.txt").write_text("tree.src: " + "0" * 40 + "\n")
        self.assertIn("doesn't describe", self.run_gates().stderr)

    def test_auditor_report_commit_can_advance_without_invalidating_execution_inputs(self):
        self.assertEqual(self.run_gates().returncode, 0)
        original_sha = self.sha
        report = self.repo / ".migration/evidence/slice/report.md"
        report.parent.mkdir(parents=True)
        report.write_text("Independent report\n")
        handoff = self.repo / ".migration/handoffs/T-1.md"
        handoff.parent.mkdir(parents=True)
        handoff.write_text("Blocked handoff\n")
        archive = self.repo / ".migration/evidence/acceptance-runs/123-1.json"
        archive.parent.mkdir(parents=True)
        shutil.copyfile(self.out / "result.json", archive)
        self.commit()
        self.assertEqual(self.verify(sha=original_sha).returncode, 0)
        (self.repo / "src/app.py").write_text("value = 2\n")
        self.assertNotEqual(self.verify(sha=original_sha).returncode, 0, "dirty inputs invalidate evidence")
        self.commit()
        self.assertNotEqual(self.verify(sha=original_sha).returncode, 0, "changed code invalidates evidence")

    def test_evidence_fixtures_are_execution_inputs_not_report_exemptions(self):
        fixture = self.repo / ".migration/evidence/slice/goldens.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text('{"expected": 1}\n')
        self.commit()
        self.env["GITHUB_SHA"] = self.sha
        self.assertEqual(self.run_gates().returncode, 0)
        fixture.write_text('{"expected": 2}\n')
        self.commit()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_stale_survivor_report_is_not_attributed_to_this_run(self):
        survivor = self.repo / ".migration/evidence/mutants/T-1.md"
        survivor.parent.mkdir(parents=True)
        survivor.write_text("Old completed run\n")
        self.commit()
        self.env["GITHUB_SHA"] = self.sha
        self.assertEqual(self.run_gates().returncode, 0)
        self.assertFalse((self.out / "mutants.md").exists())

    def test_failed_gate_is_preserved_and_full_mutation_is_not_run(self):
        self.configure("tests", "echo intentional-failure >&2; exit 7")
        run = self.run_gates()
        self.assertEqual(run.returncode, 7, run.stderr)
        result = self.result()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["steps"][-1]["name"], "tests-0")
        log = self.out / result["steps"][-1]["log"]
        self.assertIn("intentional-failure", log.read_text())
        self.assertNotEqual(self.verify().returncode, 0)

    def test_partial_na_and_low_mutation_are_not_passes(self):
        cases = [
            "AFS-RESULT gate=mutation score=n/a reason=no-files base=all",
            RESULT.replace("base=all", "base=main"),
            RESULT.replace("killed=9 survived=1", "killed=1 survived=9"),
            RESULT.replace("files=3", "files=0"),
            RESULT.replace("score=0.900", "score=nan"),
            "unfinished mutation",
        ]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(m.EvidenceError):
                    m.full_mutation(m.result_fields(self.make_log(text)), 0.8)
        self.configure("mutation_full", "echo unfinished-mutation")
        self.assertEqual(self.run_gates().returncode, 2)
        self.assertEqual(self.result()["status"], "failed")
        self.assertNotEqual(self.verify().returncode, 0)

    def make_log(self, text):
        path = self.repo / ".migration/runs/unit.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n")
        return path

    def test_all_profile_commands_are_required(self):
        self.profile["gates"]["mutation_full"] = []
        self.save_profile()
        self.commit()
        self.env["GITHUB_SHA"] = self.sha
        run = self.run_gates()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("nonempty command list", run.stderr)

    def test_exact_sha_and_safe_ticket_are_required(self):
        self.env["GITHUB_SHA"] = "b" * 40
        self.assertNotEqual(self.run_gates().returncode, 0)
        self.env["GITHUB_SHA"] = self.sha
        for ticket in ("../../bad", "T-1.", "T-1_"):
            run = self.execute("run", "--ticket", ticket, "--out", str(self.out))
            self.assertNotEqual(run.returncode, 0, ticket)
        self.assertFalse(self.out.exists())

    def test_untracked_source_is_not_silently_executed_as_the_recorded_revision(self):
        (self.repo / "src/untracked.py").write_text("value = 2\n")
        run = self.run_gates()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("untracked execution inputs", run.stderr)

    def test_stale_identity_inputs_and_modified_or_missing_logs_are_rejected(self):
        self.assertEqual(self.run_gates().returncode, 0)
        self.assertNotEqual(self.verify(sha="c" * 40).returncode, 0)
        self.assertNotEqual(self.verify(run_id="999").returncode, 0)
        self.assertNotEqual(self.verify(attempt="2").returncode, 0)
        log = self.out / self.result()["steps"][-1]["log"]
        original = log.read_bytes()
        log.write_text("tampered\n")
        self.assertNotEqual(self.verify().returncode, 0)
        log.write_bytes(original)
        log.unlink()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_artifact_repository_must_match_profile(self):
        self.assertEqual(self.run_gates().returncode, 0)
        result = self.result()
        result["workflow"]["GITHUB_REPOSITORY"] = "other/target"
        self.write_result(result)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_missing_gate_and_incomplete_hash_inventory_are_rejected(self):
        self.assertEqual(self.run_gates().returncode, 0)
        result = self.result()
        result["steps"].pop()
        self.write_result(result)
        self.assertNotEqual(self.verify().returncode, 0)
        result["files"] = {}
        self.write_result(result)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_profile_must_match(self):
        self.assertEqual(self.run_gates().returncode, 0)
        self.profile["thresholds"]["mutation_score_min"] = 0.7
        self.save_profile()
        self.assertNotEqual(self.verify().returncode, 0)
        self.commit()
        self.assertNotEqual(self.verify().returncode, 0)

    def test_installed_pin_and_source_lock_must_match(self):
        self.assertEqual(self.run_gates().returncode, 0)
        for path in (".migration/harness/installed.json", ".migration/source.lock"):
            with self.subTest(path=path):
                p = self.repo / path
                original = p.read_text()
                p.write_text(original + "\n")
                self.assertNotEqual(self.verify().returncode, 0)
                p.write_text(original)

    def test_recomputed_hashes_cannot_hide_missing_full_mutation_accounting(self):
        self.assertEqual(self.run_gates().returncode, 0)
        result = self.result()
        step = result["steps"][-1]
        log = self.out / step["log"]
        log.write_text("AFS-RESULT gate=mutation score=n/a base=all reason=interrupted\n")
        step["result"] = m.result_fields(log)
        step["record"]["bytes"] = len(log.read_bytes())
        step["record"]["lines"] = 1
        records_path = self.out / "logs/T-1/runs.jsonl"
        records = [json.loads(line) for line in records_path.read_text().splitlines()]
        records[-1] = step["record"]
        records_path.write_text("".join(json.dumps(r) + "\n" for r in records))
        m.write_result(self.out, result)
        check = self.verify()
        self.assertNotEqual(check.returncode, 0)
        self.assertIn("complete numeric result", check.stderr)

    def test_fresh_survivor_output_is_preserved(self):
        self.configure("mutation_full", "mkdir -p .migration/evidence/mutants; "
                       f"echo measured-survivors > .migration/evidence/mutants/T-1.md; echo '{RESULT}'")
        self.assertEqual(self.run_gates().returncode, 0)
        self.assertEqual((self.out / "mutants.md").read_text(), "measured-survivors\n")
        self.assertEqual(self.verify().returncode, 0)

    def test_cancellation_keeps_partial_log_but_never_completes_the_journal_row(self):
        self.configure("mutation_full",
                       f"""{sys.executable} -c 'import time; print("started", flush=True); time.sleep(60)'""")
        process = subprocess.Popen(
            [sys.executable, str(self.tools / "afs-acceptance"), "run", "--ticket", "T-1", "--out", str(self.out)],
            cwd=self.repo, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (self.out / "result.json").exists():
                result = self.result()
                logs = list(self.out.glob("logs/T-1/*-mutation_full-0.log"))
                if result["steps"] and result["steps"][-1]["name"] == "mutation_full-0" \
                        and logs and "started" in logs[0].read_text():
                    break
            time.sleep(0.02)
        else:
            self.fail("mutation step did not start")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 143, stdout + stderr)
        result = self.result()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["steps"][-1]["status"], "interrupted")
        self.assertNotIn("result", result["steps"][-1])
        self.assertIn("started", next(self.out.glob("logs/T-1/*-mutation_full-0.log")).read_text())
        journal = (self.out / "journals/T-1.md").read_text()
        self.assertNotIn("| mutation_full-0 |", journal)
        self.assertNotEqual(self.verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
