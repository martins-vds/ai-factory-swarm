import { ageMinutes, approvalKey, classify, safeGitHubUrl, splitSessions } from "./model.mjs";

const $ = id => document.getElementById(id);
let data;
let now;
const state = (text, warning = false) => el("span", text, warning ? "pill warning" : "pill");

function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
}

function link(text, url, external = true) {
    const href = external ? safeGitHubUrl(url) : url;
    if (!href) return el("span", text);
    const a = el("a", text);
    a.href = href;
    if (external) {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
    }
    return a;
}

function table(container, headers, rows, empty) {
    if (!rows.length) {
        container.replaceChildren(el("p", empty, "empty"));
        return;
    }
    const wrap = el("div", null, "table-wrap");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", headers.join(", "));
    const t = el("table");
    const head = t.createTHead().insertRow();
    for (const label of headers) {
        const th = el("th", label);
        th.scope = "col";
        head.append(th);
    }
    const body = t.createTBody();
    for (const { cells, id } of rows) {
        const row = body.insertRow();
        if (id) row.id = id;
        for (const cell of cells) row.insertCell().append(cell ?? "—");
    }
    wrap.append(t);
    container.replaceChildren(wrap);
}

function renderMeta(name) {
    const container = $(`${name}-meta`);
    const { doc, source, error, pending, snapshotError } = data[name];
    const meta = el("div", null, "meta");
    const generated = doc?.meta.find(m => m.label === "Generated")?.value;
    if (generated) {
        const time = el("time", new Date(generated).toLocaleString());
        time.dateTime = generated;
        const info = el("span", "Generated ");
        info.append(time, ` · ${source}`);
        meta.append(info);
        if (ageMinutes(generated, now) > (name === "sessions" ? 5 : 60)) meta.append(state("Stale", true));
    }
    if (pending) meta.append(el("span", "Refreshing via gh…"));
    if (doc) {
        const details = el("details");
        details.open = container.querySelector("details")?.open ?? false;
        details.append(el("summary", "Generator & input"));
        for (const item of doc.meta.filter(m => m.label !== "Generated")) {
            details.append(el("strong", item.label), el("pre", item.value));
        }
        meta.append(details);
    }
    for (const problem of [error, snapshotError].filter(Boolean)) meta.append(el("span", problem, "error"));
    container.replaceChildren(meta);
}

const rowsOf = name => data[name].doc?.rows ?? [];
const waitingFor = name => data[name].pending ? "Waiting for GitHub data…" : "No dataset available.";
const repo = row => row.repo.split("/").at(-1);
const target = row => `need-${approvalKey(row)}`;

function showNeeds(active) {
    const needs = new Map(rowsOf("needs").map(row => [approvalKey(row), row]));
    for (const row of active) {
        if (!row.approval) continue;
        const key = approvalKey(row.approval);
        const legacyKey = [...needs].find(([, need]) => need.kind === row.approval.kind &&
            need.repo === row.repo && (need.number === row.pr || need.title === row.approval.title))?.[0];
        if (legacyKey && legacyKey !== key) needs.delete(legacyKey);
        const mark = data.sessions.doc.meta.find(m => m.label === "Generated").value;
        if (!needs.has(key)) needs.set(key, { ...row.approval, sessionGenerated: mark });
    }
    const rows = [...needs.values()].sort((a, b) => Date.parse(a.waiting_since) - Date.parse(b.waiting_since));
    table($("needs-data"), ["Kind", "Repository", "Item", "Waiting"], rows.map(row => {
        const item = el("span");
        item.append(link(row.title, row.url));
        if (row.sessionGenerated) item.append(el("small", `From sessions · ${new Date(row.sessionGenerated).toLocaleString()}`));
        const days = ageMinutes(row.waiting_since, now) / 1440;
        return { id: target(row), cells: [row.kind, `${repo(row)}${row.number ? ` #${row.number}` : ""}`,
            item, `${Math.max(0, days).toFixed(1)} d`] };
    }), data.needs.doc ? "Nothing waits on the operator." : waitingFor("needs"));
}

function sessionRows(rows) {
    return rows.map(({ row, status }) => {
        const finished = row.status === "finished";
        const interval = ageMinutes(row.started_at, finished ? Date.parse(row.finished_at) : now);
        const elapsed = Number.isFinite(interval) ? `${Math.max(0, Math.floor(interval))} min${finished ? "" : " of 60"}` : "—";
        const context = el("span");
        context.append(row.run ?? "—");
        if (row.case) context.append(el("small", row.case));
        const statusCell = el("span");
        statusCell.append(state(status, ["no PR", "near limit", "over limit"].includes(status)));
        if (row.approval) {
            const note = el("small");
            note.append(link("Runs need approval", `#${encodeURIComponent(target(row.approval))}`, false));
            statusCell.append(note);
        }
        return { cells: [repo(row), link(`#${row.issue}`, `https://github.com/${row.repo}/issues/${row.issue}`),
            row.pr ? link(`#${row.pr}`, row.url) : null, row.agent, row.base, row.ticket, context, elapsed, statusCell] };
    });
}

function showSessions(active, finished) {
    const running = active.map(row => ({ row, status: classify(row, now) }));
    const complete = finished.map(row => ({ row, status: "finished" }));
    const totals = [
        ["Active", running.length],
        ["Near limit", running.filter(r => r.status === "near limit").length],
        ["Stalled", running.filter(r => ["no PR", "over limit"].includes(r.status)).length],
    ];
    $("summary").replaceChildren(...totals.map(([key, n]) => {
        const card = el("div");
        card.append(el("strong", data.sessions.doc ? n : "—"), el("span", key));
        return card;
    }));
    const group = $("group-run").checked;
    const byRun = new Map();
    for (const item of [...running, ...complete]) {
        const key = item.row.run ?? "Other sessions";
        if (!byRun.has(key)) byRun.set(key, { running: [], complete: [] });
        const bucket = byRun.get(key);
        (item.status === "finished" ? bucket.complete : bucket.running).push(item);
    }
    const groups = [...byRun].sort(([a], [b]) => a.localeCompare(b));
    const groupSummary = $("session-groups");
    groupSummary.replaceChildren();
    if (group && groups.length) {
        table(groupSummary, ["Eval run", "Running", "Starting", "Finished (24h)"], groups.map(([key, val]) =>
            ({ cells: [key, val.running.filter(r => r.row.status === "running").length,
                val.running.filter(r => r.row.status === "starting").length, val.complete.length] })), "");
    }
    for (const [id, key, list, empty, timeLabel] of [
        ["active", "running", running, "No sessions are running.", "Elapsed"],
        ["finished", "complete", complete, "No sessions finished in the last 24 hours.", "Duration"],
    ]) {
        const headers = ["Repository", "Issue", "PR", "Agent", "Base", "Ticket", "Eval run / case", timeLabel, "Status"];
        const container = $(id);
        if (group && list.length) {
            container.replaceChildren(...groups.filter(([, set]) => set[key].length).map(([name, set]) => {
                const block = el("div");
                const grid = el("div");
                table(grid, headers, sessionRows(set[key]), "");
                block.append(el("h3", name), grid);
                return block;
            }));
        } else {
            table(container, headers, sessionRows(list), data.sessions.doc ? empty : waitingFor("sessions"));
        }
    }
}

function chronological(a, b) {
    return a.date.localeCompare(b.date) || a.family.localeCompare(b.family);
}
const ratio = (passed, total) => `${passed}/${total}`;

function showTrend() {
    const rows = [...rowsOf("families")].sort(chronological);
    table($("families-data"), ["Date", "Family", "Runs", "Verifier", "Migrator", "Pass rate", "Median min/case"],
        rows.map(r => ({ cells: [r.date, r.family, r.runs, ratio(r.verifier_passed, r.verifier_cases),
            ratio(r.migrator_passed, r.migrator_cases), Number(r.pass_rate).toFixed(3), r.median_minutes ?? ""] })),
        data.families.doc ? "No graded families." : waitingFor("families"));
    const host = $("chart");
    host.replaceChildren();
    if (!rows.length) return;
    const svgEl = (tag, attrs, text) => {
        const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
        for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
        if (text) node.textContent = text;
        return node;
    };
    const width = Math.max(360, rows.length * 52 + 64);
    const svg = svgEl("svg", { width, height: 155, role: "group", "aria-label": "Eval majority pass rate by family" });
    const points = rows.map((r, i) => [48 + i * (width - 84) / Math.max(1, rows.length - 1), 116 - r.pass_rate * 98]);
    for (const [label, y] of [["100%", 18], ["50%", 67], ["0%", 116]]) {
        svg.append(svgEl("line", { x1: 40, x2: width - 18, y1: y, y2: y, class: "grid" }),
            svgEl("text", { x: 3, y: y + 4, class: "axis" }, label));
    }
    svg.append(svgEl("polyline", { points: points.map(p => p.join(",")).join(" "), class: "line" }));
    const tip = el("p", "Hover or focus a point for the family details.", "chart-info");
    rows.forEach((row, i) => {
        const [x, y] = points[i];
        const label = `${row.family} · ${row.date} · ${row.runs} run(s) · ${ratio(row.passed_cases, row.cases)} cases passed`;
        const pt = svgEl("circle", { cx: x, cy: y, r: 6, class: "point", tabindex: 0, "aria-label": label });
        pt.append(svgEl("title", {}, label));
        for (const event of ["pointerenter", "focus"]) pt.addEventListener(event, () => { tip.textContent = label; });
        svg.append(pt, svgEl("text", { x, y: 138, class: "axis", "text-anchor": "middle" }, row.family));
    });
    const chart = el("div", null, "chart");
    chart.append(svg, tip);
    host.append(chart);
}

const familyKey = row => `${row.date}/${row.family}`;
function setOptions(select, options, placeholder) {
    if (JSON.stringify(options) === select.dataset.options) return;
    const value = select.value;
    select.replaceChildren(new Option(placeholder, ""), ...options.map(([key, label]) => new Option(label, key)));
    if (options.some(([key]) => key === value)) select.value = value;
    select.dataset.options = JSON.stringify(options);
}

function showCases() {
    const rows = [...rowsOf("cases")].sort(chronological);
    setOptions($("family"), [...new Map(rows.map(r => [familyKey(r), `${r.family} · ${r.date}`]))].reverse(), "All families");
    setOptions($("case-id"), [...new Set(rows.map(r => r.case))].sort().map(key => [key, key]), "Select a case");
    const filter = (id, value) => !$(id).value || $(id).value === value;
    const columns = ["Date", "Family", "Case", "Kind", "Passes / runs", "Majority"];
    const format = r => ({ cells: [r.date, r.family, r.case, r.kind, ratio(r.passes, r.runs), r.passed ? "Passed" : "Not passed"] });
    table($("cases-data"), columns, rows.filter(r => filter("family", familyKey(r)) && filter("kind", r.kind)
        && filter("passed", String(r.passed))).map(format),
        data.cases.doc ? "No cases match these filters." : waitingFor("cases"));
    table($("history"), columns, rows.filter(r => r.case === $("case-id").value).map(format), "Select a case to see its history.");
}

function showCoverage() {
    table($("coverage-data"), ["Role", "Eval coverage"], rowsOf("coverage").map(r =>
        ({ cells: [r.role, state(r.has_case ? "Has case" : "No case", !r.has_case)] })),
        data.coverage.doc ? "No roles found in the supplied returns." : "No coverage snapshot. Generate trend with --target to add live role coverage.");
}

const num = (value, digits = 2) => value == null ? "—" : Number(value).toFixed(digits);
const firstLast = (a, b, digits) => a == null && b == null ? "—" : a === b ? num(b, digits) : `${num(a, digits)} → ${num(b, digits)}`;
const sliceKey = row => `${row.target}/${row.slice}`;

function showHealth() {
    const rows = rowsOf("health");
    const findings = r => {
        const parts = [["own-code patches", r.own_patches], ["private", r.private], ["interaction", r.interaction],
            ["browser", r.browser]].filter(([, n]) => n);
        return parts.length ? state(parts.map(([label, n]) => `${n} ${label}`).join(", "), true) : "none";
    };
    const refactor = r => !r.refactor ? "none yet" : r.refactor_tests_changed == null ? r.refactor
        : r.refactor_tests_changed ? state(`${r.refactor}: ${r.refactor_tests_changed} test(s) changed`, true)
        : `${r.refactor}: no test changed`;
    table($("health-data"), ["Target", "Slice", "Tickets", "Mutation", "Max CRAP", "Test run (s)", "Flaky",
        "Coupled tests", "Coupling", "Spec cases", "Last refactor"], rows.map(r => ({ cells: [r.target, r.slice, r.tickets,
        firstLast(r.mutation_first, r.mutation_last, 2), num(r.crap_max, 0), num(r.tests_seconds, 1),
        r.flaky ? state(String(r.flaky), true) : "0", findings(r), num(r.coupling, 2), r.spec_cases || "—",
        refactor(r)] })),
        data.health.doc ? "No slices in the supplied targets." :
            "No test-health snapshot. Generate it with tools/afs-dashboard health --target <checkout>.");
    showHealthTickets();
}

function showHealthTickets() {
    const rows = rowsOf("healthTickets");
    setOptions($("health-slice"), [...new Set(rows.map(sliceKey))].sort().map(key => [key, key]), "All slices");
    const chosen = $("health-slice").value;
    table($("health-tickets"), ["Landed", "Target", "Slice", "Ticket", "Mutation", "Max CRAP", "Test run (s)", "Flaky"],
        rows.filter(r => !chosen || sliceKey(r) === chosen).map(r => ({ cells: [r.landed, r.target, r.slice, r.ticket,
            num(r.mutation, 2), num(r.crap_max, 0), num(r.tests_seconds, 1), r.flaky ? state(String(r.flaky), true) : "0"] })),
        data.healthTickets.doc ? "No finished Migrator tickets." : "No test-health snapshot.");
}

const activeSessions = () => splitSessions(rowsOf("sessions"), now);
let rendered;
function render() {
    for (const name of Object.keys(data)) renderMeta(name);
    const { active, finished } = activeSessions();
    showNeeds(active);
    showSessions(active, finished);
    if (rendered?.families !== data.families.doc) showTrend();
    if (rendered?.cases !== data.cases.doc) showCases();
    if (rendered?.coverage !== data.coverage.doc) showCoverage();
    if (rendered?.health !== data.health.doc || rendered?.healthTickets !== data.healthTickets.doc) showHealth();
    rendered = Object.fromEntries(Object.entries(data).map(([name, value]) => [name, value.doc]));
}

let lastPayload;
async function poll() {
    try {
        if (!document.hidden || !data) {
            const response = await fetch("data", { signal: AbortSignal.timeout(10_000) });
            if (!response.ok) throw new Error(`Local data request returned ${response.status}`);
            const payload = await response.text();
            now = Date.now();
            if (payload !== lastPayload) {
                const next = JSON.parse(payload);
                for (const name of Object.keys(next)) {
                    if (JSON.stringify(next[name].doc) === JSON.stringify(data?.[name]?.doc)) next[name].doc = data[name].doc;
                }
                data = next;
                lastPayload = payload;
                render();
            } else if (document.activeElement?.closest("#sessions, #needs") == null) {
                render();
            }
            $("connection").textContent = "";
        }
    } catch (error) {
        $("connection").textContent = `Dashboard data unavailable: ${error.message}`;
    } finally {
        setTimeout(poll, 15_000);
    }
}

$("group-run").addEventListener("change", () => {
    if (!data) return;
    const { active, finished } = activeSessions();
    showSessions(active, finished);
});
for (const id of ["family", "kind", "passed", "case-id"]) $(id).addEventListener("change", () => { if (data) showCases(); });
$("health-slice").addEventListener("change", () => { if (data) showHealthTickets(); });
poll();
