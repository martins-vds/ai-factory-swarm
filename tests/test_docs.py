"""The docs describe the harness that ships: checked, so they can't drift from the code."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
ARCH = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
ROADMAP = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
ADRS = sorted((ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))


def tools():
    return sorted(p.name for p in (ROOT / "tools").iterdir() if p.is_file() and not p.name.startswith("."))


def decisions_table():
    start = ARCH.index("## 2. Decisions at a glance")
    return ARCH[start:ARCH.index("\n## ", start + 1)]


class DocsTest(unittest.TestCase):
    def test_every_tool_is_listed_in_the_readme(self):
        missing = [t for t in tools() if f"`{t}`" not in README]
        self.assertEqual(missing, [], "add each tool to the README's Tools section")

    def test_the_readme_lists_no_tool_that_is_gone(self):
        section = README[README.index("## Tools"):README.index("## Status")]
        listed = re.findall(r"^- `([^`]+)`", section, re.M)
        self.assertEqual(sorted(set(listed) - set(tools())), [])

    def test_every_adr_is_in_the_decisions_table(self):
        table = decisions_table()
        missing = [a.name for a in ADRS if f"(adr/{a.name})" not in table]
        self.assertEqual(missing, [], "add a row to architecture.md §2 for each ADR")

    def test_an_amended_or_superseded_adr_says_so(self):
        """`- Amends: ADR-N` / `- Supersedes: ADR-N` in one ADR → ADR-N's status names it."""
        by_number = {a.name[:4]: a for a in ADRS}
        for adr in ADRS:
            head = adr.read_text(encoding="utf-8").split("\n## ", 1)[0]
            for n in re.findall(r"^- (?:Amends|Supersedes):.*?ADR-(\d{4})", head, re.M):
                status = re.search(r"^- Status:(.*)$", by_number[n].read_text(encoding="utf-8"), re.M).group(1)
                self.assertIn(f"ADR-{adr.name[:4]}", status, f"{by_number[n].name}: status must name {adr.name}")

    def test_readme_status_matches_the_roadmap(self):
        done = re.findall(r"^\| \*\*(M\d) ·[^\n]*✅ \|$", ROADMAP, re.M)
        last = max(done, key=lambda m: int(m[1:]))
        self.assertRegex(README[README.index("## Status"):], rf"M0–{last} are done",
                         "README status must name the last milestone the roadmap marks done")


if __name__ == "__main__":
    unittest.main()
