#!/usr/bin/env python3
"""Add the nodes and edges Understand Anything cannot infer, deterministically, from the code (ADR-0020).

Understand Anything creates `table` nodes only from SQL/migration files, `endpoint` nodes only from
OpenAPI specs and `routes` edges only from infrastructure routing config, and never emits `reads_from`
or `writes_to`. ORM-based applications therefore have no path from a screen to their data. Each
enricher here reads one stack's code and adds those links; every added node and edge carries the tag /
description `afs-enriched:<rule>`, so they can be told from the LLM's.

Two layers (ADR-0025):
  graphify  language level, any language Graphify parses: its calls / uses / implements / inherits between
            top-level types and functions, merged first (--graphify graph.json). Hand-written enrichers never
            re-implement this.
  stack     framework level: what a framework's conventions mean, which no parser infers. A rule relies on a
            documented convention and is proven on the generic fixtures, never on one project (ADR-0023).

Framework enrichers (the stack pack names which ones a migration uses):
  java-ee   JPA @Entity/@Table → table; EntityManager queries/find → reads_from; persist/merge/remove →
            writes_to; JAX-RS @Path + verbs → endpoint, routes; JSF *.xhtml → page, EL #{bean.x} →
            routes to the @Named bean; CDI/EJB @Inject/@EJB fields → calls; JMS producers →
            publishes → queue → triggers → @MessageDriven; @ServerEndpoint → `WS` endpoint; CDI
            Event<T>.fire → publishes → `cdi-event` → triggers → @Observes; @Schedule → `timer` → triggers;
            JobOperator.start("J") → calls → `batch-job J` → calls → the job XML's ref="" beans
  django    urls.py path()/include() → endpoint, routes to the view; models.Model → table; ORM
            Model.objects.* / .save() / .delete() → reads_from / writes_to; render(template) →
            page; management/commands/<name>.py → `command`
            routes Command; @app.task/@shared_task → `task` triggers it, f.defer()/.delay() → publishes;
            {% include/extends %} → contains
  both      page/template scripts and htmx: fetch(url), new WebSocket(…"/path"), hx-get/post/…="url" or
            "{% url 'ns:name' %}" → routes to the matching endpoint (path suffix at a segment boundary,
            same verb; `/` only exactly)

Usage:
  enrich_graph.py <knowledge-graph.json> --root <analysed folder> --graphify <graph.json> --enricher java-ee
                  [--out <path>]          (default: rewrite the graph in place)
Prints one summary line per enricher and an `AFS-RESULT gate=graph-enrich …` line. Standard library only.
"""
import argparse
import ast
import collections
import json
import pathlib
import re
import sys

TAG = "afs-enriched"



class Graph:
    """The knowledge graph plus the edits an enricher makes, with provenance."""

    def __init__(self, doc):
        self.doc = doc
        self.nodes = {n["id"]: n for n in doc.setdefault("nodes", [])}
        self.edge_keys = {(e["source"], e["target"], e["type"]) for e in doc.setdefault("edges", [])}
        self.added = collections.Counter()

    def node(self, ntype, path, name, rule, summary="", line=None):
        nid = f"{ntype}:{path}:{name}" if name else f"{ntype}:{path}"
        if nid not in self.nodes:
            n = {"id": nid, "type": ntype, "name": name or pathlib.PurePosixPath(path).name, "filePath": path,
                 "summary": summary or f"{ntype} {name} (added by {rule})", "tags": [TAG, rule],
                 "complexity": "simple"}
            if line:
                n["lineRange"] = [line, line]
            self.nodes[nid] = n
            self.doc["nodes"].append(n)
            self.added[f"node:{ntype}"] += 1
        return nid

    def edge(self, source, target, etype, rule, weight=0.8, description=""):
        if source == target or (source, target, etype) in self.edge_keys:
            return
        self.edge_keys.add((source, target, etype))
        self.doc["edges"].append({"source": source, "target": target, "type": etype, "direction": "forward",
                                  "weight": weight,
                                  "description": f"{TAG}:{rule}" + (f" — {description}" if description else "")})
        self.added[f"edge:{etype}"] += 1


def rel(path, root):
    return path.relative_to(root).as_posix()


# ------------------------------------------------------------------------------------- page → endpoint

HX_ATTR = re.compile(r"\bhx-(get|post|put|patch|delete)\s*=\s*(\"[^\"]*\"|'[^']*')", re.I)
FETCH = re.compile(r"\bfetch\s*\(\s*(['\"`])([^'\"`]+)\1\s*(?:,\s*\{([^}]*)\})?")
PATH_LITERAL = re.compile(r"(['\"])(/[^'\"\s]*)\1")


def script_links(text):
    """(verb, url) pairs a page or template calls: fetch(), WebSocket path literals and htmx attributes."""
    out = []
    for q, url, opts in FETCH.findall(text):
        m = re.search(r"method\s*:\s*['\"](\w+)", opts or "")
        out.append(((m.group(1) if m else "GET").upper(), url))
    if re.search(r"\bnew\s+WebSocket\s*\(", text):
        out += [("WS", u) for _, u in PATH_LITERAL.findall(text) if len(u) > 1]
    out += [(verb.upper(), val[1:-1]) for verb, val in HX_ATTR.findall(text)]
    return out


def endpoint_index(g):
    """(verb or None, path, node id) for every endpoint node: `GET /x`, `WS /x` or a bare `/x`."""
    eps = []
    for n in g.nodes.values():
        if n.get("type") == "endpoint":
            verb, _, path = n["name"].rpartition(" ")
            eps.append((verb or None, path, n["id"]))
    return eps


def match_endpoints(url, verb, eps):
    """Endpoints a URL literal reaches: the endpoint path is a suffix of the URL at a segment boundary
    (context and application paths come first in the URL), `{x}`/`<x>` parameters match one segment,
    and the verb agrees (a bare Django route accepts any HTTP verb, never a socket). `/` matches only `/`."""
    url = re.split(r"[?#]", url, maxsplit=1)[0]
    norm = lambda u: u.rstrip("/") or "/"
    url = norm(url)
    out = []
    for ev, path, eid in eps:
        if not (ev == verb if ev else verb != "WS"):
            continue
        p = norm(path)
        if p == "/":
            if url == "/":
                out.append(eid)
            continue
        pat = "/".join("[^/]+" if re.fullmatch(r"<[^>]+>|\{[^}]+\}", seg) else re.escape(seg)
                       for seg in p.split("/"))
        if re.fullmatch(".*" + pat, url):
            out.append(eid)
    return out


def link_page(g, pid, text, eps, rule, resolve_named=None):
    for verb, url in script_links(text):
        named = resolve_named(url) if resolve_named else None
        targets = [named] if named else match_endpoints(url, verb, eps) if url.startswith("/") else []
        for eid in targets:
            g.edge(pid, eid, "routes", rule, description=f"{verb} {url}")


# --------------------------------------------------------------------------------------------- Java EE

JAVA_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
JAVA_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
TYPE_DECL = re.compile(r"\b(?:class|interface|enum)\s+(\w+)(?:\s*<[^>{]*>)?(?:\s+extends\s+([\w.<>, ]+?))?"
                       r"(?:\s+implements\s+([\w.<>, ]+?))?\s*\{")
ANNOT_ARG = r'(?:\(\s*(?:name\s*=\s*|value\s*=\s*)?"([^"]*)"[^)]*\)|\([^)]*\))?'


class JavaType:
    def __init__(self, path, name, package, text, raw):
        self.path, self.name, self.package, self.text, self.raw = path, name, package, text, raw


def java_index(root):
    types, by_simple = {}, collections.defaultdict(list)
    for f in sorted(root.rglob("*.java")):
        raw = f.read_text(encoding="utf-8", errors="ignore")
        text = JAVA_COMMENT.sub(" ", raw)
        pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
        m = TYPE_DECL.search(JAVA_STRING.sub('""', text))
        if not m:
            continue
        t = JavaType(rel(f, root), m.group(1), pkg.group(1) if pkg else "", text, raw)
        t.imports = dict((i.split(".")[-1], i) for i in re.findall(r"^\s*import\s+([\w.]+)\s*;", text, re.M))
        fq = f"{t.package}.{t.name}" if t.package else t.name
        types[fq] = t
        by_simple[t.name].append(fq)
    return types, by_simple


def resolve(t, simple, types, by_simple):
    """Fully qualified name of a simple type name as seen from type t, or None if not a project type."""
    simple = simple.split(".")[-1]
    if simple in t.imports and t.imports[simple] in types:
        return t.imports[simple]
    same = f"{t.package}.{simple}" if t.package else simple
    if same in types:
        return same
    cands = by_simple.get(simple, [])
    return cands[0] if len(cands) == 1 else None


def class_id(g, t, rule):
    return g.node("class", t.path, t.name, rule)


def enrich_java_ee(g, root):
    types, by_simple = java_index(root)
    if not types:
        return
    line = lambda t, pat: t.raw[: t.raw.find(pat)].count("\n") + 1 if pat in t.raw else None
    # JPA entities → tables; named queries → owning entity
    tables, named = {}, {}
    for fq, t in types.items():
        if re.search(r"@Entity\b", t.text):
            tm = re.search(r"@Table\s*\(\s*(?:name\s*=\s*)?\"([^\"]+)\"", t.text)
            table = tm.group(1) if tm else t.name
            tid = g.node("table", t.path, table, "jpa-entity", f"Table {table} mapped by JPA entity {t.name}",
                         line(t, "@Entity"))
            g.edge(class_id(g, t, "jpa-entity"), tid, "defines_schema", "jpa-entity")
            tables[fq] = tid
            for q in re.findall(r"@NamedQuery\s*\(\s*name\s*=\s*\"([^\"]+)\"", t.text):
                named[q] = fq
    entity_by_simple = {types[fq].name: fq for fq in tables}

    def entities_in_jpql(jpql):
        names = re.findall(r"(?i)\b(?:from|join|update|into)\s+([A-Z]\w*)", jpql)
        return {entity_by_simple[n] for n in names if n in entity_by_simple}

    for fq, t in types.items():
        cid = None
        body = t.text
        # Repositories: EntityManager use → reads/writes of entity tables
        if "EntityManager" in body:
            reads, writes = set(), set()
            for q in re.findall(r"createNamedQuery\s*\(\s*\"([^\"]+)\"", body):
                if q in named:
                    reads.add(named[q])
            for q in re.findall(r"create(?:Native)?Query\s*\(\s*\"([^\"]+)\"", body):
                reads |= entities_in_jpql(q)
            for cls in re.findall(r"\b(?:find|getReference)\s*\(\s*(\w+)\.class", body):
                e = resolve(t, cls, types, by_simple)
                if e in tables:
                    reads.add(e)
            # Declarations, including for-each loop variables (`for (Leg leg : legs)`)
            declared = dict((v, ty) for ty, v in re.findall(r"\b([A-Z]\w*)(?:<[^>]*>)?\s+(\w+)\s*[,);=:]", body))
            for op, var in re.findall(r"\.(persist|merge|remove)\s*\(\s*(\w+)", body):
                e = resolve(t, declared.get(var, ""), types, by_simple) if var in declared else None
                if e in tables:
                    writes.add(e)
            cid = class_id(g, t, "jpa-repository")
            for e in sorted(reads):
                g.edge(cid, tables[e], "reads_from", "jpa-repository")
            for e in sorted(writes):
                g.edge(cid, tables[e], "writes_to", "jpa-repository")
        # CDI / EJB dependency injection (framework wiring): @Inject / @EJB fields → calls
        for ty in (re.findall(r"@(?:Inject|EJB)\b(?:\s*@\w+(?:\([^)]*\))?)*\s+(?:private|protected|public)?\s*"
                             r"(?:final\s+)?([A-Z]\w*)(?:<[^>]*>)?\s+\w+\s*;", body)):
            s = resolve(t, ty, types, by_simple)
            if s:
                g.edge(class_id(g, t, "cdi-inject"), class_id(g, types[s], "cdi-inject"), "calls", "cdi-inject")
        # JAX-RS resources → endpoints
        base = re.search(r"@Path\s*\(\s*\"([^\"]*)\"\s*\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public\s+)?"
                         r"(?:abstract\s+)?(?:class|interface)\b", body)
        if base:
            for verb, sub in re.findall(r"@(GET|POST|PUT|DELETE|PATCH)\b((?:\s*@\w+(?:\([^)]*\))?)*)", body):
                pm = re.search(r"@Path\s*\(\s*\"([^\"]*)\"", sub)
                path = "/" + "/".join(x.strip("/") for x in (base.group(1), pm.group(1) if pm else "") if x.strip("/"))
                eid = g.node("endpoint", t.path, f"{verb} {path}", "jax-rs", f"HTTP {verb} {path} ({t.name})")
                g.edge(eid, class_id(g, t, "jax-rs"), "routes", "jax-rs")
    # JMS: producers (@Resource(lookup=…) Queue/Topic fields) publish to a queue node; @MessageDriven
    # consumers with the same destinationLookup are triggered by it — the asynchronous hop of a flow.
    for fq, t in types.items():
        for lookup in re.findall(r"@Resource\s*\(\s*(?:lookup|name|mappedName)\s*=\s*\"([^\"]+)\"[^)]*\)\s*"
                                 r"(?:private|protected|public)?\s*(?:Queue|Topic|Destination)\s+\w+", t.text):
            qid = g.node("resource", "jms", lookup, "jms", f"JMS destination {lookup}")
            g.edge(class_id(g, t, "jms"), qid, "publishes", "jms")
        if re.search(r"@MessageDriven\b", t.text):
            for lookup in re.findall(r"destinationLookup\"\s*,\s*propertyValue\s*=\s*\"([^\"]+)\"", t.text):
                qid = g.node("resource", "jms", lookup, "jms", f"JMS destination {lookup}")
                g.edge(qid, class_id(g, t, "jms"), "triggers", "jms")
    # WebSocket endpoints: @ServerEndpoint("/x") → endpoint `WS /x`, routes to the class
    for fq, t in types.items():
        m = re.search(r"@ServerEndpoint\s*\(\s*(?:value\s*=\s*)?\"([^\"]+)\"", t.text)
        if m:
            eid = g.node("endpoint", t.path, f"WS {m.group(1)}", "websocket", f"WebSocket {m.group(1)} ({t.name})")
            g.edge(eid, class_id(g, t, "websocket"), "routes", "websocket")
    # CDI events: an `@Inject [@Q…] Event<T>` field publishes to `cdi-event [@Q…] T`; a method parameter
    # `@Observes [@Q…] T` is triggered by every event of type T whose qualifiers include the observer's.
    not_qualifiers = {"Inject", "Any", "Default", "Observes", "Named"}
    quals = lambda anns: tuple(sorted(set(re.findall(r"@(\w+)", anns)) - not_qualifiers))
    ev_name = lambda q, ty: " ".join(["cdi-event", *[f"@{x}" for x in q], ty])
    events = {}
    for fq, t in types.items():
        for anns, ty in re.findall(r"((?:@\w+(?:\([^)]*\))?\s*)+)(?:private|protected|public)?\s*(?:final\s+)?"
                                   r"Event\s*<\s*(\w+)[^>]*>\s+\w+\s*;", t.text):
            if "@Inject" in anns:
                key = (quals(anns), ty)
                events[key] = g.node("resource", "cdi", ev_name(*key), "cdi-event", f"CDI event {ev_name(*key)}")
                g.edge(class_id(g, t, "cdi-event"), events[key], "publishes", "cdi-event")
    for fq, t in types.items():
        for before, after, ty in re.findall(r"((?:@\w+(?:\([^)]*\))?\s+)*)@Observes\b((?:\s*@\w+(?:\([^)]*\))?)*)"
                                            r"\s+(?:final\s+)?(\w+)", t.text):
            q = set(quals(before + after))
            hits = [eid for (pq, pty), eid in events.items() if pty == ty and q <= set(pq)]
            if not hits:
                key = (tuple(sorted(q)), ty)
                hits = [g.node("resource", "cdi", ev_name(*key), "cdi-event", f"CDI event {ev_name(*key)}")]
            for eid in hits:
                g.edge(eid, class_id(g, t, "cdi-event"), "triggers", "cdi-event")
    # EJB timers: @Schedule(…) on a method → `timer Class.method (…)` triggers the class
    for fq, t in types.items():
        for args, meth in re.findall(r"@Schedule\s*\(([^)]*)\)\s*(?:@\w+(?:\([^)]*\))?\s*)*"
                                     r"(?:public|protected|private)?\s*(?:\w+\s+)*?\w+\s+(\w+)\s*\(", t.text):
            spec = ", ".join(re.sub(r"\s*=\s*", "=", a.strip()).replace('"', "") for a in args.split(",") if a.strip())
            tid = g.node("resource", t.path, f"timer {t.name}.{meth} ({spec})", "ejb-schedule",
                         f"EJB timer @Schedule({spec}) on {t.name}.{meth}")
            g.edge(tid, class_id(g, t, "ejb-schedule"), "triggers", "ejb-schedule")
    # Batch (JSR 352): batch-jobs/J.xml → `batch-job J` calls each ref="" bean; JobOperator.start("J") calls it
    beans = {}
    for fq, t in types.items():
        m = re.search(r"@Named(?![\w])\s*(?:\(\s*(?:value\s*=\s*)?\"([^\"]+)\"\s*\))?", t.text)
        if m:
            beans[m.group(1) or t.name[0].lower() + t.name[1:]] = t
    jobs = {}
    for f in sorted(root.rglob("batch-jobs/*.xml")):
        path = rel(f, root)
        jid = jobs[f.stem] = g.node("resource", path, f"batch-job {f.stem}", "jsr352", f"Batch job {f.stem}")
        for ref in re.findall(r"\bref\s*=\s*\"([^\"]+)\"", f.read_text(encoding="utf-8", errors="ignore")):
            if ref in beans:
                g.edge(jid, class_id(g, beans[ref], "jsr352"), "calls", "jsr352")
    for fq, t in types.items():
        if "JobOperator" in t.text:
            for job in re.findall(r"\.start\s*\(\s*\"([^\"]+)\"", t.text):
                jid = jobs.get(job) or g.node("resource", "batch", f"batch-job {job}", "jsr352", f"Batch job {job}")
                g.edge(class_id(g, t, "jsr352"), jid, "calls", "jsr352")
    # JSF pages → page nodes; EL bean references → routes to the @Named bean
    eps = endpoint_index(g)
    xhtml = sorted(root.rglob("*.xhtml"))
    for f in xhtml:
        text = f.read_text(encoding="utf-8", errors="ignore")
        # Bean names may contain dots (@Named("public.track")): match each known name inside an EL expression.
        exprs = re.findall(r"[#$]\{([^}]*)\}", text)
        refs = {b for b in beans if any(re.search(rf"(?<![\w.]){re.escape(b)}(?![\w])", e) for e in exprs)}
        path = rel(f, root)
        pid = g.node("page", path, path, "jsf-page", f"JSF page {path}")
        fid = f"file:{path}"
        if fid in g.nodes:
            g.edge(fid, pid, "contains", "jsf-page")
        for b in sorted(refs):
            g.edge(pid, class_id(g, beans[b], "jsf-el"), "routes", "jsf-el", description=f"#{{{b}…}}")
        link_page(g, pid, text, eps, "page-script")
        # Facelets composition: ui:include src / ui:composition|ui:decorate template → the page contains it
        for ref in re.findall(r"<ui:(?:include|composition|decorate)\b[^>]*\b(?:src|template)\s*=\s*\"([^\"#$]+)\"", text):
            hit = next((x for x in xhtml if x.as_posix().endswith("/" + ref.lstrip("/"))), None)
            if hit:
                sub = rel(hit, root)
                g.edge(pid, g.node("page", sub, sub, "jsf-page", f"JSF page {sub}"), "contains", "jsf-include")


# ---------------------------------------------------------------------------------------------- Django

READ_METHODS = {"get", "filter", "exclude", "all", "first", "last", "values", "values_list", "count", "exists",
                "select_related", "prefetch_related", "order_by", "in_bulk", "aggregate", "annotate", "iterator",
                "only", "defer", "distinct", "latest", "earliest", "get_or_create", "update_or_create"}
TASK_DECORATORS = {"task", "shared_task", "actor", "periodic", "db_task", "db_periodic_task"}
TASK_ENQUEUE = {"defer", "defer_async", "delay", "apply_async", "send", "send_with_options", "schedule"}
WRITE_METHODS = {"create", "bulk_create", "update", "delete", "bulk_update", "get_or_create", "update_or_create"}


class PyModule:
    def __init__(self, path, dotted, tree):
        self.path, self.dotted, self.tree = path, dotted, tree
        self.imports = {}          # local name → dotted target (module or module.attr)


def py_index(root):
    mods = {}
    for f in sorted(root.rglob("*.py")):
        parts = list(f.relative_to(root).with_suffix("").parts)
        if parts and parts[0] in ("tests", "test") or "migrations" in parts:
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        # Drop a leading source folder (src/) so dotted names match imports.
        if parts and parts[0] == "src":
            parts = parts[1:]
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        m = PyModule(rel(f, root), ".".join(parts), tree)
        pkg = m.dotted if f.name == "__init__.py" else m.dotted.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    m.imports[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    up = pkg.split(".")
                    up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                    base = ".".join([*up, base] if base else up)
                for a in node.names:
                    m.imports[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
        mods[m.dotted] = m
    return mods


def defined(mods):
    """dotted name → (module, node) for every top-level class and function."""
    out = {}
    for m in mods.values():
        for node in m.tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                out[f"{m.dotted}.{node.name}"] = (m, node)
    return out


def py_node(g, m, node, rule):
    kind = "class" if isinstance(node, ast.ClassDef) else "function"
    return g.node(kind, m.path, node.name, rule, line=node.lineno)


def dotted_of(expr, m):
    """Resolve a Name/Attribute expression to a dotted name through the module's imports."""
    parts = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    head = m.imports.get(expr.id, f"{m.dotted}.{expr.id}")
    return ".".join([head, *reversed(parts)])


def class_constants(cls):
    """name → constant value of a class body's simple assignments (`name = 'x'`)."""
    return {t.id: x.value.value for x in cls.body if isinstance(x, ast.Assign) and isinstance(x.value, ast.Constant)
            for t in x.targets if isinstance(t, ast.Name)}


def app_labels(mods, defs):
    """(app module, label) for each INSTALLED_APPS entry found in the analysed code, longest module first.

    An entry is an AppConfig class (its `name` and `label`) or an app module (the AppConfig in its apps.py
    whose `name` is that module, else the module's last component), as Django resolves them."""
    entries = []
    for m in mods.values():
        for node in m.tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            names = [getattr(t, "id", "") for t in (node.targets if isinstance(node, ast.Assign) else
                                                     [getattr(node, "target", None)])]
            if "INSTALLED_APPS" in names and isinstance(value, (ast.List, ast.Tuple)):
                entries += [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    out = []
    for entry in entries:
        config = defs.get(entry)
        if not (config and isinstance(config[1], ast.ClassDef)):
            config = next(((cm, cn) for d, (cm, cn) in defs.items() if d.startswith(f"{entry}.apps.") and
                           isinstance(cn, ast.ClassDef) and class_constants(cn).get("name") == entry), None)
        attrs = class_constants(config[1]) if config else {}
        module = attrs.get("name") or entry
        out.append((module, attrs.get("label") or module.rsplit(".", 1)[-1]))
    return sorted(out, key=lambda x: -len(x[0]))


def app_label_of(dotted, labels):
    """The label of the installed app containing a module; without settings, the module's own package
    (Django would refuse a model outside an installed app, so this only happens when settings aren't analysed)."""
    for module, label in labels:
        if dotted == module or dotted.startswith(module + "."):
            return label
    parts = dotted.split(".")
    return parts[-2] if len(parts) > 1 else parts[0]


def enrich_django(g, root):
    mods = py_index(root)
    if not mods:
        return
    defs = defined(mods)
    labels = app_labels(mods, defs)
    # Models → tables (Django's default name: <app label>_<model name>)
    models = {}
    for name, (m, node) in defs.items():
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [dotted_of(b, m) or "" for b in node.bases]
        if not any(b.endswith("models.Model") or b in models for b in bases):
            continue
        if any(isinstance(s, ast.ClassDef) and s.name == "Meta" and any(
                isinstance(x, ast.Assign) and any(getattr(tg, "id", "") == "abstract" for tg in x.targets)
                for x in s.body) for s in node.body):
            continue
        meta = {}
        for s in node.body:
            if isinstance(s, ast.ClassDef) and s.name == "Meta":
                meta = class_constants(s)
        table = meta.get("db_table") or f"{meta.get('app_label') or app_label_of(m.dotted, labels)}_{node.name.lower()}"
        tid = g.node("table", m.path, table, "django-model", f"Table {table} mapped by Django model {node.name}",
                     node.lineno)
        g.edge(py_node(g, m, node, "django-model"), tid, "defines_schema", "django-model")
        models[name] = tid
    model_by_simple = {n.rsplit(".", 1)[1]: n for n in models}

    def model_of(expr, m):
        d = dotted_of(expr, m)
        if d in models:
            return d
        return model_by_simple.get(d.rsplit(".", 1)[-1]) if d else None

    # Task-queue tasks (Celery, Procrastinate, Huey, Dramatiq): @app.task / @shared_task / @actor → `task`
    # node triggers the function; f.defer() / .delay() / .apply_async() / .send() publish to it.
    tasks = {}
    for name, (m, node) in defs.items():
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                (getattr(d.func if isinstance(d, ast.Call) else d, "attr", None)
                 or getattr(d.func if isinstance(d, ast.Call) else d, "id", None)) in TASK_DECORATORS
                for d in node.decorator_list):
            tasks[name] = g.node("task", m.path, f"task {name}", "python-task", f"Queued task {name}", node.lineno)
            g.edge(tasks[name], py_node(g, m, node, "python-task"), "triggers", "python-task")
    # Management commands: <app>/management/commands/<name>.py → `command <name>` routes its Command class
    for name, (m, node) in defs.items():
        cm = re.search(r"/management/commands/(\w+)\.py$", "/" + m.path)
        if cm and isinstance(node, ast.ClassDef) and node.name == "Command":
            cid = g.node("command", m.path, cm.group(1), "django-command", f"manage.py {cm.group(1)}")
            g.edge(cid, py_node(g, m, node, "django-command"), "routes", "django-command")

    # Function-level: ORM reads/writes, template renders, task enqueues (calls between project code come from
    # Graphify's language layer, ADR-0025)
    for name, (m, top) in defs.items():
        scopes = [top] if not isinstance(top, ast.ClassDef) else [top] + [
            s for s in top.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
        owner = py_node(g, m, top, "django-code")
        for scope in scopes:
            local_types = {}
            for node in ast.walk(scope):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    mt = model_of(node.value.func, m)
                    for tg in node.targets:
                        if isinstance(tg, ast.Name) and mt:
                            local_types[tg.id] = mt
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                # Model.objects.<method>(...) (also chained: Model.objects.filter(...).first())
                chain, base = [], f
                while isinstance(base, ast.Attribute):
                    chain.append(base.attr)
                    base = base.value
                    if isinstance(base, ast.Call):
                        base = base.func
                chain.reverse()
                if "objects" in chain:
                    mt = model_of(base, m)
                    meths = set(chain[chain.index("objects") + 1:])
                    if mt:
                        if meths & READ_METHODS or not meths:
                            g.edge(owner, models[mt], "reads_from", "django-orm")
                        if meths & WRITE_METHODS:
                            g.edge(owner, models[mt], "writes_to", "django-orm")
                    continue
                if isinstance(f, ast.Attribute) and f.attr in ("save", "delete") and isinstance(f.value, ast.Name) \
                        and f.value.id in local_types:
                    g.edge(owner, models[local_types[f.value.id]], "writes_to", "django-orm")
                    continue
                # render(request, "template.html") → page
                if isinstance(f, (ast.Name, ast.Attribute)) and (getattr(f, "id", None) or f.attr) in (
                        "render", "render_to_string", "TemplateResponse") and len(node.args) >= 1:
                    tmpl = next((a.value for a in node.args if isinstance(a, ast.Constant) and
                                 isinstance(a.value, str) and a.value.endswith((".html", ".txt"))), None)
                    if tmpl:
                        hit = next((p for p in sorted(root.rglob("*.html")) if p.as_posix().endswith(tmpl)), None)
                        page = rel(hit, root) if hit else tmpl
                        g.edge(owner, g.node("page", page, page, "django-template", f"Template {tmpl}"),
                               "routes", "django-template")
                    continue
                if isinstance(f, ast.Attribute) and f.attr in TASK_ENQUEUE and dotted_of(f.value, m) in tasks:
                    g.edge(owner, tasks[dotted_of(f.value, m)], "publishes", "python-task")
                    continue

    # URL routing: path()/re_path() with include() prefixes
    def urlpatterns(m):
        for node in m.tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "urlpatterns" for t in node.targets) \
                    and isinstance(node.value, (ast.List, ast.Tuple)):
                return node.value.elts
        return []

    seen, url_names = set(), {}

    def app_name(m):
        for node in m.tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "app_name" for t in node.targets) \
                    and isinstance(node.value, ast.Constant):
                return node.value.value
        return None

    def walk(m, prefix, ns=()):
        if (m.dotted, prefix) in seen:
            return
        seen.add((m.dotted, prefix))
        for call in urlpatterns(m):
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", getattr(call.func, "attr", ""))
                    in ("path", "re_path") and len(call.args) >= 2 and isinstance(call.args[0], ast.Constant)):
                continue
            route = prefix + str(call.args[0].value)
            view = call.args[1]
            if isinstance(view, ast.Call) and getattr(view.func, "id", getattr(view.func, "attr", "")) == "include":
                arg = view.args[0] if view.args else None
                if isinstance(arg, ast.Constant) and arg.value in mods:
                    sub = mods[arg.value]
                    kw = {k.arg: k.value.value for k in view.keywords if isinstance(k.value, ast.Constant)}
                    space = kw.get("namespace") or app_name(sub)
                    walk(sub, route, ns + ((space,) if space else ()))
                continue
            if isinstance(view, ast.Call) and isinstance(view.func, ast.Attribute) and view.func.attr == "as_view":
                view = view.func.value
            elif isinstance(view, ast.Call):
                view = view.func          # a factory / composition root that builds the view: route to it
            target = dotted_of(view, m)
            eid = g.node("endpoint", m.path, "/" + route.lstrip("/"), "django-url", f"URL /{route.lstrip('/')}",
                         call.lineno)
            uname = next((k.value.value for k in call.keywords if k.arg == "name" and isinstance(k.value, ast.Constant)),
                         None)
            if uname:
                url_names[":".join([*ns, uname])] = eid
            if target in defs:
                tm, tn = defs[target]
                g.edge(eid, py_node(g, tm, tn, "django-url"), "routes", "django-url")

    roots = [m for m in mods.values() if m.path.endswith("urls.py")]
    included = set()
    for m in roots:
        for call in urlpatterns(m):
            for node in ast.walk(call):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "include" and node.args \
                        and isinstance(node.args[0], ast.Constant):
                    included.add(node.args[0].value)
    for m in roots:
        if m.dotted not in included:
            walk(m, "")

    # Templates: htmx / fetch calls → routes to endpoints ({% url 'ns:name' %} or a literal path);
    # {% include %} / {% extends %} → contains
    eps = endpoint_index(g)
    templates = sorted(p for p in root.rglob("*.html") if "tests" not in p.relative_to(root).parts)

    def named(url):
        m = re.fullmatch(r"\s*\{%\s*url\s+['\"]([^'\"]+)['\"][^%]*%\}\s*", url)
        return url_names.get(m.group(1)) if m else None

    for f in templates:
        text = f.read_text(encoding="utf-8", errors="ignore")
        page = rel(f, root)
        pid = g.node("page", page, page, "django-template", f"Template {page}")
        link_page(g, pid, text, eps, "template-script", named)
        for ref in re.findall(r"\{%\s*(?:include|extends)\s+['\"]([^'\"]+)['\"]", text):
            hit = next((p for p in templates if p.as_posix().endswith("/" + ref)), None)
            if hit:
                sub = rel(hit, root)
                g.edge(pid, g.node("page", sub, sub, "django-template", f"Template {sub}"), "contains",
                       "django-include")


# --------------------------------------------------------------------------------------------- Graphify

GRAPHIFY_SCHEMAS = {1}                 # graph.schema_version values this merge understands (ADR-0025)
GRAPHIFY_FLOW = {"calls": "calls", "indirect_call": "calls", "uses": "calls", "implements": "implements",
                 "inherits": "inherits"}      # `uses`: instantiation or a typed parameter (how Python code wires)
INTERFACE_BASES = {"Protocol", "ABC"}  # an `inherits` into a class built on these is `implements` (ADR-0025)


class GraphifyError(Exception):
    pass


def merge_graphify(g, doc):
    """Add Graphify's language-level structure (calls, implements, inherits) between top-level types and
    functions, matched to existing nodes by (file, name). Methods count as their type. `references` and
    `uses` (a type is mentioned) are not flow and are left out. Every edge says Graphify's confidence."""
    version = (doc.get("graph") or {}).get("schema_version")
    if version not in GRAPHIFY_SCHEMAS:
        raise GraphifyError(f"Graphify graph.schema_version {version!r} is not one of {sorted(GRAPHIFY_SCHEMAS)}: "
                            "pin the Graphify version this harness supports (tools/locks/graphify.lock)")
    nodes = {n["id"]: n for n in doc.get("nodes", [])}
    owner, top = {}, set()
    for link in doc.get("links", []):
        if link["relation"] == "method":
            owner[link["target"]] = link["source"]
        elif link["relation"] == "contains":
            top.add(link["target"])

    def type_of(nid):
        seen = set()
        while nid in owner and nid not in top and nid not in seen:
            seen.add(nid)
            nid = owner[nid]
        n = nodes.get(nid)
        return n if n and n.get("file_type") == "code" and not n.get("external") and n.get("source_file") else None

    existing = {(n.get("filePath"), n.get("name")): n["id"] for n in g.nodes.values()
                if n.get("type") in ("class", "function", "interface")}

    def node_id(n):
        name = n["label"].lstrip(".").removesuffix("()")
        key = (n["source_file"], name)
        if key not in existing:
            kind = "class" if n.get("_callable_class") else "function"
            line = int(re.sub(r"\D", "", str(n.get("source_location") or "")) or 0) or None
            existing[key] = g.node(kind, n["source_file"], name, "graphify", line=line)
        return existing[key]

    interfaces = {l["source"] for l in doc.get("links", []) if l["relation"] == "inherits"
                  and nodes.get(l["target"], {}).get("label") in INTERFACE_BASES}
    for link in doc.get("links", []):
        etype = GRAPHIFY_FLOW.get(link["relation"])
        a, b = type_of(link["source"]), type_of(link["target"])
        if not etype or not a or not b or a is b:
            continue
        if etype == "inherits" and b["id"] in interfaces:
            etype = "implements"
        where = f"{link.get('source_file', '')}:{link.get('source_location', '')}".strip(":")
        g.edge(node_id(a), node_id(b), etype, "graphify",
               description=f"{link['relation']} {link.get('confidence', '?')} {where}".strip())


ENRICHERS = {"java-ee": enrich_java_ee, "django": enrich_django}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("graph")
    ap.add_argument("--root", required=True, help="the folder the graph was built from")
    ap.add_argument("--enricher", action="append", default=[], choices=sorted(ENRICHERS))
    ap.add_argument("--graphify", metavar="GRAPH_JSON", help="Graphify's graph.json for the same folder: merged "
                    "first, as the language-level layer (ADR-0025)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    path = pathlib.Path(a.graph)
    doc = json.loads(path.read_text(encoding="utf-8"))
    g = Graph(doc)
    root = pathlib.Path(a.root)
    if not a.enricher and not a.graphify:
        ap.error("give --graphify and/or at least one --enricher")
    if a.graphify:
        try:
            merge_graphify(g, json.loads(pathlib.Path(a.graphify).read_text(encoding="utf-8")))
        except GraphifyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"graphify: +{sum(g.added.values())}")
        gmeta = json.loads(pathlib.Path(a.graphify).read_text(encoding="utf-8")).get("graph") or {}
    for name in a.enricher:
        before = sum(g.added.values())
        ENRICHERS[name](g, root)
        print(f"{name}: +{sum(g.added.values()) - before}")
    used = (["graphify"] if a.graphify else []) + a.enricher
    doc.setdefault("project", {})["afsEnrichment"] = {"enrichers": used, "added": dict(sorted(g.added.items())),
                                                      **({"graphify": gmeta} if a.graphify else {})}
    pathlib.Path(a.out or path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    summary = " ".join(f"{k.replace(':', '_')}={v}" for k, v in sorted(g.added.items()))
    print(f"AFS-RESULT gate=graph-enrich enrichers={','.join(used)} {summary}".rstrip())
    return 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
