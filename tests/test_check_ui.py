"""tools/check_ui.py: htmx error responses render, and the built CSS holds the templates' utilities (phase 3e)."""
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
import check_ui  # noqa: E402

CSS = ".py-4{padding-block:1rem}.text-\\[\\#66705b\\]{color:#66705b}.hover\\:bg-\\[\\#873b2a\\]:hover{x:y}"


class UiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.write("README", "x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "work")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", *args], cwd=self.root, check=True,
                       capture_output=True)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def run_gate(self, cfg, *extra):
        (self.root / ".migration").mkdir(exist_ok=True)
        (self.root / ".migration/profile.yaml").write_text(yaml.safe_dump({"ui_checks": cfg}))
        out = io.StringIO()
        with redirect_stdout(out):
            code = check_ui.main(["--root", str(self.root), "--changed-since", "main", *extra])
        return code, out.getvalue()

    HTMX = {"templates": ["templates/**/*.html"], "scripts": ["static/**/*.js"], "htmx_errors": True}

    def test_an_htmx_request_without_error_handling_fails(self):
        # Eval v3e-v3g: LL-03's 502 payment fragment and BK-05G's dialog 404 never showed.
        self.write("templates/fees/pay.html", '<form hx-post="/fees/pay" hx-target="#r"></form>\n')
        code, out = self.run_gate(self.HTMX)
        self.assertEqual(code, 1, out)
        self.assertIn("templates/fees/pay.html:1", out)
        self.assertIn("responseHandling", out)

    def test_error_handling_anywhere_satisfies_it(self):
        self.write("templates/fees/pay.html", '<form hx-post="/fees/pay"></form>\n')
        for where, text in [("templates/base.html",
                              '<meta name="htmx-config" content=\'{"responseHandling":[{"code":".*","swap":true}]}\'>'),
                             ("static/app.js", "document.body.addEventListener('htmx:beforeSwap', e => {});"),
                             ("templates/base.html", '<body hx-ext="response-targets" hx-target-error="#err">')]:
            with self.subTest(where=where):
                self.write(where, text)
                code, out = self.run_gate(self.HTMX)
                self.assertEqual(code, 0, out)
                (self.root / where).unlink()

    def test_only_changed_templates_are_checked(self):
        self.write("templates/old.html", '<button hx-get="/x"></button>\n')
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "earlier ticket")
        self.git("branch", "-f", "main", "HEAD")
        self.write("templates/new.html", "<p>no htmx</p>\n")
        code, out = self.run_gate(self.HTMX)
        self.assertEqual(code, 0, out)
        code, out = self.run_gate(self.HTMX, "--all")
        self.assertEqual(code, 1, out)

    def test_a_utility_the_built_css_lacks_fails(self):
        # Eval v3g: LL-04's About page used py-8, mt-8 and leading-relaxed; the LL-01 build had none of them.
        self.write("static/css/tailwind.css", CSS)
        self.write("templates/about.html", """\
            <section class="mx-auto py-8 text-[#66705b] card {% if x %}hidden{% endif %}">
              <p class="py-4 hover:bg-[#873b2a] leading-relaxed md:text-6xl my-js-hook"></p>
            </section>
            """)
        code, out = self.run_gate({"templates": ["templates/**/*.html"], "built_css": "static/css/tailwind.css"})
        self.assertEqual(code, 1, out)
        # A class inside a template tag ({% if %}hidden{% endif %}) is used too, so it counts.
        for missing in ("`mx-auto`", "`py-8`", "`leading-relaxed`", "`md:text-6xl`", "`hidden`"):
            self.assertIn(missing, out)
        for present_or_not_tailwind in ("`py-4`", "`text-[#66705b]`", "`hover:bg-[#873b2a]`", "`card`",
                                        "`my-js-hook`"):
            self.assertNotIn(present_or_not_tailwind, out)

    def test_css_escape(self):
        self.assertEqual(check_ui.css_escape("hover:bg-[#873b2a]"), ".hover\\:bg-\\[\\#873b2a\\]")
        self.assertEqual(check_ui.css_escape("w-1/2"), ".w-1\\/2")
        self.assertEqual(check_ui.css_escape("2xl:p-4"), ".\\32 xl\\:p-4")

    def test_utility_shapes(self):
        for token in ("py-8", "mt-8", "leading-relaxed", "text-[#66705b]", "md:text-6xl", "-mt-2", "flex",
                      "hover:bg-[#873b2a]", "w-1/2", "tracking-[.2em]"):
            self.assertTrue(check_ui.is_utility(token), token)
        for token in ("card", "btn", "card-body", "my-js-hook", "loan-row"):
            self.assertFalse(check_ui.is_utility(token), token)

    def test_config(self):
        code, out = self.run_gate({"templates": ["templates/**/*.html"]})
        self.assertEqual(code, 2, out)
        code, out = self.run_gate({"templates": ["t/*.html"], "built_css": "missing.css"})
        self.assertEqual(code, 0, out)        # no changed template: the stylesheet isn't read

    def test_no_ui_checks_passes(self):
        (self.root / ".migration").mkdir()
        (self.root / ".migration/profile.yaml").write_text("gates: {}\n")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(check_ui.main(["--root", str(self.root)]), 0)


class ValidateUiGateTest(unittest.TestCase):
    def test_ui_checks_without_the_gate_command_is_an_error(self):
        import validate
        errors = []
        validate.check_layering_gate("p.yaml", {"ui_checks": UiTest.HTMX, "gates": {"idiom": ["ruff check"]}}, errors)
        self.assertTrue(errors and "check_ui.py" in errors[0], errors)
        errors = []
        validate.check_layering_gate("p.yaml", {"ui_checks": UiTest.HTMX, "gates": {
            "idiom": ["python .migration/harness/tools/check_ui.py"]}}, errors)
        self.assertEqual(errors, [])

    def test_schema(self):
        import json

        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "schemas/profile.schema.json").read_text())
        Draft202012Validator(schema["properties"]["ui_checks"]).validate(
            dict(UiTest.HTMX, built_css="static/css/tailwind.css"))


if __name__ == "__main__":
    unittest.main()
