"""tools/check_graph_fresh.py (ADR-0019): graphs describe the code they claim to, checked with git."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools/check_graph_fresh.py"
PIN = "f3beacf78de4f6d34edc4971ac87e38a5c6fe59d"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class FreshnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.repo = pathlib.Path(self.tmp.name)
        git(r, "init", "-q", "-b", "main")
        (r / ".migration").mkdir()
        (r / ".migration/source.lock").write_text(f"repo: o/src\nsha: {PIN}\n")
        (r / "src").mkdir()
        (r / "src/app.py").write_text("x = 1\n")
        (r / "tests").mkdir()
        (r / "tests/test_app.py").write_text("def test_x():\n    pass\n")
        self.commit("base")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)

    def graph(self, side, snapshot, commit_hash):
        d = self.repo / ".migration/graphs" / side / "full"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SNAPSHOT.txt").write_text("".join(f"{k}: {v}\n" for k, v in snapshot.items()))
        (d / "knowledge-graph.json").write_text(json.dumps({"project": {"gitCommitHash": commit_hash}}))

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], cwd=self.repo, capture_output=True, text=True)

    def target_graph(self):
        head = git(self.repo, "rev-parse", "HEAD")
        self.graph("target", {"side": "target", "target_commit": head,
                              "tree.src": git(self.repo, "rev-parse", "HEAD:src")}, head)

    def test_stamped_source_graph_is_fresh(self):
        self.graph("source", {"side": "source", "source_sha": PIN}, PIN)
        r = self.run_tool("--require", "source")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_throwaway_commit_or_unstamped_or_repinned_source_is_stale(self):
        self.graph("source", {"side": "source", "source_sha": PIN}, "a8cdf52effc852af7a9218b40bedb98b8451d4ae")
        self.assertIn("gitCommitHash a8cdf52effc8 != source_sha", self.run_tool().stderr)
        self.graph("source", {"source": f"o/src@{PIN}"}, PIN)
        self.assertIn("unstamped", self.run_tool().stderr)
        other = "0" * 40
        self.graph("source", {"source_sha": other}, other)
        r = self.run_tool()
        self.assertEqual(r.returncode, 1)
        self.assertIn("source.lock pins f3beacf78de4", r.stderr)

    def test_target_graph_goes_stale_on_code_changes_only(self):
        self.target_graph()
        self.commit("graph")
        self.assertEqual(self.run_tool("--require", "target").returncode, 0)
        (self.repo / "tests/test_app.py").write_text("def test_x():\n    assert True\n")
        self.commit("test only")
        self.assertEqual(self.run_tool("--require", "target").returncode, 0, "test-only change keeps it fresh")
        (self.repo / "src/app.py").write_text("x = 2\n")
        self.commit("code")
        r = self.run_tool()
        self.assertEqual(r.returncode, 0, "stale target is only a warning unless required")
        self.assertIn("warning", r.stderr)
        self.assertIn("src/ changed since the graph was built", r.stderr)
        r = self.run_tool("--require", "target")
        self.assertEqual(r.returncode, 1)
        self.assertIn("src/ changed since the graph was built", r.stderr)

    def test_missing_graph_fails_only_when_required(self):
        self.assertEqual(self.run_tool().returncode, 0)
        r = self.run_tool("--require", "source,target")
        self.assertEqual(r.returncode, 1)
        self.assertIn("graphs/target: no graph", r.stderr)

    def test_acceptance_requires_both_graphs(self):
        self.graph("source", {"source_sha": PIN}, PIN)
        self.commit("source graph")
        git(self.repo, "branch", "base")
        (self.repo / ".migration/returns").mkdir()
        ret = self.repo / ".migration/returns/TC-15.afs-auditor.yaml"
        ret.write_text("verdict: gaps-remain\n")
        self.commit("audit")
        self.assertEqual(self.run_tool("--acceptance-since", "base").returncode, 0)
        ret.write_text("verdict: complete\n")
        self.commit("accept")
        r = self.run_tool("--acceptance-since", "base")
        self.assertEqual(r.returncode, 1)
        self.assertIn("acceptance", r.stdout)
        self.assertIn("graphs/target: no graph", r.stderr)
        self.target_graph()
        self.commit("target graph")
        self.assertEqual(self.run_tool("--acceptance-since", "base").returncode, 0)


if __name__ == "__main__":
    unittest.main()
