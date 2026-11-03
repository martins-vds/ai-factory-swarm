# ADR-0023: Code graphs follow scheduled, pushed and scripted flows, and cover every template

- Status: Accepted
- Date: 2026-11-03

## Context
ADR-0020 made the graph gate the way a slice proves its entry points reach data. Its enrichers covered
pages, JAX-RS, JPA, JMS and the Django ORM and URLs: enough for Track Cargo, whose flows are a form, a
view and a repository. The next slices on the pilot's decision map are not shaped like that:

- **Handling-event file upload:** an EJB timer (`@Schedule`) starts a JSR 352 batch job by name, and the
  job's XML wires reader and writer beans, which register attempts through JMS.
- **Admin live map:** the page fetches `/rest/cargo` from a script, and opens a WebSocket
  (`@ServerEndpoint`) fed by a CDI event (`Event<Cargo>.fire` → `@Observes`). In the target, an htmx
  attribute polls a partial view.
- **Handling registration (target):** a worker is a management command or a queued task.

None of these hops was in the graph. Those slices could not anchor their data paths, so the gate would
fail them, or tempt someone to drop the anchor. Separately, the target graph analyses only
`graph.target_paths` (default `src`). The pilot keeps its page templates in a top-level `templates/`
folder, so even Track Cargo's htmx form was invisible, and nothing said so.

## Decision
1. **Enrichers add the missing hops**, each tagged `afs-enriched:<rule>` and covered by fixtures:
   - `java-ee`: `@ServerEndpoint` → endpoint `WS /path`; CDI `Event<T>` fields publish to
     `cdi-event [@Q…] T`, which triggers each `@Observes` method whose qualifiers it includes; `@Schedule`
     → `timer Class.method (spec)` triggers the class; `JobOperator.start("J")` calls `batch-job J`,
     which calls the beans its `batch-jobs/J.xml` references.
   - `django`: `management/commands/<name>.py` → `command <name>` routes its `Command`; task-queue
     decorators (`@app.task`, `@shared_task`, `@actor`, `@app.periodic`) → `task` triggers the function,
     and `.defer()`/`.delay()`/`.apply_async()`/`.send()` publish to it; URL names, with namespaces, are
     resolved; `{% include %}`/`{% extends %}` → `contains`.
   - Both: page and template scripts route to endpoints: `fetch(url[, {method}])`, path literals on a page
     that opens a `WebSocket`, and htmx `hx-<verb>` attributes (a literal path or `{% url 'ns:name' %}`).
     A URL matches an endpoint when the endpoint's path is a suffix at a segment boundary (so context and
     application paths don't matter), parameters match one segment, and the verb agrees; `/` matches only
     `/`.
2. **The target graph must cover every template.** `check_graph_fresh.py` reports each tracked Django
   template (an `.html` file with `{% %}` or `{{ }}`) outside the analysed paths, naming the fix (add the
   folder to `graph.target_paths`). Like staleness, it is a warning on ordinary changes and fails at
   acceptance and in the graph workflow's own check (`--only`), so an incomplete graph can't be committed.

## Consequences
- On the pilot's source graph, the drop-folder scanner and the admin map frame now reach the `Cargo`
  table through the timer, batch job, JMS and REST hops. The WebSocket endpoint correctly has no path:
  it only pushes.
- The pilot's profile needs `graph.target_paths: [src, templates]`, and a rebuilt target graph.
- Entry points that are not screens (timers, commands, jobs) are valid `data_paths` anchors; the Planner
  is told so.
- Remaining blind spots, to be added when a slice needs them: XMLHttpRequest/jQuery calls, links
  between pages (`href`), and Django signals.
