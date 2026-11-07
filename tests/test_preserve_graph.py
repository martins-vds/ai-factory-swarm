"""tools/preserve_graph.py (ADR-0033): a source-graph regeneration keeps what earlier runs found."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import preserve_graph as pg  # noqa: E402


def domain(*flows):
    nodes, edges = [{"id": "domain:d", "type": "domain", "name": "D"}], []
    for f in flows:
        fid = "flow:" + f.lower().replace(" ", "-")
        nodes += [{"id": fid, "type": "flow", "name": f}, {"id": fid + ":s1", "type": "step", "name": "s1"}]
        edges += [{"source": "domain:d", "target": fid, "type": "contains_flow"},
                  {"source": fid, "target": fid + ":s1", "type": "flow_step"}]
    return {"nodes": nodes, "edges": edges}


def knowledge(*named):
    return {"nodes": [{"id": f"{t}:{n}", "type": t, "name": n} for t, n in named], "edges": []}


class MergeTest(unittest.TestCase):
    def test_a_narrowed_run_keeps_the_earlier_flows(self):
        prev, new = domain("Register Cargo", "Track Cargo"), domain("Admin Map")
        self.assertEqual(sorted(pg.merge_domain(prev, new)), ["Register Cargo", "Track Cargo"])
        self.assertEqual(sorted(f["name"] for f in pg.flows(new).values()), ["Admin Map", "Register Cargo", "Track Cargo"])
        steps = [e for e in new["edges"] if e["type"] == "flow_step"]
        self.assertEqual(len(steps), 3, "each kept flow keeps its steps")
        ids = {n["id"] for n in new["nodes"]}
        self.assertTrue(all(e["source"] in ids and e["target"] in ids for e in new["edges"]), "no dangling edge")

    def test_the_new_version_wins_when_both_have_a_flow(self):
        prev = domain("Track Cargo")
        new = domain("track  cargo")
        self.assertEqual(pg.merge_domain(prev, new), [])
        self.assertEqual(len(pg.flows(new)), 1)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.put(domain("Register Cargo", "Track Cargo"), knowledge(("table", "cargo"), ("endpoint", "GET /cargo")))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def git(self, *a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)

    def put(self, dom, kg):
        d = pathlib.Path(".migration/graphs/source/full")
        d.mkdir(parents=True, exist_ok=True)
        (d / "domain-graph.json").write_text(json.dumps(dom))
        (d / "knowledge-graph.json").write_text(json.dumps(kg))

    def change(self, dom, kg):
        self.put(dom, kg)
        self.git("commit", "-qam", "regenerate")

    def test_losing_a_flow_fails(self):
        self.change(domain("Admin Map"), knowledge(("table", "cargo"), ("endpoint", "GET /cargo")))
        _, problems = pg.check("HEAD~1", "source")
        self.assertEqual(len(problems), 2)
        self.assertEqual(pg.main(["check", "--base", "HEAD~1"]), 1)

    def test_losing_a_table_or_endpoint_fails(self):
        self.change(domain("Register Cargo", "Track Cargo"), knowledge(("table", "cargo")))
        _, problems = pg.check("HEAD~1", "source")
        self.assertEqual(problems, [".migration/graphs/source/full: lost endpoint 'get /cargo'"])

    def test_growing_passes(self):
        self.change(domain("Register Cargo", "Track Cargo", "Admin Map"),
                    knowledge(("table", "cargo"), ("endpoint", "GET /cargo"), ("page", "map.xhtml")))
        self.assertEqual(pg.check("HEAD~1", "source")[1], [])

    def test_functions_may_change(self):
        """Function nodes come from the LLM layer and move between runs; they aren't checked."""
        kg = knowledge(("table", "cargo"), ("endpoint", "GET /cargo"), ("function", "getAllCargo"))
        self.change(domain("Register Cargo", "Track Cargo"), kg)
        self.change(domain("Register Cargo", "Track Cargo"), knowledge(("table", "cargo"), ("endpoint", "GET /cargo")))
        self.assertEqual(pg.check("HEAD~1", "source")[1], [])


if __name__ == "__main__":
    unittest.main()
