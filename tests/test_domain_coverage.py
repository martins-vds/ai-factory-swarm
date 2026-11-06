import contextlib
import asyncio
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from check_domain_coverage import coverage_failures, validate_entry_points  # noqa: E402
from understand import STEPS, prompts_for, run  # noqa: E402


ENTRY = "src/admin/map.xhtml"
SERVICE = "src/admin/MapDataService.java"
PUBLIC = "src/public/TrackingService.java"


def knowledge_graph():
    return {
        "nodes": [
            {"id": "page:admin-map", "type": "page", "name": "Admin map", "filePath": ENTRY},
            {"id": "service:map-data", "type": "service", "name": "MapDataService",
             "filePath": SERVICE},
            {"id": "page:public-tracking", "type": "page", "name": "Public tracking",
             "filePath": "src/public/track.xhtml"},
            {"id": "service:tracking", "type": "service", "name": "TrackingService", "filePath": PUBLIC},
        ],
        "edges": [
            {"source": "page:admin-map", "target": "service:map-data", "type": "calls"},
            {"source": "page:public-tracking", "target": "service:tracking", "type": "calls"},
        ],
    }


def domain_graph(step_path=SERVICE, entry_point=ENTRY):
    return {
        "nodes": [
            {"id": "domain:monitoring", "type": "domain", "name": "Monitoring"},
            {"id": "flow:admin-map", "type": "flow", "name": "Display all items",
             "domainMeta": {"entryPoint": entry_point}},
            {"id": "step:admin-map:load-items", "type": "step", "name": "Load items",
             "filePath": step_path},
        ],
        "edges": [
            {"source": "domain:monitoring", "target": "flow:admin-map", "type": "contains_flow"},
            {"source": "flow:admin-map", "target": "step:admin-map:load-items", "type": "flow_step"},
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
                    {"id": "flow:admin-map", "type": "flow",
                     "domainMeta": {"entryPoint": ENTRY}},
                    {"id": "step:load", "type": "step", "filePath": SERVICE},
                ],
                "edges": [{"source": "flow:admin-map", "target": "step:load", "type": "flow_step"}],
            },
        ):
            self.assertTrue(coverage_failures(self.root, self.knowledge, graph, [ENTRY]))

    def test_legacy_global_gate_passes_unrelated_flow_but_requested_gate_fails(self):
        knowledge = knowledge_graph()
        knowledge["nodes"].append({"id": "table:items", "type": "table", "name": "Items"})
        knowledge["edges"].append(
            {"source": "service:map-data", "target": "table:items", "type": "reads_from"}
        )
        domain = domain_graph(step_path=PUBLIC, entry_point="GET /track")
        knowledge_path = self.root / "knowledge-graph.json"
        domain_path = self.root / "domain-graph.json"
        knowledge_path.write_text(json.dumps(knowledge), encoding="utf-8")
        domain_path.write_text(json.dumps(domain), encoding="utf-8")
        legacy = subprocess.run(
            [
                sys.executable, str(ROOT / "tools/check_graph.py"), str(knowledge_path),
                "--domain", str(domain_path), "--gate",
                "--require-node", "domain", "--require-node", "flow", "--require-node", "step",
                "--require-edge", "contains_flow", "--require-edge", "flow_step",
                "--data-path", ENTRY,
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(legacy.returncode, 0, legacy.stdout + legacy.stderr)
        self.assertTrue(coverage_failures(self.root, knowledge, domain, [ENTRY]))

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

    def run_mocked(self, entry_points, domain=None, defer=False):
        source_graphs = self.root / ".ua"
        source_graphs.mkdir(exist_ok=True)
        (source_graphs / "knowledge-graph.json").write_text(json.dumps(self.knowledge), encoding="utf-8")
        if domain is not None:
            (source_graphs / "domain-graph.json").write_text(json.dumps(domain), encoding="utf-8")
        else:
            (source_graphs / "domain-graph.json").unlink(missing_ok=True)
        args = Namespace(
            dir=self.root, domain_entry_points=entry_points, defer_domain_coverage=defer,
            out=self.root / "output", plugin=self.root / "plugin", model=None,
            token_env="TEST_TOKEN", timeout=1,
        )

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

        stdout = io.StringIO()
        with (
            mock.patch.dict(sys.modules, {"copilot": SimpleNamespace(CopilotClient=lambda **_: FakeClient())}),
            mock.patch("understand.run_step", new=AsyncMock()),
            mock.patch.dict("os.environ", {"TEST_TOKEN": "test-token"}),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stdout),
        ):
            result = asyncio.run(run(args))
        return result, stdout.getvalue(), args.out / "run.md"

    def test_runner_fails_when_requested_domain_artifact_is_missing(self):
        result, output, _ = self.run_mocked([ENTRY])
        self.assertEqual(result, 1)
        self.assertIn("Domain coverage: FAIL", output)
        self.assertIn("domain graph is missing", output)

    def test_runner_requires_connected_coverage_for_direct_requests(self):
        result, output, _ = self.run_mocked([ENTRY], domain=domain_graph(step_path=PUBLIC))
        self.assertEqual(result, 1)
        self.assertIn("Domain coverage: FAIL", output)

        result, output, _ = self.run_mocked([ENTRY], domain=domain_graph())
        self.assertEqual(result, 0, output)
        self.assertIn("Domain coverage: PASS", output)

    def test_runner_deferral_is_explicit_and_still_requires_domain_artifact(self):
        result, output, summary = self.run_mocked([ENTRY], domain=domain_graph(step_path=PUBLIC), defer=True)
        self.assertEqual(result, 0, output)
        self.assertIn("Domain coverage: DEFERRED", output)
        self.assertIn("must run check_domain_coverage.py after enrichment", summary.read_text())

        result, output, _ = self.run_mocked([ENTRY], defer=True)
        self.assertEqual(result, 1)
        self.assertIn("Domain coverage: FAIL", output)
        self.assertIn("domain graph is missing", output)

    def test_runner_preserves_no_request_success_without_domain_graph(self):
        result, output, _ = self.run_mocked([])
        self.assertEqual(result, 0, output)
        self.assertNotIn("domain coverage:", output)

    def test_symlink_to_outside_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as external_dir:
            outside = pathlib.Path(external_dir) / "outside.java"
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
