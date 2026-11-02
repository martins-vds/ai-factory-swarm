"""tools/enrich_graph.py and the graph gate (ADR-0020): deterministic links Understand Anything can't infer."""
import json
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
    g = enrich_graph.Graph(base or {"project": {}, "nodes": [], "edges": []})
    enrich_graph.ENRICHERS[kind](g, FIX / ("javaee" if kind == "java-ee" else "django"))
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
        self.assertEqual(edges(self.g, "writes_to"), {("JpaOrderRepository", "orders")})

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


class CliTest(unittest.TestCase):
    def test_cli_writes_provenance_and_result_line(self):
        with tempfile.TemporaryDirectory() as d:
            kg = pathlib.Path(d) / "kg.json"
            kg.write_text(json.dumps({"project": {"name": "x"}, "nodes": [], "edges": []}))
            r = subprocess.run([sys.executable, str(ROOT / "tools/enrich_graph.py"), str(kg), "--root",
                                str(FIX / "django"), "--enricher", "django"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("AFS-RESULT gate=graph-enrich enrichers=django", r.stdout)
            doc = json.loads(kg.read_text())
            self.assertEqual(doc["project"]["afsEnrichment"]["enrichers"], ["django"])

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
            self.assertIn("reaching_data=1", r.stdout)
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
