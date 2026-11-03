"""tools/enrich_graph.py and the graph gate (ADR-0020): deterministic links Understand Anything can't infer."""
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests/fixtures/graph"
sys.path.insert(0, str(ROOT / "tools"))
import check_graph  # noqa: E402
import enrich_graph  # noqa: E402


def enrich(kind, base=None):
    """The fixture graph as the workflow builds it: Graphify's language layer first, then the enricher."""
    g = enrich_graph.Graph(base or {"project": {}, "nodes": [], "edges": []})
    folder = "javaee" if kind == "java-ee" else "django"
    enrich_graph.merge_graphify(g, json.loads((FIX / f"{folder}.graphify.json").read_text()))
    enrich_graph.ENRICHERS[kind](g, FIX / folder)
    return g


def edges(g, etype):
    name = {n["id"]: n["name"] for n in g.doc["nodes"]}
    return {(name[e["source"]], name[e["target"]]) for e in g.doc["edges"] if e["type"] == etype}


def path(g, anchor):
    by_id = {n["id"]: n for n in g.doc["nodes"]}
    return check_graph.data_path(anchor, g.doc["nodes"], g.doc["edges"], by_id)


class JavaEETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = enrich("java-ee")

    def test_entities_become_tables(self):
        self.assertEqual(edges(self.g, "defines_schema"), {("Order", "orders"), ("Customer", "Customer")})

    def test_repository_reads_and_writes(self):
        self.assertEqual(edges(self.g, "reads_from"), {("JpaOrderRepository", "orders"),
                                                       ("JpaOrderRepository", "Customer")})
        self.assertEqual(edges(self.g, "writes_to"), {("JpaOrderRepository", "orders"),
                                                      ("JpaOrderRepository", "Customer")}, "incl. a for-each variable")

    def test_named_query_annotation_is_not_a_cdi_bean(self):
        self.assertNotIn("Unused", {t for _, t in edges(self.g, "routes")})

    def test_dotted_bean_names_and_facelets_composition(self):
        routes = edges(self.g, "routes")
        self.assertIn(("src/main/webapp/public/orders.xhtml", "OrderView"), routes)
        self.assertIn(("src/main/webapp/public/dashboard.xhtml", "src/main/webapp/public/orders.xhtml"),
                      edges(self.g, "contains"))

    def test_jax_rs_endpoint_and_jms_hop(self):
        self.assertIn(("POST /orders/report", "OrderResource"), edges(self.g, "routes"))
        self.assertIn(("Events", "java:app/jms/OrderQueue"), edges(self.g, "publishes"))
        self.assertIn(("java:app/jms/OrderQueue", "OrderConsumer"), edges(self.g, "triggers"))

    def test_directed_paths_to_data(self):
        self.assertIn("←implements `JpaOrderRepository` →reads_from", path(self.g, "public/dashboard.xhtml"))
        jms = path(self.g, "endpoint=POST /orders/report")
        self.assertIn("→publishes", jms)
        self.assertIn("→triggers `OrderConsumer`", jms)
        self.assertTrue(path(self.g, "templates/layout.xhtml").startswith("**NO PATH**"))

    def test_websocket_endpoint_and_cdi_events(self):
        self.assertIn(("WS /live", "LivePush"), edges(self.g, "routes"))
        self.assertIn(("OrderChecker", "cdi-event @OrderChecked Order"), edges(self.g, "publishes"))
        triggers = edges(self.g, "triggers")
        self.assertIn(("cdi-event @OrderChecked Order", "LivePush"), triggers)
        self.assertNotIn(("cdi-event @OrderChecked Order", "AuditTrail"), triggers, "different event type")

    def test_schedule_and_batch_job(self):
        self.assertIn(("timer Nightly.run (minute=*/2, hour=*)", "Nightly"), edges(self.g, "triggers"))
        calls = edges(self.g, "calls")
        self.assertIn(("Nightly", "batch-job OrderImportJob"), calls)
        self.assertIn(("batch-job OrderImportJob", "OrderLineReader"), calls)
        self.assertIn(("batch-job OrderImportJob", "OrderLineWriter"), calls)

    def test_page_scripts_route_to_endpoints(self):
        routes = edges(self.g, "routes")
        self.assertIn(("src/main/webapp/public/live.xhtml", "POST /orders/report"), routes)
        self.assertIn(("src/main/webapp/public/live.xhtml", "WS /live"), routes)

    def test_directed_paths_through_async_hops(self):
        timer = path(self.g, "resource=timer Nightly.run (minute=*/2, hour=*)")
        self.assertIn("→calls `batch-job OrderImportJob`", timer)
        self.assertIn("→triggers `OrderConsumer`", timer)
        self.assertIn("→publishes", path(self.g, "public/live.xhtml"))

    def test_existing_nodes_are_reused_and_edges_carry_provenance(self):
        cid = "class:src/main/java/demo/infra/JpaOrderRepository.java:JpaOrderRepository"
        base = {"project": {}, "nodes": [{"id": cid, "type": "class", "name": "JpaOrderRepository", "summary": "llm",
                                          "tags": [], "complexity": "simple"}], "edges": []}
        g = enrich("java-ee", base)
        self.assertEqual([n["summary"] for n in g.doc["nodes"] if n["id"] == cid], ["llm"])
        self.assertTrue(all(e["description"].startswith("afs-enriched:") for e in g.doc["edges"]))
        before = len(g.doc["edges"])
        enrich_graph.ENRICHERS["java-ee"](g, FIX / "javaee")
        self.assertEqual(len(g.doc["edges"]), before, "re-running adds nothing")


class DjangoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = enrich("django")

    def test_models_become_tables_abstract_skipped(self):
        self.assertEqual(edges(self.g, "defines_schema"), {("OrderModel", "shop_orders"), ("AuditModel", "orders_auditmodel")})

    def test_orm_reads_and_writes_tests_ignored(self):
        self.assertEqual(edges(self.g, "reads_from"), {("DjangoOrderRepository", "shop_orders")})
        self.assertEqual(edges(self.g, "writes_to"), {("DjangoOrderRepository", "orders_auditmodel")})

    def test_urls_with_factory_and_include(self):
        routes = edges(self.g, "routes")
        self.assertIn(("/", "compose_order_view"), routes)
        self.assertIn(("/api/health/", "health"), routes)
        self.assertIn(("create_order_view", "src/shop/orders/templates/orders/list.html"), routes)

    def test_typed_injection_and_protocol(self):
        self.assertIn(("create_order_view", "OrderLookup"), edges(self.g, "calls"))
        self.assertIn(("OrderLookup", "OrderRepository"), edges(self.g, "calls"))
        self.assertIn(("DjangoOrderRepository", "OrderRepository"), edges(self.g, "implements"))

    def test_directed_paths_to_data(self):
        self.assertIn("→reads_from `shop_orders`", path(self.g, "endpoint=/"))
        self.assertIn("←implements `DjangoOrderRepository` →reads_from", path(self.g, "orders/interfaces/views.py"))
        self.assertTrue(path(self.g, "endpoint=/api/health/").startswith("**NO PATH**"))

    def test_management_command_and_task(self):
        self.assertIn(("import_orders", "Command"), edges(self.g, "routes"))
        self.assertIn(("task shop.orders.tasks.record_note", "record_note"), edges(self.g, "triggers"))
        self.assertIn(("Command", "task shop.orders.tasks.record_note"), edges(self.g, "publishes"))
        self.assertIn("→publishes `task shop.orders.tasks.record_note` →triggers `record_note`",
                      path(self.g, "command=import_orders"))

    def test_templates_route_to_endpoints(self):
        routes, board = edges(self.g, "routes"), "src/shop/orders/templates/orders/board.html"
        self.assertIn((board, "/api/board/rows/"), routes, "hx-get with {% url 'ns:name' %}")
        self.assertIn((board, "/api/health/"), routes, "hx-post with a literal path")
        self.assertIn((board, "src/shop/orders/templates/orders/list.html"), edges(self.g, "contains"))

    def test_polled_partial_reaches_data(self):
        self.assertIn("→routes `/api/board/rows/`", path(self.g, "endpoint=/api/board/"))
        self.assertIn("→reads_from `shop_orders`", path(self.g, "endpoint=/api/board/"))


class AppLabelTest(unittest.TestCase):
    def labels(self, files):
        with tempfile.TemporaryDirectory() as d:
            for name, text in files.items():
                p = pathlib.Path(d) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            mods = enrich_graph.py_index(pathlib.Path(d))
            return enrich_graph.app_labels(mods, enrich_graph.defined(mods))

    def test_label_from_config_class_module_entry_or_last_component(self):
        labels = self.labels({
            "proj/settings.py": "INSTALLED_APPS = ['a.billing.apps.BillingConfig', 'a.ship', 'a.misc']\n",
            "a/billing/apps.py": "class BillingConfig:\n    name = 'a.billing'\n    label = 'invoices'\n",
            "a/ship/apps.py": "class ShipConfig:\n    name = 'a.ship'\n    label = 'shipping'\n",
        })
        self.assertEqual(dict(labels), {"a.billing": "invoices", "a.ship": "shipping", "a.misc": "misc"})
        self.assertEqual(enrich_graph.app_label_of("a.billing.infrastructure.models", labels), "invoices")
        self.assertEqual(enrich_graph.app_label_of("a.misc.models", labels), "misc")
        self.assertEqual(enrich_graph.app_label_of("other.store.models", labels), "store", "no settings: own package")

    def test_meta_app_label_and_db_table_win(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "a/x/models.py"
            f.parent.mkdir(parents=True)
            f.write_text("from django.db import models\n\n\nclass Thing(models.Model):\n    class Meta:\n"
                         "        app_label = 'legacy'\n\n\nclass Pinned(models.Model):\n    class Meta:\n"
                         "        db_table = 'PINNED'\n")
            g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
            enrich_graph.enrich_django(g, pathlib.Path(d))
            self.assertEqual(edges(g, "defines_schema"), {("Thing", "legacy_thing"), ("Pinned", "PINNED")})


class GraphifyMergeTest(unittest.TestCase):
    def doc(self, links, version=1):
        nodes = [{"id": "f", "label": "a.py", "file_type": "code", "source_file": "a.py"},
                 {"id": "A", "label": "Repo", "_callable_class": True, "file_type": "code", "source_file": "a.py"},
                 {"id": "A.m", "label": ".find()", "file_type": "code", "source_file": "a.py", "source_location": "L4"},
                 {"id": "B", "label": "SqlRepo", "_callable_class": True, "file_type": "code", "source_file": "b.py"},
                 {"id": "v", "label": "view()", "file_type": "code", "source_file": "c.py"},
                 {"id": "P", "label": "Protocol", "file_type": "concept", "external": True}]
        return {"graph": {"schema_version": version}, "nodes": nodes,
                "links": [{"source": "f", "target": "A", "relation": "contains"},
                          {"source": "A", "target": "A.m", "relation": "method"}] + links}

    def test_methods_count_as_their_type_and_only_flow_relations_merge(self):
        g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
        enrich_graph.merge_graphify(g, self.doc([
            {"source": "v", "target": "A.m", "relation": "calls", "confidence": "INFERRED", "source_file": "c.py",
             "source_location": "L9"},
            {"source": "v", "target": "B", "relation": "uses", "confidence": "EXTRACTED"},
            {"source": "B", "target": "A", "relation": "inherits", "confidence": "EXTRACTED"},
            {"source": "A", "target": "P", "relation": "inherits", "confidence": "EXTRACTED"},
            {"source": "B", "target": "v", "relation": "references", "confidence": "EXTRACTED"}]))
        self.assertEqual(edges(g, "calls"), {("view", "Repo"), ("view", "SqlRepo")})
        self.assertEqual(edges(g, "implements"), {("SqlRepo", "Repo")}, "a Protocol-based base is an interface")
        self.assertEqual(edges(g, "inherits"), set(), "external bases and references are not merged")
        desc = {e["description"] for e in g.doc["edges"]}
        self.assertIn("afs-enriched:graphify — calls INFERRED c.py:L9", desc)
        self.assertIn("afs-enriched:graphify — uses EXTRACTED", desc)

    def test_existing_nodes_are_reused(self):
        g = enrich_graph.Graph({"project": {}, "nodes": [
            {"id": "llm-repo", "type": "class", "name": "Repo", "filePath": "a.py"}], "edges": []})
        enrich_graph.merge_graphify(g, self.doc([{"source": "v", "target": "A", "relation": "calls"}]))
        self.assertEqual([e["target"] for e in g.doc["edges"]], ["llm-repo"])

    def test_unknown_schema_version_is_refused(self):
        g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
        with self.assertRaisesRegex(enrich_graph.GraphifyError, "schema_version 2"):
            enrich_graph.merge_graphify(g, self.doc([], version=2))


class GateTest(unittest.TestCase):
    def test_calling_an_entity_is_not_data_access(self):
        nodes = [{"id": i, "type": t, "name": i} for i, t in
                 (("ep", "endpoint"), ("svc", "class"), ("Cargo", "class"), ("cargo", "table"), ("repo", "class"))]
        e = lambda s, t, k: {"source": s, "target": t, "type": k}
        edges = [e("ep", "svc", "routes"), e("svc", "Cargo", "calls"), e("Cargo", "cargo", "defines_schema")]
        by_id = {n["id"]: n for n in nodes}
        self.assertTrue(check_graph.data_path("endpoint=ep", nodes, edges, by_id).startswith("**NO PATH**"))
        edges += [e("svc", "repo", "calls"), e("repo", "cargo", "reads_from")]
        self.assertIn("→reads_from `cargo`", check_graph.data_path("endpoint=ep", nodes, edges, by_id))


class PageLinkTest(unittest.TestCase):
    def test_suffix_match_and_verbs(self):
        eps = [("GET", "/cargo", "a"), ("POST", "/cargo", "b"), (None, "/", "c"), ("WS", "/tracking", "d"),
               (None, "/board/<int:pk>/", "e")]
        self.assertEqual(enrich_graph.match_endpoints("/app/rest/cargo", "GET", eps), ["a"])
        self.assertEqual(enrich_graph.match_endpoints("/app/rest/cargo?x=1", "POST", eps), ["b"])
        self.assertEqual(enrich_graph.match_endpoints("/x/tracking", "WS", eps), ["d"])
        self.assertEqual(enrich_graph.match_endpoints("/x/tracking", "GET", eps), [], "a socket is not GET")
        self.assertEqual(enrich_graph.match_endpoints("/", "GET", eps), ["c"])
        self.assertEqual(enrich_graph.match_endpoints("/other", "GET", eps), [], "/ matches only exactly")
        self.assertEqual(enrich_graph.match_endpoints("/board/7/", "GET", eps), ["e"])
        self.assertEqual(enrich_graph.match_endpoints("/rest/acargo", "GET", eps), [], "segment boundary")


class CliTest(unittest.TestCase):
    def test_cli_writes_provenance_and_result_line(self):
        with tempfile.TemporaryDirectory() as d:
            kg = pathlib.Path(d) / "kg.json"
            kg.write_text(json.dumps({"project": {"name": "x"}, "nodes": [], "edges": []}))
            r = subprocess.run([sys.executable, str(ROOT / "tools/enrich_graph.py"), str(kg), "--root",
                                str(FIX / "django"), "--graphify", str(FIX / "django.graphify.json"),
                                "--enricher", "django"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("AFS-RESULT gate=graph-enrich enrichers=graphify,django", r.stdout)
            doc = json.loads(kg.read_text())
            self.assertEqual(doc["project"]["afsEnrichment"]["enrichers"], ["graphify", "django"])
            bad = pathlib.Path(d) / "gf.json"
            bad.write_text(json.dumps({"graph": {"schema_version": 99}, "nodes": [], "links": []}))
            r = subprocess.run([sys.executable, str(ROOT / "tools/enrich_graph.py"), str(kg), "--root",
                                str(FIX / "django"), "--graphify", str(bad)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn("schema_version 99", r.stderr)

    def test_check_graph_gate_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            kg = pathlib.Path(d) / "kg.json"
            g = enrich("django")
            kg.write_text(json.dumps(g.doc))
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "tools/check_graph.py"), str(kg), "--gate", *a],
                                            capture_output=True, text=True)
            ok = run("--require-node", "table", "--require-edge", "reads_from", "--data-path", "endpoint=/")
            self.assertEqual(ok.returncode, 0, ok.stdout)
            self.assertIn("AFS-RESULT gate=graph verdict=pass", ok.stdout)
            bad = run("--require-node", "screen", "--data-path", "endpoint=/api/health/")
            self.assertEqual(bad.returncode, 1)
            self.assertIn("required node type `screen` is absent", bad.stdout)


class GraphGateTest(unittest.TestCase):
    def repo(self, d, anchors, require, graph=True):
        r = pathlib.Path(d)
        (r / ".migration/slices").mkdir(parents=True)
        (r / ".migration/profile.yaml").write_text(json.dumps({"graph": {"require": {"target": require}}}))
        (r / ".migration/source.lock").write_text("repo: o/s\nsha: " + "0" * 40 + "\n")
        (r / ".migration/slices/orders.yaml").write_text(json.dumps({"data_paths": {"target": anchors}}))
        if graph:
            (r / ".migration/graphs/target/full").mkdir(parents=True)
            (r / ".migration/graphs/target/full/knowledge-graph.json").write_text(json.dumps(enrich("django").doc))
        return r

    def gate(self, cwd, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/graph_gate.py"), *args], cwd=cwd,
                              capture_output=True, text=True)

    def test_pass_fail_and_missing_graph(self):
        with tempfile.TemporaryDirectory() as d:
            self.repo(d, ["endpoint=/"], {"nodes": ["table", "endpoint"], "edges": ["reads_from", "routes"]})
            r = self.gate(d, "--side", "target")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("verdict=pass", r.stdout)
            self.assertIn("reaching_data=4", r.stdout)
        with tempfile.TemporaryDirectory() as d:
            self.repo(d, ["endpoint=/api/health/"], {"nodes": ["screen"]})
            r = self.gate(d, "--side", "target")
            self.assertEqual(r.returncode, 1)
            self.assertIn("required node type `screen` is absent", r.stdout)
            self.assertIn("slice orders: data path from `endpoint=/api/health/`", r.stdout)
        with tempfile.TemporaryDirectory() as d:
            self.repo(d, [], {}, graph=False)
            self.assertEqual(self.gate(d, "--side", "target").returncode, 0)
            self.assertEqual(self.gate(d, "--side", "target", "--require-graph").returncode, 1)

    def test_target_entry_points_must_be_owned_by_a_slice(self):
        import graph_gate
        with tempfile.TemporaryDirectory() as d:
            r = self.repo(d, ["endpoint=/api/board/"], {})
            spec = r / ".migration/slices/orders.yaml"
            cwd = os.getcwd()
            try:
                os.chdir(r)
                loose, stale = graph_gate.unowned(*graph_gate.load_graph("target"))
                names = {n["name"] for n in loose}
                self.assertNotIn("/api/board/", names, "the anchor itself")
                self.assertNotIn("/api/board/rows/", names, "reached from the anchor (htmx)")
                self.assertNotIn("/api/health/", names, "reached from the anchor's page (hx-post)")
                self.assertEqual(names, {"/", "import_orders"})
                spec.write_text(json.dumps({"data_paths": {"target": ["endpoint=/api/board/"]},
                                            "entry_points": {"target": ["endpoint=/", "command=import_orders",
                                                                        "endpoint=/gone/"]}}))
                loose, stale = graph_gate.unowned(*graph_gate.load_graph("target"))
                self.assertEqual(loose, [])
                self.assertEqual(stale, ["slice orders: entry_points.target `endpoint=/gone/` matches no node"])
            finally:
                os.chdir(cwd)
            r2 = self.gate(d, "--side", "target")
            self.assertEqual(r2.returncode, 0, "outside acceptance, ownership problems are warnings")
            self.assertIn("matches no node", r2.stderr)

    def test_unowned_entry_point_fails_at_acceptance(self):
        import graph_gate
        with tempfile.TemporaryDirectory() as d:
            r = self.repo(d, ["endpoint=/"], {})
            cwd, accepting = os.getcwd(), graph_gate.check_graph_fresh.accepting
            try:
                os.chdir(r)
                graph_gate.check_graph_fresh.accepting = lambda base: True
                with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                    code = graph_gate.main(["--side", "target", "--acceptance-since", "base"])
            finally:
                graph_gate.check_graph_fresh.accepting = accepting
                os.chdir(cwd)
            self.assertEqual(code, 1)
            self.assertIn("endpoint=/api/board/ (src/shop/orders/interfaces/urls.py) is owned by no slice", out.getvalue())


class SliceSchemaTest(unittest.TestCase):
    def test_unknown_keys_and_bad_entry_points_are_errors(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas/slice.schema.json").read_text())
        v = jsonschema.Draft202012Validator(schema)
        good = {"epic": 9, "data_paths": {"source": ["a.xhtml"], "target": ["endpoint=/"]},
                "entry_points": {"target": ["endpoint=/tracking/map/", "command=seed_sample_data"]}}
        self.assertEqual(list(v.iter_errors(good)), [])
        self.assertTrue(list(v.iter_errors({"data_path": {"target": ["endpoint=/"]}})), "misspelt key")
        self.assertTrue(list(v.iter_errors({"data_paths": {"targets": ["endpoint=/"]}})), "misspelt side")
        self.assertTrue(list(v.iter_errors({"entry_points": {"target": ["/tracking/map/"]}})), "needs TYPE=NAME")


class BootstrapGraphTest(unittest.TestCase):
    def test_profile_must_state_the_stack_packs_graph_settings(self):
        import bootstrap
        pack = json.loads((ROOT / "stacks/java-to-django.json").read_text())
        good = {"graph": {"enrich": pack["graph"]["enrich"], "require": pack["graph"]["require"]}}
        bootstrap.check_profile_graph(good, [pack])
        with self.assertRaisesRegex(bootstrap.BootstrapError, "graph.enrich.source must include"):
            bootstrap.check_profile_graph({"graph": {}}, [pack])
        weaker = json.loads(json.dumps(good))
        weaker["graph"]["require"]["target"]["edges"].remove("writes_to")
        with self.assertRaisesRegex(bootstrap.BootstrapError, r"require.target.edges must include \['writes_to'\]"):
            bootstrap.check_profile_graph(weaker, [pack])


if __name__ == "__main__":
    unittest.main()
