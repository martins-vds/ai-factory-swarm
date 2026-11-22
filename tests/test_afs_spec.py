"""afs-spec (ADR-0061): customer tests as data, checked and run the same way on every target."""
import contextlib
import importlib.machinery
import importlib.util
import io
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

LEDGER = {"id": "fees.calculation", "kind": "behavioral", "status": "migrated", "rules": [
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
    oracle: tests/characterization/goldens/fees.json
    when: {http: {method: GET, path: /fees/L2}}
    then: {status: 200, json: {fee: "0.00"}}
  - title: Late fees by loan
    rule: [fee-25-cents-a-day, fee-capped-at-10]
    oracle: tests/characterization/goldens/fees.json
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
        self.repo = pathlib.Path(self._d.name)
        self.root = self.repo / ".migration"
        (self.root / "ledger").mkdir(parents=True)
        golden = self.repo / "tests/characterization/goldens/fees.json"
        golden.parent.mkdir(parents=True)
        golden.write_text("{}")
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
        self.assertIn("### A loan returned two days late costs nothing", text)
        self.assertIn("- proves **fee-waived-two-days**: Up to two days late costs nothing.", text)
        self.assertIn("Result: ✅ passed", text)
        self.assertIn("| loan | fee | result |", text)
        self.assertIn("| L3 | 4.75 | ❌ failed |", text)
        self.assertIn("| L1 | 10.00 | not run yet |", text)

    def test_a_clock_can_come_from_the_examples(self):
        doc = yaml.safe_load(self.path.read_text())
        doc["cases"][1]["given"] = {"clock": "{day}"}
        doc["cases"][1]["examples"] = {"columns": ["loan", "fee", "day"],
                                       "rows": [["L3", "4.75", "2026-02-01"], ["L1", "10.00", "2026-06-30"]]}
        self.path.write_text(yaml.safe_dump(doc))
        self.assertEqual(self.check(require=True), [])
        cases = sp.expand(doc, "x.yaml")
        self.assertEqual(cases[2]["given"]["clock"], "2026-06-30")

    def test_the_cli_runs_check(self):
        code = sp.main(["check", "--spec", str(self.root / "spec"), "--ledger", str(self.root / "ledger"), "--require"])
        self.assertEqual(code, 0)


    def test_with_require_every_case_says_where_its_values_come_from(self):
        doc = yaml.safe_load(self.path.read_text())
        del doc["cases"][0]["oracle"]
        doc["cases"][1]["oracle"] = "tests/characterization/goldens/nowhere.json"
        self.path.write_text(yaml.safe_dump(doc))
        problems = "\n".join(self.check(require=True))
        self.assertIn("case 1 ('A loan returned two days late costs nothing') says neither where", problems)
        self.assertIn("names oracle 'tests/characterization/goldens/nowhere.json', which doesn't exist", problems)
        self.assertNotIn("says neither", "\n".join(self.check()))       # without require, only a bad path counts
        doc["cases"][0]["ruling"] = "Q-7"
        doc["cases"][1]["oracle"] = "tests/characterization/goldens/fees.json"
        self.path.write_text(yaml.safe_dump(doc))
        self.assertEqual(self.check(require=True), [])                   # a ruling sets the values instead
        self.assertIn("- expected values set by quirk ruling Q-7",
                      sp.render("fees-payments", self.root / "spec", self.root / "ledger"))

    def test_a_capability_not_built_yet_is_pending_not_failed(self):
        led = dict(LEDGER, status="pending")
        (self.root / "ledger/fees.calculation.yaml").write_text(yaml.safe_dump(led))
        out = self.root / "runs/spec-results.json"
        argv = ["run", "--spec", str(self.root / "spec"), "--ledger", str(self.root / "ledger"),
                "--results", str(out)]
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(sp.main(argv), 0)                           # no adapter is even loaded
        self.assertIn("PEND fees.calculation: not built yet (ledger status 'pending')", printed.getvalue())
        self.assertIn("AFS-RESULT gate=spec cases=0 failed=0 pending=3 pending_caps=fees.calculation",
                      printed.getvalue())
        results = json.loads(out.read_text())["results"]
        self.assertTrue(all(r["pending"] for r in results))
        text = sp.render("fees-payments", self.root / "spec", self.root / "ledger", results)
        self.assertIn("Result: ⏳ not built yet", text)
        # once the Migrator marks it in progress, the same cases run and must pass
        cases = sp.expand(yaml.safe_load(self.path.read_text()), "late-fees.yaml")
        self.assertEqual(sp.run_cases(cases, FakeAdapter(), pending={"fees.calculation"})[0]["passed"], None)
        self.assertTrue(all(r["passed"] for r in sp.run_cases(cases, FakeAdapter(), pending=set())))


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


class ReplayTest(unittest.TestCase):
    """ADR-0067: a recorded legacy exchange is the oracle; the runner replays it and compares the response."""

    RECORDING = {"GET /fees/{id}": {"request": {"method": "GET", "path": "/fees/L3", "form": None},
                                    "response": {"status": 200, "content_type": "text/html", "body":
                                                 "<h1>Late fee for L3</h1><p>Due 2025-12-15, 19 day(s) late.</p>"
                                                 "<p class=\"fee\">Fee: $4.75</p>"}},
                 "GET /fees/unknown": {"request": {"method": "GET", "path": "/fees/unknown"},
                                       "response": {"status": 404, "body": "<p>No such loan.</p>"}}}

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._d.name)
        self.mig = self.repo / ".migration"
        (self.mig / "ledger").mkdir(parents=True)
        (self.mig / "ledger/fees.page.yaml").write_text(yaml.safe_dump({
            "id": "fees.page", "status": "migrated", "characterization_tier": "A",
            "rules": [{"id": "fee-page", "rule": "shows the fee"}, {"id": "unknown-404", "rule": "404 for no loan"}]}))
        rec = self.mig / "characterization/goldens/http.json"
        rec.parent.mkdir(parents=True)
        rec.write_text(json.dumps(self.RECORDING))
        (self.mig / "spec/fees").mkdir(parents=True)
        self.path = self.mig / "spec/fees/page.yaml"
        self.write([{"title": "Each recorded fee page comes back the same", "rule": ["fee-page", "unknown-404"],
                     "examples": {"columns": ["file", "name"], "rows": [
                         ["http.json", "GET /fees/{id}"], ["http.json", "GET /fees/unknown"]]},
                     "when": {"replay": {"recording": ".migration/characterization/goldens/{file}",
                                         "exchange": "{name}"}},
                     "then": {"replay": {"body": "text"}}}])

    def tearDown(self):
        self._d.cleanup()

    def write(self, cases):
        self.path.write_text(yaml.safe_dump({"capability": "fees.page", "cases": cases}))

    def check(self, require=True):
        return sp.check(self.mig / "spec", self.mig / "ledger", require)

    def cases(self):
        return sp.expand(yaml.safe_load(self.path.read_text()), self.path)

    def test_a_replay_is_its_own_oracle_and_expands_to_the_recorded_request(self):
        self.assertEqual(self.check(), [])
        first, second = self.cases()
        self.assertEqual(first["when"], {"http": {"method": "GET", "path": "/fees/L3"}})
        self.assertEqual(first["then"]["status"], 200)
        self.assertEqual(second["then"]["status"], 404)
        self.assertEqual(second["then"]["replay"]["source"], ".migration/characterization/goldens/http.json#GET /fees/unknown")

    def test_text_mode_ignores_markup_and_whitespace_but_not_a_wrong_value(self):
        case = self.cases()[0]
        same = {"status": 200, "text": "<main>\n <h1>Late fee for L3</h1>\n<p>Due 2025-12-15, 19 day(s) late.</p>"
                                       "<p>Fee: &#36;4.75</p></main>"}
        self.assertEqual(sp.verdict(case["then"], same), [])
        wrong = dict(same, text=same["text"].replace("4.75", "4.50"))
        failure = sp.verdict(case["then"], wrong)
        self.assertEqual(len(failure), 1)
        self.assertIn("body (text) differs", failure[0])
        self.assertIn("Fee: $4.50", failure[0])

    def test_exact_json_masks_and_ignore(self):
        v = sp.replay_verdict
        self.assertEqual(v({"body": "exact", "expected": "a \r\nb\n"}, {"text": "a\nb"}), [])
        self.assertTrue(v({"body": "exact", "expected": "<p>a</p>"}, {"text": "<p> a</p>"}))
        self.assertEqual(v({"body": "json", "expected": '{"a": 1, "b": [1, 2]}'}, {"text": '{"b":[1,2],"a":1}'}), [])
        self.assertTrue(v({"body": "json", "expected": '{"a": 1}'}, {"text": '{"a": 2}'}))
        masked = {"body": "text", "expected": "Due 2026-01-16", "mask": [r"\d{4}-\d{2}-\d{2}"]}
        self.assertEqual(v(masked, {"text": "Due 2026-11-22"}), [])
        self.assertEqual(v({"body": "ignore", "expected": "x"}, {"text": "y"}), [])

    def test_a_missing_exchange_or_a_replay_without_a_comparison_is_refused(self):
        self.write([{"title": "A page nobody recorded", "rule": "fee-page",
                     "when": {"replay": {"recording": ".migration/characterization/goldens/http.json",
                                         "exchange": "GET /fees/L9"}},
                     "then": {"status": 200}}])
        problems = "\n".join(self.check())
        self.assertIn("has no exchange 'GET /fees/L9'", problems)
        self.assertIn("`then` has no `replay`", problems)

    def test_a_tier_a_capability_replays_something_or_says_why_not(self):
        self.write([{"title": "The fee page shows the fee", "rule": ["fee-page", "unknown-404"], "oracle":
                     ".migration/characterization/goldens/http.json",
                     "when": {"http": {"method": "GET", "path": "/fees/L3"}}, "then": {"text": ["$4.75"]}}])
        self.assertIn("characterized at tier A, so its recorded exchanges can be replayed", "\n".join(self.check()))
        self.assertNotIn("tier A", "\n".join(self.check(require=False)))
        led = yaml.safe_load((self.mig / "ledger/fees.page.yaml").read_text())
        led["no_replay"] = "the page is a JSF conversation; each step depends on the session"
        (self.mig / "ledger/fees.page.yaml").write_text(yaml.safe_dump(led))
        self.assertEqual(self.check(), [])

    def test_the_rendered_spec_says_what_is_replayed(self):
        text = sp.render("fees", self.mig / "spec", self.mig / "ledger")
        self.assertIn("the recorded exchange `{name}` (`.migration/characterization/goldens/{file}`) is replayed", text)
        self.assertIn("the same status and body as recorded (text)", text)
        self.assertIn("| http.json | GET /fees/unknown | not run yet |", text)
