import assert from "node:assert/strict";
import test from "node:test";
import { classify, safeGitHubUrl, splitSessions } from "./model.mjs";
import { startServer } from "./server.mjs";

const now = Date.parse("2026-11-18T12:00:00Z");
const ago = minutes => new Date(now - minutes * 60_000).toISOString();
const running = (elapsed, commit) => ({
    status: "running", started_at: ago(elapsed), last_commit_at: commit == null ? null : ago(commit),
});

test("session thresholds", () => {
    for (const [elapsed, commit, expected] of [
        [49, null, "running"], [50, null, "near limit"], [60, null, "near limit"],
        [61, 9, "near limit"], [61, 10, "over limit"],
    ]) assert.equal(classify(running(elapsed, commit), now), expected);
    for (const [elapsed, expected] of [[4, "starting"], [15, "no PR"]]) {
        assert.equal(classify({ status: "starting", started_at: ago(elapsed) }, now), expected);
    }
});

test("finished within 24 hours, newest first", () => {
    const finished = n => ({ status: "finished", finished_at: ago(n) });
    const active = running(50);
    assert.deepEqual(splitSessions([finished(1440), finished(1441), active, finished(5)], now),
        { active: [active], finished: [finished(5), finished(1440)] });
});

test("only plain GitHub HTTPS links are clickable", () => {
    assert.equal(safeGitHubUrl("https://github.com/org/repo/pull/1"), "https://github.com/org/repo/pull/1");
    for (const url of ["https://github.com.evil.example", "javascript:void(0)", "http://github.com", "https://u@github.com"]) {
        assert.equal(safeGitHubUrl(url), null);
    }
});

test("canvas serves an instance-scoped read-only page", async t => {
    const { server, url } = await startServer();
    t.after(() => server.close());
    const page = await fetch(url);
    assert.equal(page.status, 200);
    assert.match(await page.text(), /Operator dashboard/);
    assert.match(page.headers.get("content-security-policy"), /connect-src 'self'/);
    assert.equal((await fetch(new URL("dashboard.mjs", url))).status, 200);
    assert.equal((await fetch(new URL("/data", url))).status, 404);
    assert.equal((await fetch(new URL("data", url), { method: "POST" })).status, 404);
});
