#!/usr/bin/env python3
"""Role agents and harness skills stay consistent with skills.lock.json.

* one agents/afs-<role>.agent.md per role, frontmatter name == file name, description present;
* required sections; the return contract is parseable YAML;
* the skills an agent lists == the lock entries assigned to its role (both directions);
* agent files stay small (they are loaded into every session; ADR-0015);
* harness skills: frontmatter name == folder, description present, relative links resolve.
"""
import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / "skills.lock.json").read_text(encoding="utf-8"))
ROLES = ["program-orchestrator", "bootstrapper", "analyst", "characterizer", "planner", "slice-coordinator",
         "migrator", "specialist-migrator", "verifier", "auditor"]
MAX_AGENT_CHARS = 9000
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def frontmatter(text):
    m = FRONTMATTER.match(text)
    return (yaml.safe_load(m.group(1)), text[m.end():]) if m else (None, text)


def section(body, title):
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    return m.group(1) if m else None


def listed_skills(skills_section):
    names, bullets = set(), []
    for line in skills_section.splitlines():          # join wrapped continuation lines to their bullet
        if line.startswith("- "):
            bullets.append(line)
        elif line.startswith("  ") and bullets:
            bullets[-1] += " " + line.strip()
    for line in bullets:
        head = line.split(" — ", 1)[0]
        names |= {t for t in re.findall(r"`([^`]+)`", head) if re.fullmatch(r"[a-z0-9-]+", t)}
    return names


def lock_skills_for(role):
    return {e["name"] for e in LOCK["skills"] + LOCK["plugins"] if role in e["roles"]}


class AgentsTest(unittest.TestCase):
    def test_every_role_has_a_consistent_agent(self):
        files = {p.name for p in (ROOT / "agents").glob("*.agent.md")}
        self.assertEqual(files, {f"afs-{r}.agent.md" for r in ROLES})
        for role in ROLES:
            with self.subTest(role=role):
                path = ROOT / "agents" / f"afs-{role}.agent.md"
                text = path.read_text(encoding="utf-8")
                fm, body = frontmatter(text)
                self.assertIsNotNone(fm, "missing frontmatter")
                self.assertEqual(fm.get("name"), f"afs-{role}")
                self.assertGreater(len(fm.get("description", "")), 40)
                self.assertLessEqual(len(text), MAX_AGENT_CHARS, "agent file too large for the context budget")
                self.assertIn("afs-migration-contract", body.split("##", 1)[0], "must load the contract first")
                for title in ("Inputs", "Procedure", "Return contract"):
                    self.assertIsNotNone(section(body, title), f"missing section: {title}")
                skills = section(body, "Skills (load only when the step needs it)")
                self.assertIsNotNone(skills, "missing Skills section")
                listed, expected = listed_skills(skills), lock_skills_for(role)
                self.assertEqual(sorted(listed - expected), [], "listed but not assigned to this role in skills.lock.json")
                self.assertEqual(sorted(expected - listed), [], "assigned in skills.lock.json but not listed")
                contract = re.search(r"```yaml\n(.*?)```", section(body, "Return contract"), re.S)
                self.assertIsNotNone(contract, "return contract needs a yaml block")
                self.assertIsInstance(yaml.safe_load(contract.group(1)), dict)

    def test_harness_skills_are_well_formed(self):
        harness = [e for e in LOCK["skills"] if e.get("install") == "harness"]
        self.assertTrue(harness)
        for e in harness:
            with self.subTest(skill=e["name"]):
                folder = ROOT / e["path"]
                fm, body = frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
                self.assertEqual(fm.get("name"), e["name"])
                self.assertGreater(len(fm.get("description", "")), 40)
                for md in folder.rglob("*.md"):
                    for link in re.findall(r"\]\(([^)#:]+)\)", md.read_text(encoding="utf-8")):
                        self.assertTrue((md.parent / link).exists(), f"{md.relative_to(ROOT)}: broken link {link}")


if __name__ == "__main__":
    unittest.main()
