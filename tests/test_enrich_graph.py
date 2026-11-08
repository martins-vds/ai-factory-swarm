"""tools/enrich_graph.py and the graph gate (ADR-0020): deterministic links Understand Anything can't infer."""
import contextlib
import io
import json
import os
import pathlib
import shutil
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


class StaticPagesTest(unittest.TestCase):
    """A Java EE app whose UI is static HTML (the synthetic target's About page, served by a JAX-RS resource)
    has `page` nodes: the stack pack requires them, and the graph gate failed without (synthetic SY-01)."""
    def test_static_html_is_a_page_routed_from_the_resource_that_serves_it(self):
        g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
        enrich_graph.ENRICHERS["java-ee"](g, ROOT / "synthetic/legacy")
        self.assertIn("src/main/resources/static/about.html",
                      {n["name"] for n in g.doc["nodes"] if n["type"] == "page"})
        self.assertIn(("GET /about", "src/main/resources/static/about.html"), edges(g, "routes"))

    def test_jsp_and_test_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "src/main/java/app").mkdir(parents=True)
            (root / "src/main/java/app/App.java").write_text("package app;\npublic class App {}\n")
            (root / "src/main/webapp").mkdir(parents=True)
            (root / "src/main/webapp/list.jsp").write_text("<%@ page %><html></html>")
            (root / "src/test/resources").mkdir(parents=True)
            (root / "src/test/resources/fixture.html").write_text("<html></html>")
            g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
            enrich_graph.ENRICHERS["java-ee"](g, root)
            pages = {n["name"]: n for n in g.doc["nodes"] if n["type"] == "page"}
        self.assertIn("src/main/webapp/list.jsp", pages)
        self.assertNotIn("src/test/resources/fixture.html", pages, "test fixtures aren't the app's pages")


class JavaEETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = enrich("java-ee")

    def test_entities_become_tables(self):
        self.assertEqual(edges(self.g, "defines_schema"), {("Order", "orders"), ("Customer", "Customer")})

    def test_repository_reads_and_writes(self):
        self.assertEqual(edges(self.g, "reads_from"), {("JpaOrderRepository.find", "orders"),
                                                       ("JpaOrderRepository.find", "Customer")})
        self.assertEqual(edges(self.g, "writes_to"), {("JpaOrderRepository.store", "orders"),
                                                      ("JpaOrderRepository.store", "Customer")},
                         "per method, incl. a for-each variable")

    def test_named_query_annotation_is_not_a_cdi_bean(self):
        self.assertNotIn("Unused", {t for _, t in edges(self.g, "routes")})

    def test_dotted_bean_names_and_facelets_composition(self):
        routes = edges(self.g, "routes")
        self.assertIn(("src/main/webapp/public/orders.xhtml", "OrderView"), routes)
        self.assertIn(("src/main/webapp/public/dashboard.xhtml", "src/main/webapp/public/orders.xhtml"),
                      edges(self.g, "contains"))

    def test_jax_rs_endpoint_and_jms_hop(self):
        self.assertIn(("POST /orders/report", "OrderResource.report"), edges(self.g, "routes"))
        self.assertIn(("Events.orderReported", "java:app/jms/OrderQueue"), edges(self.g, "publishes"))
        self.assertIn(("java:app/jms/OrderQueue", "OrderConsumer.onMessage"), edges(self.g, "triggers"))

    def test_directed_paths_to_data(self):
        self.assertIn("←implements `JpaOrderRepository.find` →reads_from", path(self.g, "public/dashboard.xhtml"))
        jms = path(self.g, "endpoint=POST /orders/report")
        self.assertIn("→publishes `java:app/jms/OrderQueue`", jms)
        self.assertIn("→triggers `OrderConsumer.onMessage`", jms)
        self.assertTrue(path(self.g, "templates/layout.xhtml").startswith("**NO PATH**"))

    def test_each_method_publishes_only_to_the_queue_it_uses(self):
        """ADR-0028: one class, two queues, two methods; a flow follows the method it enters (pilot #115)."""
        self.assertEqual(edges(self.g, "publishes") & {("Events", "java:app/jms/OrderQueue"),
                                                       ("Events", "java:app/jms/AuditQueue")}, set())
        report = check_graph.reachable(check_graph.anchor_nodes("endpoint=POST /orders/report", self.g.doc["nodes"]),
                                       self.g.doc["edges"])
        names = {n["name"] for n in self.g.doc["nodes"] if n["id"] in report}
        self.assertIn("java:app/jms/OrderQueue", names)
        self.assertNotIn("java:app/jms/AuditQueue", names, "the report never audits")
        self.assertTrue(path(self.g, "endpoint=GET /orders/ping").startswith("**NO PATH**"),
                        "ping only audits, and the audit consumer reads nothing")

    def test_websocket_endpoint_and_cdi_events(self):
        self.assertIn(("WS /live", "LivePush"), edges(self.g, "routes"))
        self.assertIn(("OrderChecker.check", "cdi-event @OrderChecked Order"), edges(self.g, "publishes"))
        triggers = edges(self.g, "triggers")
        self.assertIn(("cdi-event @OrderChecked Order", "LivePush.onOrderChecked"), triggers)
        self.assertNotIn(("cdi-event @OrderChecked Order", "AuditTrail.onCustomer"), triggers, "different event type")

    def test_schedule_and_batch_job(self):
        self.assertIn(("timer Nightly.run (minute=*/2, hour=*)", "Nightly.run"), edges(self.g, "triggers"))
        calls = edges(self.g, "calls")
        self.assertIn(("Nightly.run", "batch-job OrderImportJob"), calls)
        self.assertIn(("batch-job OrderImportJob", "OrderLineReader"), calls)
        self.assertIn(("batch-job OrderImportJob", "OrderLineWriter"), calls)

    def test_page_scripts_route_to_endpoints(self):
        routes = edges(self.g, "routes")
        self.assertIn(("src/main/webapp/public/live.xhtml", "POST /orders/report"), routes)
        self.assertIn(("src/main/webapp/public/live.xhtml", "WS /live"), routes)

    def test_directed_paths_through_async_hops(self):
        timer = path(self.g, "resource=timer Nightly.run (minute=*/2, hour=*)")
        self.assertIn("→calls `batch-job OrderImportJob`", timer)
        self.assertIn("→triggers `OrderConsumer.onMessage`", timer)
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


class JavaEEIframeTest(unittest.TestCase):
    wrapper = "src/main/webapp/admin/tracking/map.xhtml"
    frame = "src/main/webapp/admin/tracking/mapFrame.xhtml"

    def graph(self, markup):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(FIX / "javaee", root, dirs_exist_ok=True)
            page = root / self.wrapper
            page.parent.mkdir(parents=True)
            page.write_text(markup)
            (root / self.frame).write_text(
                '<html><script>fetch("/orders/report", {method: "POST"});</script></html>')
            # Same suffix in another module must never stand in for a missing local target.
            decoy = root / "other/src/main/webapp/missing/mapFrame.xhtml"
            decoy.parent.mkdir(parents=True)
            decoy.write_text('<html><h:outputText value="#{public.orders.count}"/></html>')
            g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
            enrich_graph.merge_graphify(g, json.loads((FIX / "javaee.graphify.json").read_text()))
            enrich_graph.enrich_java_ee(g, root)
            before = json.dumps(g.doc, sort_keys=True)
            enrich_graph.enrich_java_ee(g, root)
            self.assertEqual(json.dumps(g.doc, sort_keys=True), before, "enrichment stays idempotent")
            return g

    def test_context_path_iframe_reaches_data_through_child(self):
        g = self.graph('<html><iframe width="100%" '
                       'src="#{request.contextPath}/admin/tracking/mapFrame.xhtml"/></html>')
        self.assertIn((self.wrapper, self.frame), edges(g, "contains"))
        flow = path(g, self.wrapper)
        self.assertIn(f"→contains `{self.frame}`", flow)
        self.assertIn("→routes `POST /orders/report`", flow)
        self.assertRegex(flow, r"→reads_from `(orders|Customer)`")
        pages = {n["filePath"]: n["id"] for n in g.doc["nodes"] if n["type"] == "page"}
        edge = next(e for e in g.doc["edges"]
                    if e["source"] == pages[self.wrapper] and e["target"] == pages[self.frame])
        self.assertIn("afs-enriched:jsf-iframe", edge["description"])
        self.assertIn("#{request.contextPath}/admin/tracking/mapFrame.xhtml", edge["description"])

    def test_local_path_semantics(self):
        for src in ("mapFrame.xhtml", "./mapFrame.xhtml", "../tracking/mapFrame.xhtml",
                    "/admin/tracking/mapFrame.xhtml", "mapFrame.xhtml?mode=live&amp;zoom=2#map"):
            with self.subTest(src=src):
                g = self.graph(f"<html><iframe\n src='{src}'></iframe></html>")
                self.assertIn((self.wrapper, self.frame), edges(g, "contains"))
                self.assertRegex(path(g, self.wrapper), r"→reads_from `(orders|Customer)`")

    def test_unresolved_references_do_not_invent_data_paths(self):
        for src in ("#{mapView.frame}", "${mapView.frame}",
                    "#{request.contextPath}/admin/#{mapView.frame}.xhtml",
                    "#{request.contextPath.concat('/admin/tracking/mapFrame.xhtml')}",
                    "#{request.contextPath}//admin/tracking/mapFrame.xhtml",
                    "https://example.test/admin/tracking/mapFrame.xhtml",
                    "//example.test/admin/tracking/mapFrame.xhtml",
                    "file:///admin/tracking/mapFrame.xhtml", "javascript:mapFrame.xhtml",
                    "\\\\example.test\\mapFrame.xhtml", "%2e%2e/tracking/mapFrame.xhtml",
                    "/missing/mapFrame.xhtml", "missing/mapFrame.xhtml", "absent.xhtml",
                    "mapFrame.xhtml/",
                    "../../../../other/src/main/webapp/missing/mapFrame.xhtml",
                    "", "#map", "?mode=live"):
            with self.subTest(src=src):
                g = self.graph(f'<html><iframe src="{src}"/></html>')
                self.assertFalse(any(s == self.wrapper for s, _ in edges(g, "contains")))
                self.assertTrue(path(g, self.wrapper).startswith("**NO PATH**"))
                self.assertRegex(path(g, self.frame), r"→reads_from `(orders|Customer)`",
                                 "child control reaches data")

    def test_inactive_or_non_src_attributes_do_not_link(self):
        for markup in ('<!-- <iframe src="mapFrame.xhtml"/> -->',
                       '<iframe data-src="mapFrame.xhtml"/>',
                       '<iframe src="mapFrame.xhtml" srcdoc="inline content"/>',
                       '<iframe src="absent.xhtml" src="mapFrame.xhtml"/>',
                       '<base href="https://example.test/"/><iframe src="mapFrame.xhtml"/>'):
            with self.subTest(markup=markup):
                g = self.graph(markup)
                self.assertTrue(path(g, self.wrapper).startswith("**NO PATH**"))


class DjangoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = enrich("django")

    def test_models_become_tables_abstract_skipped(self):
        self.assertEqual(edges(self.g, "defines_schema"), {("OrderModel", "shop_orders"), ("AuditModel", "orders_auditmodel")})

    def test_orm_reads_and_writes_tests_ignored(self):
        self.assertEqual(edges(self.g, "reads_from"), {("DjangoOrderRepository.find", "shop_orders")})
        self.assertEqual(edges(self.g, "writes_to"), {("DjangoOrderRepository.record", "orders_auditmodel")})

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
        self.assertIn("←implements `DjangoOrderRepository.find` →reads_from", path(self.g, "orders/interfaces/views.py"))
        self.assertTrue(path(self.g, "endpoint=/api/health/").startswith("**NO PATH**"))

    def test_management_command_and_task(self):
        self.assertIn(("import_orders", "Command"), edges(self.g, "routes"))
        self.assertIn(("task shop.orders.tasks.record_note", "record_note"), edges(self.g, "triggers"))
        self.assertIn(("Command.handle", "task shop.orders.tasks.record_note"), edges(self.g, "publishes"))
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


class DjangoHttpMethodsTest(unittest.TestCase):
    def graph(self, views=None, composition=None, pages=None):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            shutil.copytree(FIX / "django", root, dirs_exist_ok=True)
            for name, text in {"src/shop/orders/interfaces/views.py": views,
                               "src/shop/orders/composition.py": composition,
                               **(pages or {})}.items():
                if text is not None:
                    f = root / name
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(text)
            g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
            enrich_graph.merge_graphify(g, json.loads((FIX / "django.graphify.json").read_text()))
            enrich_graph.enrich_django(g, root)
            before = json.dumps(g.doc, sort_keys=True)
            enrich_graph.enrich_django(g, root)
            self.assertEqual(json.dumps(g.doc, sort_keys=True), before, "enrichment stays idempotent")
            return g

    def factory(self, decorators, imports="", extra=""):
        return (
            "from django.views.decorators.http import require_POST, require_GET, require_safe, require_http_methods\n"
            f"{imports}\n"
            "def create_order_view(lookup):\n"
            f"{extra}"
            + "".join(f"    @{d}\n" for d in decorators)
            + "    def view(request):\n"
              "        return lookup.find(request.GET.get('id'))\n"
              "    return view\n\n"
              "def health(request):\n"
              "    return None\n"
        )

    def test_returned_post_view_through_composition_preserves_exact_anchor_and_data_flow(self):
        g = self.graph(self.factory(["require_POST"]))
        self.assertIn(("POST /", "compose_order_view"), edges(g, "routes"))
        self.assertIn("→reads_from `shop_orders`", path(g, "endpoint=POST /"))
        self.assertTrue(path(g, "endpoint=GET /").startswith("no matching node"))
        self.assertTrue(path(g, "endpoint=/").startswith("no matching node"), "no unrestricted duplicate")
        self.assertNotIn(("POST /", "health"), edges(g, "routes"))

    def test_graph_gate_passes_post_anchor_but_rejects_wrong_method(self):
        g = self.graph(self.factory(["require_POST"]))
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / ".migration/graphs/target/full").mkdir(parents=True)
            (root / ".migration/slices").mkdir()
            (root / ".migration/graphs/target/full/knowledge-graph.json").write_text(json.dumps(g.doc))
            (root / ".migration/profile.yaml").write_text(json.dumps({
                "graph": {"require": {"target": {"nodes": ["endpoint", "table"], "edges": ["reads_from"]}}}
            }))
            spec = root / ".migration/slices/orders.yaml"
            for method, code in (("POST", 0), ("GET", 1)):
                spec.write_text(json.dumps({"data_paths": {"target": [f"endpoint={method} /"]}}))
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools/graph_gate.py"), "--side", "target", "--require-graph"],
                    cwd=root, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn("verdict=pass" if code == 0 else "no matching node", result.stdout)

    def test_aliases_safe_and_literal_method_lists(self):
        cases = [
            (["only_post"], "from django.views.decorators.http import require_POST as only_post", {"POST"}),
            (["http.require_safe"], "from django.views.decorators import http", {"GET", "HEAD"}),
            (["require_GET"], "", {"GET"}),
            (["require_http_methods(['POST', 'PATCH'])"], "", {"POST", "PATCH"}),
            (["require_http_methods(('GET', 'POST'))", "require_GET"], "", {"GET"}),
            (["require_GET", "require_POST"], "", set()),
        ]
        for decorators, imports, methods in cases:
            with self.subTest(decorators=decorators):
                g = self.graph(self.factory(decorators, imports))
                names = {n["name"] for n in g.doc["nodes"] if n.get("type") == "endpoint"
                         and n.get("filePath") == "src/shop/urls.py"}
                self.assertEqual(names, {f"{method} /" for method in methods})

    def test_data_path_lists_every_table_reached_not_only_the_shortest(self):
        # pilot DM-AUDIT: the shortest path ended at one table, and the Auditor read the other five as missing
        g = enrich("django")
        with tempfile.TemporaryDirectory() as d:
            mapping = pathlib.Path(d) / "mapping.yaml"
            mapping.write_text("tables:\n  - target: shop_orders\n  - target: orders_auditmodel\n")
            profile = pathlib.Path(d) / "profile.yaml"
            profile.write_text(json.dumps({"data": {"load": [f"python manage.py import_orders --mapping {mapping}"]}}))
            enrich_graph.enrich_data_mapping(g, profile)
        line = path(g, "command=import_orders")
        self.assertIn("reaches 2 data node(s): orders_auditmodel, shop_orders", line)

    def test_module_level_views_built_by_a_factory_are_routed(self):
        # pilot admin live map: `live_map, live_map_markers = compose_admin_map_views()`, then path('', live_map)
        for urls in ("from shop.orders.composition import compose_order_view\n"
                     "orders_view = compose_order_view()\n",
                     "from shop.orders.composition import compose_order_view\n"
                     "orders_view, markers_view = compose_order_view()\n",
                     "from shop.orders.composition import compose_order_view\n"
                     "orders_view, unused = compose_order_view(), None\n"):
            with self.subTest(urls=urls.splitlines()[1]):
                g = self.graph(pages={"src/shop/urls.py": urls + "from django.urls import include, path\n"
                                      "urlpatterns = [path('', orders_view, name='orders'),\n"
                                      "    path('api/', include('shop.orders.interfaces.urls'))]\n"})
                if "unused" in urls:
                    self.assertNotIn(("/", "compose_order_view"), edges(g, "routes"),
                                     "a tuple of two calls isn't one factory's result")
                else:
                    self.assertIn(("/", "compose_order_view"), edges(g, "routes"))
                    self.assertFalse(path(g, "endpoint=/").startswith(("**NO PATH**", "no matching")))

    def test_data_mapping_links_the_load_and_export_commands_to_mapped_tables(self):
        g = enrich("django")
        with tempfile.TemporaryDirectory() as d:
            mapping = pathlib.Path(d) / "mapping.yaml"
            mapping.write_text("tables:\n  - target: shop_orders\n  - target: nowhere\n")
            profile = pathlib.Path(d) / "profile.yaml"
            profile.write_text(json.dumps({"data": {
                "load": [f"python manage.py import_orders --snapshot {{snapshot}} --mapping {mapping}"],
                "export": [f"python manage.py import_orders --mapping {mapping} --out {{out}}"]}}))
            enrich_graph.enrich_data_mapping(g, profile)
        self.assertIn(("import_orders", "shop_orders"), edges(g, "writes_to"))
        self.assertIn(("import_orders", "shop_orders"), edges(g, "reads_from"))
        self.assertTrue(any(e["description"].startswith("afs-enriched:data-mapping") for e in g.doc["edges"]))

    def test_direct_decorated_view_is_not_treated_as_a_factory(self):
        g = self.graph(
            "from django.views.decorators.http import require_POST\n"
            "@require_POST\n"
            "def health(request):\n"
            "    return render(request, 'orders/health.html')\n"
        )
        self.assertIn(("POST /api/health/", "health"), edges(g, "routes"))
        self.assertTrue(path(g, "endpoint=GET /api/health/").startswith("no matching node"))

    def test_unrelated_nested_decorators_do_not_restrict_returned_view(self):
        g = self.graph(self.factory([], extra="    @require_POST\n    def unused(request):\n        pass\n"))
        self.assertIn(("/", "compose_order_view"), edges(g, "routes"))

    def test_unknown_dynamic_or_lookalike_decorators_do_not_invent_methods(self):
        cases = [
            (["require_http_methods(METHODS)"], ""),
            (["require_POST"], "from custom import require_POST"),
            (["require_http_methods(['post'])"], ""),
        ]
        for decorators, imports in cases:
            with self.subTest(decorators=decorators, imports=imports):
                g = self.graph(self.factory(decorators, imports))
                self.assertIn(("/", "compose_order_view"), edges(g, "routes"))
                self.assertTrue(path(g, "endpoint=POST /").startswith("no matching node"))

    def test_recursive_and_conflicting_factory_returns_stay_unknown(self):
        for composition in (
            "def compose_order_view():\n    return compose_order_view()\n",
            "def compose_order_view():\n    return external_factory()\n",
            "from shop.orders.interfaces.views import create_order_view, health\n"
            "def compose_order_view():\n"
            "    if condition:\n        return create_order_view(None)\n"
            "    return health\n",
        ):
            with self.subTest(composition=composition):
                g = self.graph(self.factory(["require_POST"]), composition)
                self.assertIn(("/", "compose_order_view"), edges(g, "routes"))
                self.assertTrue(path(g, "endpoint=POST /").startswith("no matching node"))

    def test_templates_match_named_and_literal_routes_by_method(self):
        pages = {}
        for method in ("get", "post", "patch"):
            for kind, url in (("named", "{% url 'orders' %}"), ("literal", "/")):
                pages[f"src/shop/orders/templates/orders/{kind}-{method}.html"] = f'<div hx-{method}="{url}"></div>'
        g = self.graph(self.factory(["require_http_methods(['POST', 'PATCH'])"]), pages=pages)
        routes = edges(g, "routes")
        for method in ("GET", "POST", "PATCH"):
            for kind in ("named", "literal"):
                page = f"src/shop/orders/templates/orders/{kind}-{method.lower()}.html"
                for endpoint_method in ("POST", "PATCH"):
                    self.assertEqual((page, f"{endpoint_method} /") in routes, method == endpoint_method)


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

    def test_methods_are_nodes_their_type_contains_and_only_flow_relations_merge(self):
        g = enrich_graph.Graph({"project": {}, "nodes": [], "edges": []})
        enrich_graph.merge_graphify(g, self.doc([
            {"source": "v", "target": "A.m", "relation": "calls", "confidence": "INFERRED", "source_file": "c.py",
             "source_location": "L9"},
            {"source": "v", "target": "B", "relation": "uses", "confidence": "EXTRACTED"},
            {"source": "B", "target": "A", "relation": "inherits", "confidence": "EXTRACTED"},
            {"source": "A", "target": "P", "relation": "inherits", "confidence": "EXTRACTED"},
            {"source": "B", "target": "v", "relation": "references", "confidence": "EXTRACTED"}]))
        self.assertEqual(edges(g, "calls"), {("view", "Repo.find"), ("view", "SqlRepo")}, "a call lands on the method")
        self.assertIn(("Repo", "Repo.find"), edges(g, "contains"))
        self.assertEqual(edges(g, "implements"), {("SqlRepo", "Repo")}, "a Protocol-based base is an interface")
        self.assertEqual(edges(g, "inherits"), set(), "external bases and references are not merged")
        desc = {e["description"] for e in g.doc["edges"]}
        self.assertIn("afs-enriched:graphify — calls INFERRED c.py:L9", desc)
        self.assertIn("afs-enriched:graphify — uses EXTRACTED", desc)

    def test_existing_nodes_are_reused(self):
        g = enrich_graph.Graph({"project": {}, "nodes": [
            {"id": "llm-repo", "type": "class", "name": "Repo", "filePath": "a.py"}], "edges": []})
        enrich_graph.merge_graphify(g, self.doc([{"source": "v", "target": "A", "relation": "calls"}]))
        self.assertEqual([(e["source"], e["target"]) for e in g.doc["edges"] if e["type"] == "calls"],
                         [("function:c.py:view", "llm-repo")])

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

    def test_unbuilt_slice_data_paths_warn_until_its_code_is_merged(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.repo(d, ["endpoint=/api/health/"], {})
            (r / ".migration/plan").mkdir()
            (r / ".migration/plan/orders.md").write_text("# orders\n")
            (r / ".migration/plan/orders.tickets.yaml").write_text(json.dumps({"slice": "orders", "tickets": [
                {"id": "OR-01", "role": "afs-migrator", "files": ["src/a.py"], "blocked_by": []}]}))
            g = self.gate(d, "--side", "target")
            self.assertEqual(g.returncode, 0, g.stdout + g.stderr)
            self.assertIn("not enforced: OR-01 still open", g.stderr)
            self.assertIn("not built yet: OR-01 open", g.stdout)
            (r / ".migration/returns").mkdir()
            (r / ".migration/returns/OR-01.afs-migrator.yaml").write_text("role: afs-migrator\n")
            g = self.gate(d, "--side", "target")
            self.assertEqual(g.returncode, 1, "built: the missing path fails")
            self.assertIn("slice orders: data path from `endpoint=/api/health/`", g.stdout)

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

    def test_unowned_entry_point_fails_when_ownership_is_enforced(self):
        import graph_gate
        with tempfile.TemporaryDirectory() as d:
            r = self.repo(d, ["endpoint=/"], {})
            cwd = os.getcwd()
            try:
                os.chdir(r)
                with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
                    code = graph_gate.main(["--side", "target", "--enforce-ownership"])
            finally:
                os.chdir(cwd)
            self.assertEqual(code, 1)
            self.assertIn("endpoint=/api/board/ (src/shop/orders/interfaces/urls.py) is owned by no slice", out.getvalue())

    def test_target_graph_dir_override(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.repo(d, ["endpoint=/"], {"nodes": ["table"]}, graph=False)
            built = r / "built"
            built.mkdir()
            (built / "knowledge-graph.json").write_text(json.dumps(enrich("django").doc))
            env = {**os.environ, "AFS_GRAPH_TARGET_DIR": str(built)}
            g = subprocess.run([sys.executable, str(ROOT / "tools/graph_gate.py"), "--side", "target", "--require-graph"],
                               cwd=r, capture_output=True, text=True, env=env)
            self.assertEqual(g.returncode, 0, g.stdout + g.stderr)


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
