"""tools/fog_rewalk.py (ADR-0022): slice acceptance opens a wayfinder task to re-walk the map's fog."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import fog_rewalk  # noqa: E402

MAP = """## Destination
x

## Not yet specified
<!-- in-scope fog -->
- The mobile event logger: flow from the source,
  look from ADR-0002.
- Scheduling of reports.

## Out of scope
- Mobile apps.

---
_footer_
"""


class FogRewalkTest(unittest.TestCase):
    def test_fog_items_fold_continuations_and_stop_at_next_section(self):
        self.assertEqual(fog_rewalk.fog_items(MAP), [
            "The mobile event logger: flow from the source, look from ADR-0002.", "Scheduling of reports."])
        self.assertEqual(fog_rewalk.fog_items("## Destination\nx\n"), [])

    def test_ticket_lists_each_item_as_a_checkbox(self):
        title, body = fog_rewalk.ticket("Slice: Track Cargo", "https://x/9", fog_rewalk.fog_items(MAP))
        self.assertEqual(title, 'Re-walk the fog after accepting "Slice: Track Cargo"')
        self.assertTrue(body.startswith("## Question"))
        self.assertIn("- [ ] Scheduling of reports.", body)
        self.assertNotIn("Mobile apps", body)
        _, empty = fog_rewalk.ticket("S", "#", [])
        self.assertIn("is empty: confirm nothing new surfaced", empty)

    def test_slice_epic_by_label_or_by_slice_spec(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "track-cargo.yaml").write_text("epic: 9\ndata_paths: {}\n")
            self.assertTrue(fog_rewalk.is_slice_epic(9, [], d))
            self.assertTrue(fog_rewalk.is_slice_epic(40, ["afs:slice"], d))
            self.assertFalse(fog_rewalk.is_slice_epic(41, ["bug"], d))

    def run_main(self, epic_state, existing_titles):
        calls = []

        def gh(path, *args, data=None):
            calls.append((path, args, data))
            if path.endswith("/issues/9"):
                return {"title": "Slice: X", "html_url": "u", "state": epic_state, "labels": [{"name": "afs:slice"}]}
            if "labels=wayfinder:map" in path:
                return [{"number": 3, "body": MAP}]
            if path.startswith("repos/o/r/issues/3/sub_issues?"):
                return [{"title": t, "html_url": "old"} for t in existing_titles]
            if path == "repos/o/r/issues":
                return {"id": 1, "html_url": "new"}
            return {}
        orig, fog_rewalk.gh = fog_rewalk.gh, gh
        try:
            self.assertEqual(fog_rewalk.main(["--repo", "o/r", "--epic", "9", "--closed-by", "al"]), 0)
        finally:
            fog_rewalk.gh = orig
        return [c for c in calls if c[0] == "repos/o/r/issues"]

    def test_opens_once_only_for_a_closed_epic(self):
        self.assertEqual(len(self.run_main("closed", [])), 1)
        self.assertEqual(self.run_main("open", []), [], "an open epic isn't accepted")
        self.assertEqual(self.run_main("closed", ['Re-walk the fog after accepting "Slice: X"']), [],
                         "a re-run doesn't duplicate the ticket")


if __name__ == "__main__":
    unittest.main()
