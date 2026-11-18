import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const filenames = {
    sessions: "sessions.json", needs: "needs.json", families: "trend.json",
    cases: "trend-cases.json", coverage: "trend-coverage.json",
};
const repos = ["pilot-target", "synthetic-target", "eval", "swarm"].flatMap(
    name => ["--repo", `martins-vds/ai-factory-${name}`],
);
const live = new Map();
const cadence = { sessions: 120_000, needs: 600_000 };

function parse(text) {
    const doc = JSON.parse(text);
    if (!Array.isArray(doc?.rows) || !Array.isArray(doc.meta) ||
        !Number.isFinite(Date.parse(doc.meta.find(m => m?.label === "Generated")?.value))) {
        throw new Error("Expected {rows, meta} with a valid Generated timestamp.");
    }
    return doc;
}

function update(name) {
    const entry = live.get(name) ?? {};
    if (!entry.pending && (!entry.at || Date.now() - entry.at >= cadence[name])) {
        entry.pending = promisify(execFile)("python3", [
            join(root, "tools/afs-dashboard"), name, ...repos, "--out", "-",
        ], { cwd: root, timeout: 240_000, maxBuffer: 8 * 1024 * 1024 }).then(
            ({ stdout }) => {
                entry.doc = parse(stdout);
                entry.error = null;
            },
        ).catch(error => {
            entry.error = error.stderr?.trim().slice(0, 2000) ||
                (error.killed ? "GitHub refresh timed out." : error.message);
        }).finally(() => {
            entry.pending = null;
            entry.at = Date.now();
        });
        live.set(name, entry);
    }
    return entry;
}

async function dataset(name, snapshotDir, includeLive, refresh) {
    const entry = !includeLive ? null : refresh && name in cadence ? update(name) : live.get(name);
    const result = { pending: Boolean(entry?.pending), error: entry?.error ?? null };
    let snapshot;
    try {
        snapshot = parse(await readFile(join(snapshotDir, filenames[name]), "utf8"));
    } catch (error) {
        if (error.code !== "ENOENT") result.snapshotError = `Could not read ${filenames[name]}: ${error.message}`;
    }
    const doc = entry?.doc;
    const generated = value => Date.parse(value?.meta.find(m => m.label === "Generated")?.value);
    const useLive = doc && (!snapshot || generated(doc) >= generated(snapshot));
    return { ...result, doc: useLive ? doc : snapshot ?? null, source: useLive ? "Live via gh" : snapshot ? "Snapshot" : null };
}

async function datasets(snapshotDir, includeLive, refresh) {
    return Object.fromEntries(await Promise.all(Object.keys(filenames).map(async name =>
        [name, await dataset(name, snapshotDir, includeLive, refresh)])));
}

const assets = new Map([
    ["", ["dashboard.html", "text/html"]], ["dashboard.css", ["dashboard.css", "text/css"]],
    ["dashboard.mjs", ["dashboard.mjs", "text/javascript"]], ["model.mjs", ["model.mjs", "text/javascript"]],
]);

export async function startServer({ snapshotDir = join(root, ".afs-dashboard"), includeLive = true } = {}) {
    const prefix = `/${randomBytes(24).toString("base64url")}/`;
    const server = createServer(async (req, res) => {
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Referrer-Policy", "no-referrer");
        res.setHeader("X-Content-Type-Options", "nosniff");
        res.setHeader("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'");
        if (req.method !== "GET" || req.headers.host !== `127.0.0.1:${server.address().port}` ||
            req.headers["sec-fetch-site"] === "cross-site" && req.headers["sec-fetch-mode"] !== "navigate" ||
            !req.url?.startsWith(prefix)) {
            res.writeHead(404).end();
            return;
        }
        const path = req.url.slice(prefix.length);
        try {
            if (path === "data") {
                res.setHeader("Content-Type", "application/json; charset=utf-8");
                res.end(JSON.stringify(await datasets(snapshotDir, includeLive, true)));
            } else if (assets.has(path)) {
                const [file, type] = assets.get(path);
                const body = await readFile(new URL(file, import.meta.url));
                res.setHeader("Content-Type", `${type}; charset=utf-8`);
                res.end(body);
            } else {
                res.writeHead(404).end();
            }
        } catch (error) {
            res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" }).end(`Dashboard: ${error.message}`);
        }
    });
    await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(0, "127.0.0.1", resolve);
    });
    return {
        server,
        url: `http://127.0.0.1:${server.address().port}${prefix}`,
        async status() {
            return Object.fromEntries(Object.entries(await datasets(snapshotDir, includeLive, false)).map(([name, value]) => [
                name, { source: value.source, rows: value.doc?.rows.length ?? null,
                    generated: value.doc?.meta.find(m => m.label === "Generated")?.value,
                    error: value.error ?? value.snapshotError, pending: value.pending },
            ]));
        },
    };
}
