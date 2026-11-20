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
ROLES = ["program-orchestrator", "analyst", "characterizer", "planner",
         "migrator", "verifier", "auditor"]
MAX_AGENT_CHARS = 6000   # phase 5 (ADR-0053): was 9,000; the largest file was 8,838
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

    def test_coordinator_return_examples_parse_as_string_lists(self):
        examples = [
            ("afs-program-orchestrator", "", "decisions", "<ticket link: one-line answer>"),
            ("afs-program-orchestrator", "", "awaiting_human", "<ticket link: what is needed>"),
        ]
        for role, parent, key, expected in examples:
            with self.subTest(role=role, key=key):
                text = (ROOT / "agents" / f"{role}.agent.md").read_text(encoding="utf-8")
                contract = re.search(r"## Return contract.*?```yaml\n(.*?)```", text, re.S)
                self.assertIsNotNone(contract)
                parsed = yaml.safe_load(contract.group(1))
                items = parsed[parent][key] if parent else parsed[key]
                self.assertEqual(items, [expected])
                self.assertTrue(all(isinstance(item, str) for item in items))

    # Phase 5 (ADR-0053): at most 12 listed skills per role. A role above it needs a recorded reason here.
    SKILL_BUDGET = 12
    SKILL_BUDGET_EXCEPTIONS = {
        "program-orchestrator": "absorbed the Bootstrapper and the Slice Coordinator (ADR-0046, ADR-0050); 16 of its "
                                "skills are loaded only by `afs-bootstrap` or the ticket loop. No session data yet: "
                                "revisit after its next 20 sessions",
        "characterizer": "no eval sessions yet to show which of its 13 are unused; revisit with phase 4b's follow-up",
        "verifier": "audit-only since ADR-0045; its four gate-3 rule sets are each loaded in 16-33% of 180 sessions",
    }

    def test_each_role_stays_within_its_skill_budget(self):
        lock = json.loads((ROOT / "skills.lock.json").read_text(encoding="utf-8"))
        counts = {}
        for e in lock["skills"] + lock["plugins"]:
            for r in e["roles"]:
                counts[r] = counts.get(r, 0) + 1
        for role, n in counts.items():
            with self.subTest(role=role):
                if n > self.SKILL_BUDGET:
                    self.assertIn(role, self.SKILL_BUDGET_EXCEPTIONS,
                                  f"{role} lists {n} skills (budget {self.SKILL_BUDGET}): trim, or record why")
        for role in self.SKILL_BUDGET_EXCEPTIONS:
            self.assertGreater(counts.get(role, 0), self.SKILL_BUDGET, f"{role}'s exception is stale: remove it")

    def test_the_acceptance_return_example_parses(self):
        # ADR-0050: the Slice Coordinator's return became the orchestrator's `acceptance` block.
        text = (ROOT / "skills" / "afs-slice-acceptance" / "SKILL.md").read_text(encoding="utf-8")
        block = yaml.safe_load(re.search(r"```yaml\n(.*?)```", text, re.S).group(1))["acceptance"]
        self.assertEqual(block["tickets"]["blocked"], ["<link: blocker>"])
        self.assertIn("human_check", block)

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
