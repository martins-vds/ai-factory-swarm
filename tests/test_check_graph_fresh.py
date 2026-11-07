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

    def test_templates_outside_the_analysed_paths_make_the_target_graph_incomplete(self):
        self.target_graph()
        (self.repo / "templates/tracking").mkdir(parents=True)
        (self.repo / "templates/tracking/track.html").write_text("<form hx-post=\"{% url 'track' %}\"></form>\n")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/page.html").write_text("{% not analysed: docs are excluded %}\n")
        (self.repo / "static").mkdir()
        (self.repo / "static/plain.html").write_text("<p>no template tags</p>\n")
        self.commit("graph, templates outside src")
        r = self.run_tool("--require", "target")
        self.assertEqual(r.returncode, 1)
        self.assertIn("templates/tracking/track.html: a Django template outside the analysed paths (src)", r.stderr)
        self.assertIn("graph.target_paths", r.stderr)
        self.assertNotIn("docs/page.html", r.stderr)
        self.assertNotIn("static/plain.html", r.stderr)
        (self.repo / ".migration/profile.yaml").write_text("graph:\n  target_exclude: [templates/]\n")
        self.assertNotIn("track.html", self.run_tool("--require", "target").stderr, "excluded by the profile")

    def test_missing_graph_fails_only_when_required(self):
        self.assertEqual(self.run_tool().returncode, 0)
        r = self.run_tool("--require", "source,target")
        self.assertEqual(r.returncode, 1)
        self.assertIn("graphs/target: no graph", r.stderr)

    def run_record(self, commit, trees, status="passed"):
        d = self.repo / ".migration/evidence/acceptance-runs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "42-1.json").write_text(json.dumps({"status": status, "exit": 0 if status == "passed" else 1,
                                                 "commit": commit, "target_graph": {"trees": trees}}))

    def test_acceptance_needs_the_source_graph_and_a_bound_acceptance_run(self):
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
        self.assertIn("cites no acceptance run", r.stderr)
        # The run checked commit C and built its graph there; main then moved on (src changed). Still valid.
        accepted = git(self.repo, "rev-parse", "HEAD")
        trees = {"src": git(self.repo, "rev-parse", "HEAD:src")}
        (self.repo / "src/app.py").write_text("x = 2\n")
        self.commit("another slice merged during the audit")
        self.run_record(accepted, trees)
        self.commit("audit evidence")
        r = self.run_tool("--acceptance-since", "base")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # a graph that doesn't describe the cited commit, or a failed run, doesn't bind
        self.run_record(accepted, {"src": "0" * 40})
        self.commit("wrong graph")
        self.assertIn("doesn't describe commit", self.run_tool("--acceptance-since", "base").stderr)
        self.run_record(accepted, trees, status="failed")
        self.commit("failed run")
        self.assertIn("did not pass", self.run_tool("--acceptance-since", "base").stderr)

    def test_env_points_the_target_side_at_the_acceptance_build(self):
        self.graph("source", {"source_sha": PIN}, PIN)
        built = self.repo / "built"
        built.mkdir()
        head = git(self.repo, "rev-parse", "HEAD")
        (built / "SNAPSHOT.txt").write_text(f"target_commit: {head}\ntree.src: {git(self.repo, 'rev-parse', 'HEAD:src')}\n")
        env = {**__import__("os").environ, "AFS_GRAPH_TARGET_DIR": str(built)}
        r = subprocess.run([sys.executable, str(TOOL), "--require", "source,target"], cwd=self.repo,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(str(built), r.stdout)

    def test_only_checks_the_named_graph(self):
        self.graph("source", {"source": f"o/src@{PIN}"}, PIN)        # unstamped, but not ours
        self.target_graph()
        self.commit("graphs")
        r = self.run_tool("--only", ".migration/graphs/target/full")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.run_tool("--only", ".migration/graphs/source/full").returncode, 1)
        self.assertEqual(self.run_tool("--only", ".migration/graphs/nope").returncode, 2)

if __name__ == "__main__":
    unittest.main()
