"""afs-spec (ADR-0061): customer tests as data, checked and run the same way on every target."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import pathlib
import sys
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
  given: {fixtures: [.migration/spec/fees-payments/fixtures/loans.json], clock: "2026-02-01"}
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
        (self.root / "spec/fees-payments/fixtures").mkdir()
        (self.root / "spec/fees-payments/fixtures/loans.json").write_text("[]")

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
        self.assertEqual(adapter.givens[0], {"fixtures": [".migration/spec/fees-payments/fixtures/loans.json"], "clock": "2026-02-01"})
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
        doc["cases"][0]["ruling"] = "o/t#7"
        doc["cases"][1]["oracle"] = "tests/characterization/goldens/fees.json"
        self.path.write_text(yaml.safe_dump(doc))
        (self.root / "ledger/fees.calculation.yaml").write_text(yaml.safe_dump(dict(LEDGER, quirks=["o/t#7"])))
        self.assertEqual(self.check(require=True), [])                   # a ruling sets the values instead
        self.assertIn("- expected values set by quirk ruling o/t#7",
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

    def test_a_recording_may_nest_its_exchanges(self):
        rec = self.mig / "characterization/goldens/gateway.json"
        rec.write_text(json.dumps({"gateway_requests": [], "responses": self.RECORDING}))
        ex = sp.load_exchange(self.repo, {"recording": ".migration/characterization/goldens/gateway.json",
                                          "under": "responses", "exchange": "GET /fees/unknown"})
        self.assertEqual(ex["response"]["status"], 404)

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


class ContractTest(unittest.TestCase):
    """ADR-0068: contracts at a boundary: a real HTTP stub per gateway, the requests sent, the shape of a response."""

    def test_a_stub_answers_in_order_records_requests_and_is_found_through_the_environment(self):
        import os
        import urllib.error
        import urllib.request
        sys.path.insert(0, str(ROOT / "tools"))
        import afs_spec_stub as stub
        wanted = {"payment": {"respond": [{"status": 200, "body": "charged\n"}, {"status": 402, "body": "declined\n"}]},
                  "maps": {"unreachable": True}}
        config = {"payment": {"env": "PAYMENT_GATEWAY_URL"}, "maps": {"env": "MAP_URL"}}
        with stub.gateways(wanted, config) as stubs:
            base = os.environ["PAYMENT_GATEWAY_URL"]
            first = urllib.request.urlopen(urllib.request.Request(base + "/charge?loan=L1", method="POST"))
            self.assertEqual((first.status, first.read()), (200, b"charged\n"))
            for _ in range(2):                                   # the last answer repeats
                with self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(urllib.request.Request(base + "/charge?loan=L2", method="POST", data=b"x=1"))
                self.assertEqual(e.exception.code, 402)
            with self.assertRaises(OSError):
                urllib.request.urlopen(os.environ["MAP_URL"] + "/tiles", timeout=2)
            got = stub.sent(stubs)
        self.assertNotIn("PAYMENT_GATEWAY_URL", os.environ)
        self.assertEqual([(r["method"], r["path"]) for r in got["payment"]],
                         [("POST", "/charge?loan=L1"), ("POST", "/charge?loan=L2"), ("POST", "/charge?loan=L2")])
        self.assertEqual(got["payment"][1]["body"], "x=1")
        self.assertEqual(got["maps"], [])
        with self.assertRaises(ValueError):
            with stub.gateways({"sms": {"respond": {"status": 200}}}, config):
                pass

    def test_sent_and_schema_verdicts(self):
        want = {"payment": [{"method": "post", "path": "/charge?loan=L2"}]}
        ok = {"payment": [{"method": "POST", "path": "/charge?loan=L2", "body": ""}]}
        self.assertEqual(sp.sent_verdict(want, ok), [])
        self.assertIn("the target sent", sp.sent_verdict(want, {"payment": []})[0])
        self.assertIn("didn't put a stub", sp.sent_verdict(want, {})[0])
        schema = {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["legs"],
                                                            "properties": {"legs": {"type": "array"}}}}
        self.assertEqual(sp.schema_verdict(schema, {"json": [{"legs": []}, {"legs": [1]}]}), [])
        bad = sp.schema_verdict(schema, {"json": [{"legs": []}, {"edges": []}]})
        self.assertEqual(bad, ["schema: 1: 'legs' is a required property"])
        self.assertEqual(sp.schema_verdict(schema, {"json": None}), ["schema: expected a JSON body, got none"])

    def test_an_integration_has_a_contract_case_or_says_why_not(self):
        with tempfile.TemporaryDirectory() as d:
            mig = pathlib.Path(d) / ".migration"
            (mig / "ledger").mkdir(parents=True)
            (mig / "spec/fees").mkdir(parents=True)
            led = {"id": "integration.payment-gateway", "kind": "integration", "characterization_tier": "B",
                   "rules": [{"id": "declined-is-502", "rule": "a declined charge answers 502"}]}
            (mig / "ledger/integration.payment-gateway.yaml").write_text(yaml.safe_dump(led))
            case = {"title": "A declined charge is reported", "rule": "declined-is-502", "oracle": "x",
                    "when": {"http": {"method": "POST", "path": "/payments/L2"}}, "then": {"status": 502}}
            (pathlib.Path(d) / "x").write_text("{}")
            spec_file = mig / "spec/fees/gateway.yaml"
            spec_file.write_text(yaml.safe_dump({"capability": "integration.payment-gateway", "cases": [case]}))
            check = lambda: "\n".join(sp.check(mig / "spec", mig / "ledger", True))
            self.assertIn("is an integration, so its contract is checked at the boundary", check())
            case.update(given={"gateways": {"payment": {"respond": {"status": 402, "body": "declined\n"}}}},
                        then={"status": 502, "sent": {"payment": [{"method": "POST", "path": "/charge?loan=L2"}]}})
            spec_file.write_text(yaml.safe_dump({"capability": "integration.payment-gateway", "cases": [case]}))
            self.assertEqual(check(), "")
            case["then"] = {"status": 200, "schema": "missing.json"}
            spec_file.write_text(yaml.safe_dump({"capability": "integration.payment-gateway", "cases": [case]}))
            self.assertIn("schema 'missing.json' can't be read as JSON", check())
            text = sp.render("fees", mig / "spec", mig / "ledger")
            self.assertIn("a body shaped as `missing.json`", text)


class PropertyTest(unittest.TestCase):
    """ADR-0069: a property case holds over a whole range; a failure is shrunk to the smallest failing input."""

    class FeeTarget:
        """Late fees for a loan due 2026-01-16: 25 cents a day after two free days, capped at $10 unless `broken`."""

        def __init__(self, broken_from=None):
            self.broken_from = broken_from
            self.calls = 0
            self.today = None

        def setup(self):
            pass

        def teardown(self):
            pass

        @contextlib.contextmanager
        def case(self, given):
            import datetime
            self.today = datetime.date.fromisoformat(given["clock"])
            yield

        def act(self, when):
            import datetime
            self.calls += 1
            days = max(0, (self.today - datetime.date(2026, 1, 16)).days)
            fee = 0 if days <= 2 else days * 0.25
            if self.broken_from is None or days < self.broken_from:
                fee = min(fee, 10)
            return {"status": 200, "text": f"{days} day(s) late. Fee: ${fee:.2f}", "json": None, "headers": {}}

    CASE = {"title": "The fee never exceeds $10, whatever the date", "rule": "fee-capped-at-10",
            "forall": {"today": {"date": {"from": "2026-01-16", "to": "2030-12-31"}}},
            "given": {"clock": "{today}"}, "when": {"http": {"method": "GET", "path": "/fees/L1"}},
            "then": {"status": 200, "number": {"pattern": r"Fee: \$([0-9.]+)", "max": 10}}}

    def expand(self):
        return sp.expand({"capability": "fees.calculation", "cases": [self.CASE]}, "late.yaml", root=".")

    def test_samples_cover_the_edges_and_repeat_from_run_to_run(self):
        rows = sp.samples(self.CASE["forall"], "late.yaml#1", 25)
        days = [r["today"] for r in rows]
        self.assertEqual(len(days), 25)
        for edge in ("2026-01-16", "2026-01-17", "2030-12-30", "2030-12-31"):
            self.assertIn(edge, days)
        self.assertEqual(rows, sp.samples(self.CASE["forall"], "late.yaml#1", 25))
        both = sp.samples({"n": {"int": {"from": 0, "to": 3}}, "loan": {"one_of": ["L1", "L2"]}}, "x", 50)
        self.assertEqual(len(both), 8)                         # every combination, no repeats

    def test_a_property_that_holds_passes_in_one_result(self):
        cases = self.expand()
        self.assertEqual(len(cases), 1)
        target = self.FeeTarget()
        results = sp.run_cases(cases, target)
        self.assertEqual([r["passed"] for r in results], [True])
        self.assertEqual(target.calls, 25)

    def test_a_broken_cap_is_found_and_shrunk_to_the_first_failing_day(self):
        results = sp.run_cases(self.expand(), self.FeeTarget(broken_from=41))
        failure = results[0]["failures"]
        self.assertFalse(results[0]["passed"])
        self.assertIn("fails for today=2026-02-26 (the smallest failing input found, from 25 tried)", failure[0])
        self.assertIn("number: 10.25 is above 10", failure[1])

    def test_forall_is_checked_and_rendered(self):
        with tempfile.TemporaryDirectory() as d:
            mig = pathlib.Path(d) / ".migration"
            (mig / "ledger").mkdir(parents=True)
            (mig / "spec/fees").mkdir(parents=True)
            (mig / "ledger/fees.calculation.yaml").write_text(yaml.safe_dump(LEDGER))
            bad = dict(self.CASE, forall={"today": {"date": {"from": "2030-01-01", "to": "2026-01-01"}}},
                       when={"http": {"method": "GET", "path": "/fees/{loan}"}},
                       examples={"columns": ["x"], "rows": [[1]]})
            (mig / "spec/fees/late.yaml").write_text(yaml.safe_dump({"capability": "fees.calculation", "cases": [bad]}))
            problems = "\n".join(sp.check(mig / "spec", mig / "ledger"))
            self.assertIn("has both `forall` and `examples`", problems)
            self.assertIn("runs from 2030-01-01 down to 2026-01-01", problems)
            self.assertIn("uses {loan} but its forall has no such name", problems)
            (mig / "spec/fees/late.yaml").write_text(yaml.safe_dump({"capability": "fees.calculation",
                                                                     "cases": [self.CASE]}))
            self.assertEqual(sp.check(mig / "spec", mig / "ledger"), [])
            text = sp.render("fees", mig / "spec", mig / "ledger")
            self.assertIn("- for every **today** from 2026-01-16 to 2030-12-31", text)
            self.assertIn("`Fee: \\$([0-9.]+)` is at most 10", text)


class SpecStrengthTest(unittest.TestCase):
    """ADR-0074: a spec proves each observed outcome, asserts more than a status, and cites only decided rulings."""
    ENTRY = {"id": "hold.place", "kind": "behavioral", "status": "pending", "characterization_tier": "A",
             "source": {"graph_node": "endpoint:legacy/src/main/java/lib/HoldResource.java:POST /holds"},
             "evidence": [".migration/characterization/source/goldens/holds.json"],
             "quirks": ["o/t#7"],
             "rules": [{"id": "hold-placed", "rule": "A hold on a book out on loan is placed."},
                       {"id": "hold-limit", "rule": "A member's holds are limited."}]}
    RECORDING = {
        "POST /holds": {"request": {"method": "POST", "path": "/holds", "form": {"member": "dee", "isbn": "1"}},
                        "response": {"status": 201, "body": "H2;dee;1\n"}},
        "POST /holds missing member": {"request": {"method": "POST", "path": "/holds", "form": {"isbn": "1"}},
                                       "response": {"status": 400, "body": "member and isbn are required\n"}},
        "POST /holds fifth hold": {"request": {"method": "POST", "path": "/holds", "form": {"member": "hal", "isbn": "5"}},
                                   "response": {"status": 409, "body": "hold limit reached\n"}},
        "GET /holds": {"request": {"method": "GET", "path": "/holds"}, "response": {"status": 200, "body": ""}}}
    REC = ".migration/characterization/source/goldens/holds.json"

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._d.name)
        self.root = self.repo / ".migration"
        (self.root / "ledger").mkdir(parents=True)
        (self.root / "spec/holds").mkdir(parents=True)
        (self.repo / self.REC).parent.mkdir(parents=True)
        (self.repo / self.REC).write_text(json.dumps(self.RECORDING))
        (self.root / "ledger/hold.place.yaml").write_text(yaml.safe_dump(self.ENTRY))
        self.path = self.root / "spec/holds/place.yaml"

    def tearDown(self):
        self._d.cleanup()

    def write(self, cases):
        self.path.write_text(yaml.safe_dump({"capability": "hold.place", "title": "Holds", "cases": cases}))
        return "\n".join(sp.check(self.root / "spec", self.root / "ledger", True))

    def replay(self, exchange, rule="hold-placed"):
        return {"title": exchange, "rule": rule, "when": {"replay": {"recording": self.REC, "exchange": exchange}},
                "then": {"replay": {"body": "exact"}}}

    def test_every_recorded_outcome_of_the_endpoint_needs_a_case(self):
        problems = self.write([self.replay("POST /holds"), self.replay("POST /holds fifth hold", "hold-limit")])
        self.assertIn("answered POST /holds with 400", problems)
        self.assertNotIn("with 201", problems)
        self.assertNotIn("with 409", problems)
        self.assertNotIn("with 200", problems)          # GET /holds is another endpoint
        problems = self.write([self.replay("POST /holds"), self.replay("POST /holds fifth hold", "hold-limit"),
                               self.replay("POST /holds missing member")])
        self.assertEqual(problems, "")

    def test_a_case_that_checks_only_the_status_is_refused(self):
        case = {"title": "a hold is placed", "rule": "hold-placed", "oracle": self.REC,
                "when": {"http": {"method": "POST", "path": "/holds", "form": {"member": "dee", "isbn": "1"}}},
                "then": {"status": 201}}
        others = [self.replay("POST /holds fifth hold", "hold-limit"), self.replay("POST /holds missing member")]
        self.assertIn("checks only the status", self.write([case] + others))
        case["then"]["text"] = ["H2;dee;1"]
        self.assertEqual(self.write([case] + others), "")

    def test_a_ruling_must_be_a_quirk_raised_on_the_capability(self):
        fixed = {"title": "a fourth hold is refused", "rule": "hold-limit", "ruling": "the operator said so",
                 "when": {"http": {"method": "POST", "path": "/holds", "form": {"member": "hal", "isbn": "4"}}},
                 "then": {"status": 409, "text": ["hold limit reached"]}}
        base = [self.replay("POST /holds"), self.replay("POST /holds missing member"), fixed]
        self.assertIn("a ruling is the quirk issue that decided it", self.write(base))
        fixed["ruling"] = "o/t#99"
        self.assertIn("doesn't list under `quirks` (o/t#7)", self.write(base))
        fixed["ruling"] = "o/t#7"
        self.assertEqual(self.write(base), "")

    def test_a_cited_ruling_must_be_decided_on_github(self):
        cites = {"o/t#7": ["place.yaml: case 3"]}
        open_quirk = lambda ref: ({"state": "open", "state_reason": None}, [])
        self.assertIn("isn't decided yet", "\n".join(sp.ruling_problems(cites, open_quirk)))
        no_comment = lambda ref: ({"state": "closed", "state_reason": "completed"}, [{"body": "looks fine"}])
        self.assertIn("no ruling comment", "\n".join(sp.ruling_problems(cites, no_comment)))
        dropped = lambda ref: ({"state": "closed", "state_reason": "not_planned"}, [{"body": "**Ruling: fix"}])
        self.assertIn("isn't decided yet", "\n".join(sp.ruling_problems(cites, dropped)))
        def missing(ref):
            raise RuntimeError("HTTP 404: Not Found")
        self.assertIn("can't be read from GitHub", "\n".join(sp.ruling_problems(cites, missing)))
        ruled = lambda ref: ({"state": "closed", "state_reason": "completed"},
                             [{"body": "**Ruling (operator, 2026-11-23): fix** — three holds at most."}])
        self.assertEqual(sp.ruling_problems(cites, ruled), [])

    def test_spec_rulings_lists_each_cited_ruling(self):
        self.write([dict(self.replay("POST /holds"), ruling="o/t#7")])
        self.assertEqual(list(sp.spec_rulings(self.root / "spec")), ["o/t#7"])


class SpecOwnedSetupTest(unittest.TestCase):
    """ADR-0078: a case's starting state is the spec's own: public setup requests, or fixtures under .migration/spec/."""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._d.name)
        self.root = self.repo / ".migration"
        (self.root / "ledger").mkdir(parents=True)
        (self.root / "spec/holds").mkdir(parents=True)
        (self.root / "ledger/hold.place.yaml").write_text(yaml.safe_dump(
            {"id": "hold.place", "kind": "behavioral", "status": "pending",
             "rules": [{"id": "limit", "rule": "A member's holds are limited."}]}))
        self.path = self.root / "spec/holds/place.yaml"

    def tearDown(self):
        self._d.cleanup()

    def check(self, given, examples=None):
        case = {"title": "a fourth hold", "rule": "limit", "oracle": ".migration/spec/holds/place.yaml",
                "given": given, "when": {"http": {"method": "POST", "path": "/holds", "form": {"member": "hal"}}},
                "then": {"status": 201, "text": ["H5"]}}
        if examples:
            case["examples"] = examples
        self.path.write_text(yaml.safe_dump({"capability": "hold.place", "title": "Holds", "cases": [case]}))
        return "\n".join(sp.check(self.root / "spec", self.root / "ledger", True))

    def test_setup_requests_are_valid_spec_data(self):
        self.assertEqual(self.check({"requests": [{"method": "POST", "path": "/loans", "form": {"isbn": "1"}},
                                                  {"method": "POST", "path": "/holds", "form": {"isbn": "1"}}]}), "")

    def test_a_fixture_the_build_writes_is_refused(self):
        self.assertIn("isn't part of the spec", self.check({"fixtures": ["tests/holds/fixtures/three.json"]}))
        self.assertIn("isn't part of the spec", self.check(
            {"fixtures": ["{fx}"]}, {"columns": ["fx"], "rows": [["tests/holds/fixtures/three.json"]]}))

    def built(self):
        (self.root / "ledger/hold.place.yaml").write_text(yaml.safe_dump(
            {"id": "hold.place", "kind": "behavioral", "status": "in-progress",
             "rules": [{"id": "limit", "rule": "A member's holds are limited."}]}))

    def test_a_fixture_under_the_spec_must_exist(self):
        self.built()
        self.assertIn("doesn't exist", self.check({"fixtures": [".migration/spec/holds/fixtures/three.json"]}))
        (self.root / "spec/holds/fixtures").mkdir()
        (self.root / "spec/holds/fixtures/three.json").write_text("[]")
        self.assertEqual(self.check({"fixtures": [".migration/spec/holds/fixtures/three.json"]}), "")

    def test_a_capability_not_built_yet_sets_up_by_requests_not_fixtures(self):
        """ADR-0079: before the code exists a fixture can only guess its schema."""
        (self.root / "spec/holds/fixtures").mkdir()
        (self.root / "spec/holds/fixtures/expiry.json").write_text('[{"model": "holds.hold"}]')
        problems = self.check({"fixtures": [".migration/spec/holds/fixtures/expiry.json"]})
        self.assertIn("isn't built yet", problems)
        self.assertIn("its own `clock`", problems)
        self.assertEqual(self.check({"clock": "2026-11-23", "requests": [
            {"method": "POST", "path": "/holds", "form": {"member": "bo"}, "clock": "2026-10-24"}]}), "")

    def test_a_setup_request_holds_its_own_clock_while_it_is_sent(self):
        import afs_spec_django
        log = []

        @contextlib.contextmanager
        def clock(value):
            log.append(f"clock {value}")
            yield
            log.append("clock restored")

        def http(req):
            log.append(f"{req['path']} clock-key={'clock' in req}")
            return {"status": 201, "text": ""}

        afs_spec_django.send_setup_requests({"requests": [
            {"method": "POST", "path": "/past", "clock": "2026-10-24"},
            {"method": "POST", "path": "/today"}]}, http, clock)
        self.assertEqual(log, ["clock 2026-10-24", "/past clock-key=False", "clock restored", "/today clock-key=False"])

    def test_setup_requests_run_in_order_and_each_must_succeed(self):
        import afs_spec_django
        sent = []

        def http(req):
            sent.append(req["path"])
            return {"status": 409 if req["path"] == "/bad" else 201, "text": "hold limit reached\n"}

        afs_spec_django.send_setup_requests({"requests": [{"method": "POST", "path": "/a"},
                                                          {"method": "POST", "path": "/b"}]}, http)
        self.assertEqual(sent, ["/a", "/b"])
        with self.assertRaisesRegex(RuntimeError, r"setup request 2 \(POST /bad\) answered 409"):
            afs_spec_django.send_setup_requests({"requests": [{"method": "POST", "path": "/a"},
                                                              {"method": "POST", "path": "/bad"}]}, http)
