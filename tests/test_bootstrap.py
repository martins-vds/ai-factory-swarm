"""Tests for tools/bootstrap.py and tools/check_installed.py. Offline: upstream fetches and `gh` are faked."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import bootstrap  # noqa: E402

PROFILE = ROOT / "templates/migration/profile.yaml"
CAPS = ROOT / "templates/migration/capabilities.yaml"
PACK = ROOT / "stacks/java-to-django.json"


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
                  ".migration/harness/tools/afs-run", ".migration/harness/installed.json",
                  ".github/hooks/rtk-rewrite.json", ".github/workflows/copilot-setup-steps.yml",
                  ".github/workflows/afs-harness-check.yml", ".github/skills/django-patterns/PROVENANCE.md",
                  ".github/skills/django-patterns/LICENSE", ".github/skills/afs-wayfinder/PROVENANCE.md"]:
            self.assertTrue((self.target / f).exists(), f)
        self.assertTrue(os.access(self.target / ".migration/harness/tools/afs-run", os.X_OK))
        for wf in ("copilot-setup-steps.yml", "afs-harness-check.yml", "afs-understand.yml"):
            doc = yaml.safe_load((self.target / ".github/workflows" / wf).read_text())
            self.assertIn("jobs", doc)
        self.assertIn("copilot-setup-steps", yaml.safe_load(
            (self.target / ".github/workflows/copilot-setup-steps.yml").read_text())["jobs"])
        for cmd in (["python3", ".migration/harness/tools/check_installed.py"],
                    ["python3", ".migration/harness/tools/validate.py", ".migration"]):
            out = subprocess.run(cmd, cwd=self.target, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        lock_text = (self.target / ".migration/source.lock").read_text()
        self.assertIn("sha: c2df7607e3b6a997dd27eb2917bc33e4ec0f6692", lock_text)
        self.assertEqual((self.target / ".gitignore").read_text(), ".source/\n.migration/runs/\n")

    def test_instruction_blocks_preserve_team_content_and_are_idempotent(self):
        ci = self.target / ".github/copilot-instructions.md"
        ci.parent.mkdir(parents=True)
        ci.write_text("# Team notes\nKeep this.\n")
        self.run_bootstrap()
        first = ci.read_text()
        self.assertTrue(first.startswith("<!-- afs-instructions v1 -->"))
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
