"""Generated workflows use the PR's own base, never github.base_ref.

On a GitHub stacked PR, `github.base_ref` is the bottom of the stack (the default branch), while
`github.event.pull_request.base.ref` is the branch the PR targets. Pilot #229: the return-file check
compared against main and failed; diffs against main also over-count a stacked PR's changes.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class BaseRefTest(unittest.TestCase):
    def test_no_template_uses_github_base_ref(self):
        for wf in sorted((ROOT / "templates" / "target").glob("*.yml")):
            body = "\n".join(l for l in wf.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
            with self.subTest(workflow=wf.name):
                self.assertNotIn("github.base_ref", body)


if __name__ == "__main__":
    unittest.main()
