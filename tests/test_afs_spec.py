"""afs-spec (ADR-0061): customer tests as data, checked and run the same way on every target."""
import contextlib
import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import textwrap
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("afs_spec", str(ROOT / "tools/afs-spec"))
spec = importlib.util.spec_from_loader("afs_spec", loader)
sp = importlib.util.module_from_spec(spec)
loader.exec_module(sp)

LEDGER = {"id": "fees.calculation", "kind": "behavioral", "rules": [
    {"id": "fee-waived-two-days", "rule": "Up to two days late costs nothing."},
    {"id": "fee-25-cents-a-day", "rule": "Each day late costs 25 cents."},
    {"id": "fee-capped-at-10", "rule": "The fee never exceeds $10."}]}

SPEC = """
capability: fees.calculation
title: Late fees
background:
  given: {fixtures: [loans.json], clock: "2026-02-01"}
cases:
  - title: A loan returned two days late costs nothing
    rule: fee-waived-two-days
    when: {http: {method: GET, path: /fees/L2}}
    then: {status: 200, json: {fee: "0.00"}}
  - title: Late fees by loan
    rule: [fee-25-cents-a-day, fee-capped-at-10]
    examples:
      columns: [loan, fee]
      rows: [[L3, "4.75"], [L1, "10.00"]]
    when: {http: {method: GET, path: "/fees/{loan}"}}
    then: {status: 200, json: {fee: "{fee}"}}
"""


class FakeAdapter:
    """Answers like the synthetic fees endpoint, from a table, and records what each case set up."""

    FEES = {"L1": "10.00", "L2": "0.00", "L3": "4.75"}

    def __init__(self, wrong=None):
        self.wrong = wrong or {}
        self.givens = []
        self.events = []

    def setup(self):
        self.events.append("setup")

    def teardown(self):
        self.events.append("teardown")

    @contextlib.contextmanager
    def case(self, given):
        self.givens.append(given)
        yield

    def act(self, when):
        loan = when["http"]["path"].rsplit("/", 1)[-1]
        fee = self.wrong.get(loan, self.FEES.get(loan))
        return {"status": 200 if fee else 404, "json": {"fee": fee, "loan": loan}, "text": "", "headers": {}}


class SpecTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._d.name)
        (self.root / "ledger").mkdir()
        (self.root / "ledger/fees.calculation.yaml").write_text(yaml.safe_dump(LEDGER))
        (self.root / "spec/fees-payments").mkdir(parents=True)
        self.path = self.root / "spec/fees-payments/late-fees.yaml"
        self.path.write_text(textwrap.dedent(SPEC))

    def tearDown(self):
        self._d.cleanup()

    def check(self, require=False):
        return sp.check(self.root / "spec", self.root / "ledger", require)

    def test_a_sound_spec_checks_clean_and_proves_every_rule(self):
        self.assertEqual(self.check(require=True), [])

    def test_an_unknown_rule_an_empty_then_and_a_missing_column_are_refused(self):
        doc = yaml.safe_load(self.path.read_text())
        doc["cases"][0]["rule"] = "fee-waived-forever"
        doc["cases"][1]["examples"]["columns"] = ["loan"]
        doc["cases"][1]["examples"]["rows"] = [["L3"]]
        doc["cases"].append({"title": "says nothing", "rule": "fee-capped-at-10",
                             "when": {"http": {"method": "GET", "path": "/fees/L1"}}, "then": {}})
        self.path.write_text(yaml.safe_dump(doc))
        # an assertion-free case is refused by the schema, before anything else is read from the file
        self.assertIn("cases/2/then: {} should be non-empty", "\n".join(self.check()))
        doc["cases"].pop()
        self.path.write_text(yaml.safe_dump(doc))
        problems = "\n".join(self.check())
        self.assertIn("names rule 'fee-waived-forever'", problems)
        self.assertIn("uses {fee} but its examples have no such column", problems)

    def test_require_names_a_rule_no_case_proves(self):
        doc = yaml.safe_load(self.path.read_text())
        doc["cases"] = doc["cases"][:1]
        self.path.write_text(yaml.safe_dump(doc))
        problems = self.check(require=True)
        self.assertEqual(len(problems), 2)
        self.assertIn("rule 'fee-25-cents-a-day' of fees.calculation has no case", problems[0])

    def test_examples_expand_with_the_background_and_run_through_the_adapter(self):
        cases = sp.expand(yaml.safe_load(self.path.read_text()), "late-fees.yaml")
        self.assertEqual([c["id"] for c in cases], ["late-fees.yaml#1", "late-fees.yaml#2.1", "late-fees.yaml#2.2"])
        self.assertEqual(cases[2]["when"]["http"]["path"], "/fees/L1")
        self.assertEqual(cases[2]["then"]["json"], {"fee": "10.00"})
        adapter = FakeAdapter()
        results = sp.run_cases(cases, adapter)
        self.assertTrue(all(r["passed"] for r in results), results)
        self.assertEqual(adapter.givens[0], {"fixtures": ["loans.json"], "clock": "2026-02-01"})
        self.assertEqual(adapter.events, ["setup", "teardown"])

    def test_a_wrong_answer_fails_with_a_readable_diff(self):
        cases = sp.expand(yaml.safe_load(self.path.read_text()), "late-fees.yaml")
        results = sp.run_cases(cases, FakeAdapter(wrong={"L1": "12.50"}))
        bad = [r for r in results if not r["passed"]]
        self.assertEqual([r["id"] for r in bad], ["late-fees.yaml#2.2"])
        self.assertIn("fee: '10.00'", bad[0]["failures"][0])
        self.assertIn("fee: '12.50'", bad[0]["failures"][0])

    def test_text_header_and_numeric_assertions(self):
        result = {"status": 200, "json": {"amount": 4.75, "items": [1, 2]}, "text": "<p role=alert>Payment failed</p>",
                  "headers": {"hx-trigger": "paid"}}
        self.assertEqual(sp.verdict({"json": {"amount": "4.75", "items": [1, 2]}, "text": ["Payment failed"],
                                     "not_text": ["Traceback"], "headers": {"HX-Trigger": "paid"}}, result), [])
        self.assertEqual(len(sp.verdict({"json": {"items": [1]}, "not_text": ["Payment"]}, result)), 2)

    def test_render_lists_each_rule_with_its_cases_and_results(self):
        results = [{"id": str(self.path) + "#1", "passed": True}, {"id": str(self.path) + "#2.1", "passed": False}]
        text = sp.render("fees-payments", self.root / "spec", self.root / "ledger", results)
        self.assertIn("**fee-waived-two-days**: Up to two days late costs nothing.", text)
        self.assertIn("✅ A loan returned two days late costs nothing: `GET /fees/L2` → 200", text)
        self.assertIn("❌ Late fees by loan — loan=L3, fee=4.75", text)

    def test_the_cli_runs_check(self):
        code = sp.main(["check", "--spec", str(self.root / "spec"), "--ledger", str(self.root / "ledger"), "--require"])
        self.assertEqual(code, 0)


class SchemaTest(unittest.TestCase):
    def test_the_schema_is_valid_and_refuses_an_action_with_two_entry_points(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas/spec.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        doc = yaml.safe_load(SPEC)
        doc["cases"][0]["when"]["command"] = {"name": "export"}
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(doc))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
