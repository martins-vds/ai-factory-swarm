"""tools/check_layers.py: the layering gate (phase 3e)."""
import io
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_layers  # noqa: E402

PILOT = {
    "source_root": "src",
    "contracts": [
        {"name": "use cases don't depend on web adapters", "adr": "ADR-0001",
         "files": ["src/app/*/application/**/*.py"],
         "forbid": ["django.http", "django.shortcuts", "django.utils.timezone", "app.*.infrastructure"]},
        {"name": "web adapters call use cases, not repositories", "adr": "ADR-0001",
         "files": ["src/app/*/interfaces/**/*.py"],
         "forbid": ["app.*.infrastructure", "app.*.domain.repository"]},
    ],
}


class LayersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def run_gate(self, layering):
        (self.root / ".migration").mkdir(exist_ok=True)
        (self.root / ".migration/profile.yaml").write_text(yaml.safe_dump({"layering": layering}))
        out = io.StringIO()
        with redirect_stdout(out):
            code = check_layers.main(["--root", str(self.root)])
        return code, out.getvalue()

    def test_a_use_case_raising_http404_fails(self):
        # eval b3c: BK-05F's use case raised Django's Http404; the Verifier missed it in every run.
        self.write("src/app/booking/application/routing.py", "from django.http import Http404\n")
        code, out = self.run_gate(PILOT)
        self.assertEqual(code, 1, out)
        self.assertIn("src/app/booking/application/routing.py:1", out)
        self.assertIn("`django.http.Http404`", out)
        self.assertIn("ADR-0001", out)
        self.assertIn("violations=1", out)

    def test_from_package_import_module_is_caught(self):
        self.write("src/app/loans/application/lend.py", "from django.utils import timezone\n")
        code, out = self.run_gate(PILOT)
        self.assertEqual(code, 1, out)
        self.assertIn("`django.utils.timezone`", out)

    def test_a_view_importing_the_repository_fails(self):
        # eval b3c: BK-05E's view called CargoRepository directly instead of a use case.
        self.write("src/app/booking/interfaces/dashboard/views.py",
                   "from app.cargo.domain.repository import CargoRepository\n")
        code, out = self.run_gate(PILOT)
        self.assertEqual(code, 1, out)
        self.assertIn("web adapters call use cases", out)

    def test_relative_imports_resolve_against_the_package(self):
        # synthetic LL-02: services.py imported `.repository` (resolved under source_root ".").
        layering = {"contracts": [{"name": "use cases depend only on their ports",
                                   "files": ["src/*/services.py"], "forbid": ["django", "src.*.repository"]}]}
        self.write("src/loans/services.py", "from .repository import LoanRepository\nimport csv\n")
        self.write("src/loans/__init__.py", "")
        code, out = self.run_gate(layering)
        self.assertEqual(code, 1, out)
        self.assertIn("`src.loans.repository", out)

    def test_clean_code_passes(self):
        self.write("src/app/booking/application/routing.py",
                   "from app.cargo.domain.repository import CargoRepository\nfrom datetime import date\n")
        self.write("src/app/booking/interfaces/views.py",
                   "from django.http import Http404\nfrom app.booking.application.routing import x\n")
        code, out = self.run_gate(PILOT)
        self.assertEqual(code, 0, out)
        self.assertIn("violations=0", out)

    def test_type_checking_imports_are_skipped(self):
        self.write("src/app/booking/application/routing.py", """\
            from typing import TYPE_CHECKING
            if TYPE_CHECKING:
                from django.http import HttpRequest
            """)
        code, out = self.run_gate(PILOT)
        self.assertEqual(code, 0, out)

    def test_imports_inside_functions_count(self):
        self.write("src/app/booking/application/routing.py", """\
            def find():
                from django.shortcuts import get_object_or_404
                return get_object_or_404
            """)
        code, _ = self.run_gate(PILOT)
        self.assertEqual(code, 1)

    def test_allow_and_except_files(self):
        layering = {"source_root": "src", "contracts": [dict(PILOT["contracts"][1],
                                                             allow=["app.cargo.domain.repository"],
                                                             except_files=["src/app/*/interfaces/wiring.py"])]}
        self.write("src/app/booking/interfaces/views.py", "from app.cargo.domain.repository import CargoRepository\n")
        self.write("src/app/booking/interfaces/wiring.py", "from app.cargo.infrastructure import DjangoRepo\n")
        code, out = self.run_gate(layering)
        self.assertEqual(code, 0, out)

    def test_a_known_violation_is_reported_but_does_not_fail(self):
        self.write("src/app/booking/application/routing.py", "from django.http import Http404\n")
        layering = dict(PILOT, known=[{"file": "src/app/booking/application/routing.py", "module": "django.http",
                                       "reason": "pilot ticket BK-05H"}])
        code, out = self.run_gate(layering)
        self.assertEqual(code, 0, out)
        self.assertIn("known, not failing", out)
        self.assertIn("pilot ticket BK-05H", out)
        self.assertIn("violations=0 known=1", out)

    def test_a_known_entry_does_not_cover_a_new_violation_in_another_file(self):
        self.write("src/app/booking/application/routing.py", "from django.http import Http404\n")
        self.write("src/app/booking/application/select.py", "from django.http import Http404\n")
        layering = dict(PILOT, known=[{"file": "src/app/booking/application/routing.py", "module": "django.http",
                                       "reason": "pilot ticket BK-05H"}])
        code, out = self.run_gate(layering)
        self.assertEqual(code, 1, out)
        self.assertIn("src/app/booking/application/select.py:1", out)

    def test_a_stale_known_entry_is_reported(self):
        self.write("src/app/booking/application/routing.py", "import datetime\n")
        layering = dict(PILOT, known=[{"file": "src/app/booking/application/routing.py", "module": "django.http",
                                       "reason": "fixed"}])
        code, out = self.run_gate(layering)
        self.assertEqual(code, 0, out)
        self.assertIn("no longer occurs", out)

    def test_bad_contract_exits_2(self):
        code, out = self.run_gate({"contracts": [{"name": "x", "files": ["src/**"]}]})
        self.assertEqual(code, 2, out)
        self.assertIn("needs `name`, `files` and `forbid`", out)
        code, out = self.run_gate(dict(PILOT, known=[{"file": "a.py", "module": "django"}]))
        self.assertEqual(code, 2, out)
        self.assertIn("`reason`", out)

    def test_no_layering_passes(self):
        (self.root / ".migration").mkdir()
        (self.root / ".migration/profile.yaml").write_text("gates: {}\n")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(check_layers.main(["--root", str(self.root)]), 0)
        self.assertIn("contracts=0", out.getvalue())

    def test_globs(self):
        self.assertTrue(check_layers.glob_match("src/a/application/x.py", "src/*/application/**/*.py"))
        self.assertTrue(check_layers.glob_match("src/a/application/b/c/x.py", "src/*/application/**/*.py"))
        self.assertFalse(check_layers.glob_match("src/a/b/application/x.py", "src/*/application/**/*.py"))
        self.assertFalse(check_layers.glob_match("src/loans/services_test.py", "src/*/services.py"))


class ValidateLayeringGateTest(unittest.TestCase):
    def test_layering_without_the_gate_command_is_an_error(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import validate
        errors = []
        validate.check_layering_gate("profile.yaml", {"layering": PILOT, "gates": {"idiom": ["ruff check"]}}, errors)
        self.assertTrue(errors and "check_layers.py" in errors[0], errors)
        errors = []
        validate.check_layering_gate("profile.yaml", {"layering": PILOT, "gates": {
            "idiom": ["ruff check", "python .migration/harness/tools/check_layers.py"]}}, errors)
        self.assertEqual(errors, [])

    def test_schema_accepts_the_example(self):
        import json

        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "schemas/profile.schema.json").read_text())
        sub = schema["properties"]["layering"]
        Draft202012Validator(sub).validate(dict(PILOT, known=[{"file": "a.py", "module": "django", "reason": "r"}]))

    def test_cli_runs(self):
        out = subprocess.run([sys.executable, str(ROOT / "tools/check_layers.py"), "--help"],
                             capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
