"""tools/afs-services: compose lint, health parsing, env export, and the no-services notice."""
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools/afs-services"
loader = importlib.machinery.SourceFileLoader("afs_services", str(TOOL))
spec = importlib.util.spec_from_loader("afs_services", loader)
svc = importlib.util.module_from_spec(spec)
loader.exec_module(svc)

COMPOSE = """services:
  db:
    image: postgres:17
    healthcheck: {test: ["CMD", "pg_isready"], interval: 5s}
  mq:
    image: rabbitmq:4
"""


class LintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "compose.yaml").write_text(COMPOSE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_healthy_definition_passes(self):
        self.assertEqual(svc.lint({"compose": "compose.yaml", "test": ["db"]}, self.root), [])

    def test_missing_file(self):
        errors = svc.lint({"compose": "nope.yaml", "test": ["db"]}, self.root)
        self.assertIn("does not exist", errors[0])

    def test_undefined_service(self):
        errors = svc.lint({"compose": "compose.yaml", "test": ["cache"]}, self.root)
        self.assertIn("does not define", errors[0])

    def test_service_without_healthcheck(self):
        errors = svc.lint({"compose": "compose.yaml", "test": ["db", "mq"]}, self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn("'mq' needs a healthcheck", errors[0])


class CheckTest(unittest.TestCase):
    services = {"compose": "compose.yaml", "test": ["db", "mq"]}

    def ps(self, out, rc=0):
        return mock.patch.object(svc.subprocess, "run",
                                 return_value=subprocess.CompletedProcess([], rc, stdout=out, stderr="boom"))

    def test_all_healthy_ndjson(self):
        out = "\n".join(json.dumps(r) for r in [{"Service": "db", "State": "running", "Health": "healthy"},
                                                 {"Service": "mq", "State": "running", "Health": "healthy"}])
        with self.ps(out):
            self.assertEqual(svc.check(self.services, pathlib.Path(".")), 0)

    def test_array_format_and_unhealthy(self):
        out = json.dumps([{"Service": "db", "State": "running", "Health": "starting"}])
        with self.ps(out), mock.patch("sys.stderr") as err:
            self.assertEqual(svc.check(self.services, pathlib.Path(".")), 1)
        written = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertIn("db: running starting", written)
        self.assertIn("mq: not started", written)

    def test_compose_failure_is_down(self):
        with self.ps("", rc=1):
            self.assertEqual(svc.check(self.services, pathlib.Path(".")), 1)


class EnvAndCliTest(unittest.TestCase):
    def test_env_goes_to_github_env(self):
        with tempfile.NamedTemporaryFile("r+", delete=False) as f:
            path = f.name
        try:
            with mock.patch.dict(os.environ, {"GITHUB_ENV": path}):
                svc.export_env({"env": {"POSTGRES_HOST": "localhost"}})
            self.assertEqual(pathlib.Path(path).read_text(), "POSTGRES_HOST=localhost\n")
        finally:
            os.unlink(path)

    def test_no_services_is_a_notice(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "profile.yaml"
            p.write_text("harness_version: 0.2.0\n")
            r = subprocess.run([sys.executable, str(TOOL), "check", "--profile", str(p)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("No `services`", r.stdout)

    def test_lint_cli_fails_on_missing_compose(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "profile.yaml"
            p.write_text("services: {compose: compose.yaml, test: [db]}\n")
            r = subprocess.run([sys.executable, str(TOOL), "lint", "--profile", str(p), "--root", d],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not exist", r.stderr)


if __name__ == "__main__":
    unittest.main()
