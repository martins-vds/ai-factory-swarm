import asyncio
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from check_domain_coverage import coverage_failures, validate_entry_points  # noqa: E402
from understand import STEPS, prompts_for, run  # noqa: E402


ENTRY = "src/admin/map.xhtml"
SERVICE = "src/admin/CargoMonitoringService.java"
PUBLIC = "src/public/TrackingService.java"


def knowledge_graph():
    return {
        "nodes": [
            {"id": "page:admin-map", "type": "page", "name": "Admin map", "filePath": ENTRY},
            {"id": "service:cargo-monitoring", "type": "service", "name": "CargoMonitoringService",
             "filePath": SERVICE},
            {"id": "page:public-tracking", "type": "page", "name": "Public tracking",
             "filePath": "src/public/track.xhtml"},
            {"id": "service:tracking", "type": "service", "name": "TrackingService", "filePath": PUBLIC},
        ],
        "edges": [
            {"source": "page:admin-map", "target": "service:cargo-monitoring", "type": "calls"},
            {"source": "page:public-tracking", "target": "service:tracking", "type": "calls"},
        ],
    }


def domain_graph(step_path=SERVICE, entry_point=ENTRY):
    return {
        "nodes": [
            {"id": "domain:monitoring", "type": "domain", "name": "Monitoring"},
            {"id": "flow:all-cargo-map", "type": "flow", "name": "Display all cargo",
             "domainMeta": {"entryPoint": entry_point}},
            {"id": "step:all-cargo-map:load-cargo", "type": "step", "name": "Load cargo",
             "filePath": step_path},
        ],
        "edges": [
            {"source": "domain:monitoring", "target": "flow:all-cargo-map", "type": "contains_flow"},
            {"source": "flow:all-cargo-map", "target": "step:all-cargo-map:load-cargo", "type": "flow_step"},
        ],
    }


class DomainCoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        for path in (ENTRY, SERVICE, PUBLIC, "src/public/track.xhtml"):
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("source\n", encoding="utf-8")
        self.knowledge = knowledge_graph()

    def tearDown(self):
        self.tmp.cleanup()

    def test_connected_source_backed_flow_covers_requested_entry_point(self):
        self.assertEqual(
            coverage_failures(self.root, self.knowledge, domain_graph(), [ENTRY]),
            [],
        )

    def test_missing_domain_graph_or_flow_is_a_failure(self):
        self.assertTrue(coverage_failures(self.root, self.knowledge, None, [ENTRY]))
        for graph in (
            {"nodes": [], "edges": []},
            {
                "nodes": [
                    {"id": "domain:monitoring", "type": "domain"},
                    {"id": "flow:all-cargo-map", "type": "flow",
                     "domainMeta": {"entryPoint": ENTRY}},
                    {"id": "step:load", "type": "step", "filePath": SERVICE},
                ],
                "edges": [{"source": "flow:all-cargo-map", "target": "step:load", "type": "flow_step"}],
            },
        ):
            self.assertTrue(coverage_failures(self.root, self.knowledge, graph, [ENTRY]))

    def test_missing_domain_artifact_fails_in_the_cli(self):
        knowledge_path = self.root / "knowledge-graph.json"
        knowledge_path.write_text(json.dumps(self.knowledge), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "tools/check_domain_coverage.py"),
                "--root", str(self.root), "--knowledge", str(knowledge_path),
                "--domain", str(self.root / "missing-domain-graph.json"),
                "--domain-entry-point", ENTRY,
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot read domain graph", result.stderr)

    def test_unrelated_public_flow_does_not_cover_admin_entry_point(self):
        graph = domain_graph(step_path=PUBLIC, entry_point="GET /track")
        self.assertTrue(coverage_failures(self.root, self.knowledge, graph, [ENTRY]))

    def test_disconnected_step_and_unbacked_file_reference_do_not_cover(self):
        disconnected = domain_graph()
        disconnected["edges"] = disconnected["edges"][:1]
        self.assertTrue(coverage_failures(self.root, self.knowledge, disconnected, [ENTRY]))

        unbacked = domain_graph(step_path="src/admin/Unrelated.java")
        (self.root / "src/admin/Unrelated.java").write_text("source\n", encoding="utf-8")
        self.assertTrue(coverage_failures(self.root, self.knowledge, unbacked, [ENTRY]))

    def test_existing_but_structurally_unreachable_step_does_not_cover(self):
        graph = domain_graph(step_path=PUBLIC)
        self.assertTrue(coverage_failures(self.root, self.knowledge, graph, [ENTRY]))

    def test_exact_entry_point_marker_is_required(self):
        graph = domain_graph(entry_point="src/admin")
        self.assertTrue(coverage_failures(self.root, self.knowledge, graph, [ENTRY]))

    def test_entry_points_must_be_existing_files_inside_source_root(self):
        self.assertEqual(validate_entry_points(self.root, [ENTRY]), [ENTRY])
        for invalid in ("../outside.java", "/absolute.java", "src/missing.java", "src/../outside.java"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_entry_points(self.root, [invalid])

    def test_runner_rejects_invalid_request_before_loading_the_sdk(self):
        args = Namespace(dir=self.root, domain_entry_points=["../outside.java"])
        with self.assertRaises(ValueError):
            asyncio.run(run(args))

    def test_symlink_to_outside_source_is_rejected(self):
        outside = self.root.parent / "outside.java"
        outside.write_text("outside\n", encoding="utf-8")
        link = self.root / "src/admin/outside.java"
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            validate_entry_points(self.root, ["src/admin/outside.java"])

    def test_no_request_preserves_default_prompts(self):
        self.assertEqual(prompts_for([]), STEPS)

    def test_request_uses_full_scan_and_names_the_exact_paths(self):
        steps = prompts_for([ENTRY])
        self.assertEqual(steps[0], STEPS[0])
        self.assertEqual(steps[1][0], STEPS[1][0])
        self.assertIn("`--full`", steps[1][1])
        self.assertIn(ENTRY, steps[1][1])


if __name__ == "__main__":
    unittest.main()
