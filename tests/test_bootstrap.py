"""Tests for tools/bootstrap.py and tools/check_installed.py. Offline: upstream fetches and `gh` are faked."""
import json
import multiprocessing
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import bootstrap  # noqa: E402

PROFILE = ROOT / "templates/migration/profile.yaml"
CAPS = ROOT / "templates/migration/capabilities.yaml"
PACK = ROOT / "stacks/java-to-django.json"


def bootstrap_process(target, ready, release, pause_at, outcomes):
    original_publish = getattr(bootstrap, "publish_install", None)
    original_output = getattr(bootstrap, "_publish_output", None)
    count = 0

    def pause_publish(*args, **kwargs):
        ready.set()
        release.wait(30)
        return original_publish(*args, **kwargs)

    def pause_output(*args, **kwargs):
        nonlocal count
        result = original_output(*args, **kwargs)
        count += 1
        if count == 1:
            ready.set()
            release.wait(30)
        return result

    if pause_at == "before-publish":
        bootstrap.publish_install = pause_publish
    elif pause_at == "after-first-output":
        bootstrap._publish_output = pause_output
    try:
        bootstrap.bootstrap(target, PROFILE, CAPS, [PACK], offline=True)
    except BaseException as exc:
        outcomes.put(f"{type(exc).__name__}: {exc}")
    else:
        outcomes.put("ok")


def managed_snapshot(target):
    paths = (".github/skills", ".github/agents", ".github/workflows", ".github/hooks",
             ".github/copilot-instructions.md", ".migration/harness", ".migration/source.lock",
             ".migration/profile.yaml", ".migration/capabilities.yaml", ".migration/ledger",
             ".gitignore")
    snapshot = {}
    for rel in paths:
        path = target / rel
        snapshot[rel] = "directory" if path.is_dir() else "file" if path.is_file() else "missing"
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    snapshot[str(child.relative_to(target))] = child.read_bytes()
        elif path.is_file():
            snapshot[rel] = path.read_bytes()
    return snapshot


def fake_upstream():
    """One fake repo holding every upstream path of the lock and the stack pack."""
    repo = pathlib.Path(tempfile.mkdtemp())
    (repo / "LICENSE").write_text("MIT License (fake)\n")
    for lock in (json.loads((ROOT / "skills.lock.json").read_text()), json.loads(PACK.read_text())):
        for s in lock["skills"]:
            if s["install"] == "upstream":
                d = repo / s["path"]
                d.mkdir(parents=True, exist_ok=True)
                (d / "SKILL.md").write_text(f"---\nname: {s['name']}\ndescription: fake\n---\nbody\n")
    return repo


class BootstrapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = fake_upstream()
        cls._fetch = bootstrap.fetch
        bootstrap.fetch = lambda repo, commit, cache: cls.upstream

    @classmethod
    def tearDownClass(cls):
        bootstrap.fetch = cls._fetch
        shutil.rmtree(cls.upstream)

    def setUp(self):
        self.target = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.target)

    def run_bootstrap(self, caps=CAPS, **kw):
        return bootstrap.bootstrap(self.target, PROFILE, caps, [PACK], **kw)

    def caps_with_new_gap(self):
        doc = yaml.safe_load(CAPS.read_text())
        for c in doc["capabilities"]:
            if c["status"] == "gap":
                c["ticket"] = "new"
        p = self.target.parent / f"{self.target.name}-caps.yaml"
        p.write_text(yaml.safe_dump(doc, sort_keys=False))
        self.addCleanup(p.unlink)
        return p

    def test_installs_everything_and_passes_its_own_checks(self):
        r = self.run_bootstrap()
        lock = json.loads((ROOT / "skills.lock.json").read_text())
        self.assertEqual(r["skills"], len(lock["skills"]) + len(json.loads(PACK.read_text())["skills"]))
        self.assertEqual(r["agents"], 10)
        for f in [".migration/source.lock", ".migration/profile.yaml", ".migration/capabilities.yaml",
                  ".migration/harness/tools/afs-run", ".migration/harness/tools/check_stack_base.py",
                  ".migration/harness/tools/afs-acceptance",
                  ".migration/harness/installed.json",
                  ".github/hooks/rtk-rewrite.json", ".github/workflows/copilot-setup-steps.yml",
                  ".github/workflows/afs-harness-check.yml", ".github/skills/django-patterns/PROVENANCE.md",
                  ".github/skills/django-patterns/LICENSE", ".github/skills/afs-wayfinder/PROVENANCE.md"]:
            self.assertTrue((self.target / f).exists(), f)
        self.assertTrue(os.access(self.target / ".migration/harness/tools/afs-run", os.X_OK))
        for wf in ("copilot-setup-steps.yml", "afs-harness-check.yml", "afs-understand.yml", "afs-acceptance.yml"):
            doc = yaml.safe_load((self.target / ".github/workflows" / wf).read_text())
            self.assertIn("jobs", doc)
        self.assertIn("copilot-setup-steps", yaml.safe_load(
            (self.target / ".github/workflows/copilot-setup-steps.yml").read_text())["jobs"])
        checks = yaml.safe_load((self.target / ".github/workflows/afs-harness-check.yml").read_text())["jobs"]
        self.assertEqual(checks["stack-base"]["steps"][0]["with"]["fetch-depth"], 0)
        self.assertIn("check_stack_base.py", checks["stack-base"]["steps"][1]["run"])
        for job in ("harness", "return-contract", "gates"):
            self.assertEqual(checks[job]["needs"], "stack-base")
        installs = [s.get("run", "") for s in checks["return-contract"]["steps"]]
        self.assertTrue(any("pip install" in cmd and {"pyyaml", "jsonschema"} <= set(cmd.split())
                            for cmd in installs))
        closure = yaml.safe_load((self.target / ".github/workflows/afs-map-fog.yml").read_text())["jobs"]["rewalk"]
        self.assertEqual(closure["steps"][0]["with"]["fetch-depth"], 0)
        self.assertTrue(any("pip install" in s.get("run", "") and
                            {"pyyaml", "jsonschema"} <= set(s["run"].split()) for s in closure["steps"]))
        # ADR-0018: the workflows' Python is the profile's declared python-X.Y, not a harness default.
        prof = yaml.safe_load((self.target / ".migration/profile.yaml").read_text())
        want = next(s.split("-", 1)[1] for s in prof["target"]["stacks"]["backend"] if s.startswith("python-"))
        for wf in ("copilot-setup-steps.yml", "afs-harness-check.yml", "afs-acceptance.yml"):
            self.assertIn(f'python-version: "{want}"', (self.target / ".github/workflows" / wf).read_text())
        for cmd in (["python3", ".migration/harness/tools/check_installed.py"],
                    ["python3", ".migration/harness/tools/validate.py", ".migration"]):
            out = subprocess.run(cmd, cwd=self.target, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        lock_text = (self.target / ".migration/source.lock").read_text()
        self.assertIn("sha: c2df7607e3b6a997dd27eb2917bc33e4ec0f6692", lock_text)
        self.assertEqual((self.target / ".gitignore").read_text(), ".source/\n.migration/runs/\n")

    def test_acceptance_workflow_is_manual_durable_and_preserves_failed_evidence(self):
        self.run_bootstrap()
        text = (self.target / ".github/workflows/afs-acceptance.yml").read_text()
        doc = yaml.safe_load(text)
        # PyYAML's YAML 1.1 parser treats the Actions key "on" as True.
        self.assertEqual(set(doc[True]), {"workflow_dispatch"})
        self.assertEqual(doc["permissions"], {"contents": "read"})
        job = doc["jobs"]["acceptance"]
        self.assertEqual(job["timeout-minutes"], 360)
        run = next(s for s in job["steps"] if "afs-acceptance run" in s.get("run", ""))
        self.assertEqual(run["timeout-minutes"], 330)
        self.assertIn('--ticket "$AFS_ACCEPTANCE_TICKET"', run["run"])
        self.assertNotIn("${{ inputs.ticket }}", run["run"], "dispatch input is data, not shell source")
        upload = next(s for s in job["steps"] if s.get("uses") == "actions/upload-artifact@v4")
        self.assertEqual(upload["if"], "always()")
        self.assertTrue(upload["with"]["include-hidden-files"])
        self.assertIn("github.sha", upload["with"]["name"])
        checks = (self.target / ".github/workflows/afs-harness-check.yml").read_text()
        self.assertNotIn("mutation_full", checks, "ordinary per-PR gates remain unchanged")

    def test_instruction_blocks_preserve_team_content_and_are_idempotent(self):
        ci = self.target / ".github/copilot-instructions.md"
        ci.parent.mkdir(parents=True)
        ci.write_text("# Team notes\nKeep this.\n")
        self.run_bootstrap()
        first = ci.read_text()
        self.assertTrue(first.startswith("<!-- afs-instructions v"))
        self.assertIn("# Team notes\nKeep this.\n", first)
        self.assertLess(first.index("Keep this."), first.index("<!-- rtk-instructions v2 -->"))
        self.assertTrue(first.endswith("<!-- /rtk-instructions -->\n"))
        self.run_bootstrap()
        self.assertEqual(ci.read_text(), first)
        self.assertEqual(first.count("<!-- afs-instructions"), 1)

    def test_rerun_replaces_harness_owned_files(self):
        self.run_bootstrap()
        (self.target / ".github/skills/afs-ledger/SKILL.md").write_text("edited")
        (self.target / ".github/agents/afs-stale.agent.md").write_text("stale")
        (self.target / ".github/agents/team.agent.md").write_text("team agent")
        self.run_bootstrap()
        self.assertNotEqual((self.target / ".github/skills/afs-ledger/SKILL.md").read_text(), "edited")
        self.assertFalse((self.target / ".github/agents/afs-stale.agent.md").exists())
        self.assertTrue((self.target / ".github/agents/team.agent.md").exists())

    def test_concurrent_process_is_refused_with_lock_owner_pid(self):
        context = multiprocessing.get_context("fork")
        ready, release, outcomes = context.Event(), context.Event(), context.Queue()
        first = context.Process(target=bootstrap_process,
                                args=(self.target, ready, release, "before-publish", outcomes))
        first.start()
        self.addCleanup(lambda: first.is_alive() and first.kill())
        self.assertTrue(ready.wait(20), "first bootstrap did not reach staged publication")

        second_outcomes = context.Queue()
        second = context.Process(target=bootstrap_process,
                                 args=(self.target, context.Event(), context.Event(), None, second_outcomes))
        second.start()
        second.join(20)
        self.assertFalse(second.is_alive(), "competing bootstrap did not exit")
        result = second_outcomes.get(timeout=2)
        self.assertIn("BootstrapLockError", result)
        self.assertIn(str(first.pid), result)

        release.set()
        first.join(20)
        self.assertFalse(first.is_alive(), "first bootstrap did not finish")
        self.assertEqual(outcomes.get(timeout=2), "ok")

    def test_killed_staging_run_preserves_old_install_and_reports_stale_lock(self):
        self.run_bootstrap()
        before = managed_snapshot(self.target)
        context = multiprocessing.get_context("fork")
        ready, release = context.Event(), context.Event()
        process = context.Process(target=bootstrap_process,
                                  args=(self.target, ready, release, "before-publish", context.Queue()))
        process.start()
        self.addCleanup(lambda: process.is_alive() and process.kill())
        self.assertTrue(ready.wait(20), "bootstrap did not finish staging")
        process.kill()
        process.join(10)

        self.assertEqual(managed_snapshot(self.target), before)
        with self.assertRaisesRegex(bootstrap.BootstrapLockError, str(process.pid)):
            self.run_bootstrap(offline=True)
        lock_path = self.target / ".afs-bootstrap.lock"
        self.assertTrue(lock_path.exists())
        lock_path.unlink()
        self.run_bootstrap(offline=True)

    def test_publication_failure_rolls_back_all_managed_outputs(self):
        self.run_bootstrap()
        before = managed_snapshot(self.target)
        original = getattr(bootstrap, "_publish_output", None)
        count = 0

        def fail_after_one(*args, **kwargs):
            nonlocal count
            if count == 1:
                raise OSError("injected publication failure")
            count += 1
            return original(*args, **kwargs)

        with mock.patch.object(bootstrap, "_publish_output", fail_after_one):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "previous install was restored"):
                self.run_bootstrap(offline=True)
        self.assertEqual(managed_snapshot(self.target), before)

    def test_killed_publication_is_recovered_before_the_next_install(self):
        self.run_bootstrap()
        before = managed_snapshot(self.target)
        context = multiprocessing.get_context("fork")
        ready, release = context.Event(), context.Event()
        process = context.Process(target=bootstrap_process,
                                  args=(self.target, ready, release, "after-first-output", context.Queue()))
        process.start()
        self.addCleanup(lambda: process.is_alive() and process.kill())
        self.assertTrue(ready.wait(20), "bootstrap did not publish its first output")
        process.kill()
        process.join(10)
        self.assertNotEqual(managed_snapshot(self.target), before)

        (self.target / ".afs-bootstrap.lock").unlink()
        with bootstrap.bootstrap_lock(self.target):
            bootstrap.recover_interrupted_install(self.target)
        self.assertEqual(managed_snapshot(self.target), before)

    def test_rerun_from_the_targets_own_state(self):
        self.run_bootstrap()
        m = self.target / ".migration"
        before = (m / "profile.yaml").read_text()
        bootstrap.bootstrap(self.target, m / "profile.yaml", m / "capabilities.yaml", [PACK])
        self.assertEqual((m / "profile.yaml").read_text(), before)
        out = subprocess.run(["python3", ".migration/harness/tools/validate.py", ".migration"], cwd=self.target,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_check_installed_reports_drift(self):
        self.run_bootstrap()
        (self.target / ".github/skills/afs-ledger/SKILL.md").write_text("edited")
        (self.target / ".github/skills/afs-ledger/extra.md").write_text("new")
        (self.target / ".github/agents/afs-auditor.agent.md").unlink()
        out = subprocess.run(["python3", ".migration/harness/tools/check_installed.py"], cwd=self.target,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn("edited: .github/skills/afs-ledger/SKILL.md", out.stdout)
        self.assertIn("unexpected: .github/skills/afs-ledger/extra.md", out.stdout)
        self.assertIn("missing: .github/agents/afs-auditor.agent.md", out.stdout)

    def test_interpreter_caches_are_not_drift(self):
        self.run_bootstrap()
        cache = self.target / ".migration/harness/tools/__pycache__"
        cache.mkdir()
        (cache / "check_graph.cpython-313.pyc").write_bytes(b"x")
        out = subprocess.run(["python3", ".migration/harness/tools/check_installed.py"], cwd=self.target,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_new_gap_needs_the_issue_flag(self):
        with self.assertRaisesRegex(bootstrap.BootstrapError, "data-migration"):
            self.run_bootstrap(caps=self.caps_with_new_gap())
        self.assertFalse((self.target / ".github").exists())  # refused before writing anything

    def test_new_gap_becomes_an_issue_ref(self):
        log = self.target.parent / f"{self.target.name}-gh.log"
        fake = self.target.parent / f"{self.target.name}-gh"
        fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\n'
                        'case "$2" in */issues) echo https://github.com/martins-vds/ai-factory-pilot-target/issues/42;; '
                        '*/labels) [ "$3" = --paginate ] && echo ready-for-agent;; esac\nexit 0\n')
        fake.chmod(0o755)
        self.addCleanup(lambda: (fake.unlink(), log.unlink()))
        os.environ["AFS_GH"] = str(fake)
        self.addCleanup(os.environ.pop, "AFS_GH")
        r = self.run_bootstrap(caps=self.caps_with_new_gap(), create_gap_issues=True)
        self.assertEqual(r["issues_created"], ["martins-vds/ai-factory-pilot-target#42"])
        caps = yaml.safe_load((self.target / ".migration/capabilities.yaml").read_text())
        gap = [c for c in caps["capabilities"] if c["status"] == "gap"][0]
        self.assertEqual(gap["ticket"], "martins-vds/ai-factory-pilot-target#42")
        calls = log.read_text()
        self.assertIn("labels --method POST -f name=afs:capability-gap", calls)
        self.assertIn("labels/ready-for-agent --method PATCH", calls)
        self.assertIn("-f labels[]=afs:capability-gap", calls)

    def test_profile_must_reference_installed_skills(self):
        doc = yaml.safe_load(PROFILE.read_text())
        doc["skills"]["target"]["patterns"].append("no-such-skill")
        p = self.target.parent / f"{self.target.name}-profile.yaml"
        p.write_text(yaml.safe_dump(doc, sort_keys=False))
        self.addCleanup(p.unlink)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "no-such-skill"):
            bootstrap.bootstrap(self.target, p, CAPS, [PACK])

    def test_stack_pack_cannot_shadow_menu_skill(self):
        lock = json.loads((ROOT / "skills.lock.json").read_text())
        pack = json.loads(PACK.read_text())
        pack["skills"].append(dict(pack["skills"][0], name="tdd"))
        with self.assertRaisesRegex(bootstrap.BootstrapError, "tdd"):
            bootstrap.plan_skills(lock, [pack], offline=False)


if __name__ == "__main__":
    unittest.main()
