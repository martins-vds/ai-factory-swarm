import assert from "node:assert/strict";
import { rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import {
    After, AfterAll, Before, BeforeAll, Given, Then, When, setDefaultTimeout, setWorldConstructor,
} from "@cucumber/cucumber";
import { chromium } from "playwright";
import { startServer } from "../../.github/extensions/operator-dashboard/server.mjs";
import { DashboardWorld, base, bot, evalRepo, github, list, repos } from "./world.mjs";

setDefaultTimeout(20_000);
setWorldConstructor(DashboardWorld);
let browser;
BeforeAll(async () => { browser = await chromium.launch(); });
AfterAll(async () => { await browser?.close(); });
Before(async function () { await this.init(); });
After(async function () {
    await this.page?.context().close();
    if (this.server) await new Promise(resolve => this.server.server.close(resolve));
    for (const [key, value] of Object.entries(this.originalEnv ?? {})) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
    }
    if (this.dir) await rm(this.dir, { recursive: true, force: true });
});

async function open(world, includeLive = false) {
    world.server = await startServer({ snapshotDir: world.snapshots, includeLive });
    world.page = await browser.newPage();
    world.page.on("request", r => world.network.push({ url: r.url(), method: r.method() }));
    await world.page.clock.install({ time: world.now + 1000 });
    await world.page.clock.setFixedTime(world.now);
    const data = world.page.waitForResponse(r => r.url() === `${world.server.url}data`);
    await world.page.goto(world.server.url);
    await data;
    await world.page.waitForFunction(() => document.querySelector("#connection").textContent === "");
}

async function nextPoll(world) {
    const data = world.page.waitForResponse(r => r.url() === `${world.server.url}data`);
    await world.page.clock.runFor(15_100);
    await data;
}

const isGenerated = async server => {
    const stop = Date.now() + 10_000;
    while (Date.now() < stop) {
        const status = (await server.status()).sessions;
        if (status.error) throw new Error(status.error);
        if (status.rows !== null) return;
        await sleep(25);
    }
    throw new Error("Live session generator did not publish data");
};

When("I open the dashboard", async function () { await open(this); });
When("I generate {string} and open the dashboard", async function (name) {
    await this.generate(name);
    await open(this);
});
When("I generate {string} and {string} and open the dashboard", async function (one, two) {
    await this.generate(one);
    await this.generate(two);
    await open(this);
});
When("I regenerate {string} and wait for the next poll", async function (name) {
    await this.generate(name);
    await nextPoll(this);
});
When("I wait for the next poll", async function () { await nextPoll(this); });
When("the dashboard polls GitHub through the local generator", async function () {
    await this.writeFixture();
    this.originalEnv = Object.fromEntries(Object.keys(this.env).map(key => [key, process.env[key]]));
    Object.assign(process.env, this.env);
    await open(this, true);
    await isGenerated(this.server);
    await nextPoll(this);
});

Then("{string} says {string}", async function (id, message) {
    await this.page.locator(id === "chart" ? "#chart .chart-info" : `#${id}`)
        .getByText(message, { exact: true }).first().waitFor({ timeout: 5000 });
});

const tables = { family: "families-data", case: "cases-data", history: "history", coverage: "coverage-data",
    "active sessions": "active", "finished sessions": "finished", "run summary": "session-groups",
    health: "health-data", "health ticket": "health-tickets" };
Then(/^the (family|case|history|coverage|active sessions|finished sessions|run summary|health|health ticket) table contains exactly:$/, async function (name, data) {
    const region = this.page.locator(`#${tables[name]}`);
    const headings = data.raw()[0];
    const expected = data.rows();
    await region.locator("tbody tr").first().waitFor();
    const tableRows = async () => region.evaluate((node, names) => [...node.querySelectorAll("table")].flatMap(table => {
        const labels = [...table.querySelectorAll("th")].map(th => th.textContent);
        return [...table.tBodies[0].rows].map(row => names.map(label =>
            row.cells[labels.indexOf(label)]?.innerText.trim().replace(/\s+/g, " ")));
    }), headings);
    let actual;
    const deadline = Date.now() + 2000;
    do {
        actual = await tableRows();
        if (JSON.stringify(actual) === JSON.stringify(expected)) break;
        await sleep(25);
    } while (Date.now() < deadline);
    assert.deepEqual(actual, expected);
});

Given("{int} workflow runs on {string} in {string} have waited {int}, {int} and {int} days", function (count, branch, repo, a, b, c) {
    const days = [a, b, c];
    assert.equal(count, days.length);
    this.branch = { repo, branch };
    this.data(repo).runs = days.map(n => ({ head_branch: branch, created_at: this.ago(n * 1440), pull_requests: [] }));
});
Given(/^the branch has (a PR|no PR)$/, function (attachment) {
    if (attachment === "a PR") this.pull(this.branch.repo, 42, { branch: this.branch.branch, draft: true });
});
Given(/^"([^"]+)" has an open (ready|draft) PR (\d+)$/, function (repo, state, number) {
    this.pull(repo, Number(number), { draft: state === "draft" });
});
Given("its changed {string} at the PR head says {string}", function (suffix, content) {
    const { repo, row } = this.lastPull;
    const filename = `LL-02${suffix}`;
    this.data(repo).files[row.number] = [{ filename, status: "added" }];
    this.data(repo).contents[`${row.head.sha}:${filename}`] = content;
});
Given("ready PRs have these waiting ages:", function (rows) {
    for (const item of rows.hashes()) this.pull("ai-factory-swarm", Number(item.PR), { age: Number(item.days) * 1440 });
});
Then("Needs shows one {string} row titled {string}", async function (kind, title) {
    const rows = this.page.locator("#needs-data tbody tr").filter({ hasText: kind });
    await rows.first().waitFor();
    assert.equal(await rows.count(), 1);
    await rows.getByRole("link", { name: title, exact: true }).waitFor();
    this.needsRow = rows.first();
});
Then("the row links to {string}", async function (url) {
    assert.equal(await this.needsRow.getByRole("link").getAttribute("href"), url);
});
Then("the row shows {string} and links to {string}", async function (age, url) {
    assert.equal(await this.needsRow.getByRole("link").getAttribute("href"), url);
    await this.needsRow.getByText(age, { exact: true }).waitFor();
});
Then("Needs has no {string} rows", async function (kind) {
    await this.page.locator("#needs-meta time").waitFor();
    assert.equal(await this.page.locator("#needs-data tbody tr").filter({ hasText: kind }).count(), 0);
});
Then("Needs shows the items in order {string}", async function (items) {
    await this.page.locator("#needs-data tbody tr").first().waitFor();
    assert.deepEqual(await this.page.locator("#needs-data tbody tr td:nth-child(3)").allTextContents(), list(items));
});
Then("their waiting times are {string}", async function (ages) {
    assert.deepEqual(await this.page.locator("#needs-data tbody tr td:nth-child(4)").allTextContents(), list(ages));
});

Given("the graded family {string} on {string} has {int} runs and a state file", async function (family, date, count) {
    await this.graded(family, date, [{ case: "a", outcomes: Array(count).fill("pass").join(",") }], count, true);
});
Given("these graded outcomes in {string} on {string}:", async function (family, date, data) {
    const rows = data.hashes();
    await this.graded(family, date, rows, Math.max(...rows.map(row => list(row.outcomes).length)));
});
Then("the trend chart plots {string} in that order", async function (families) {
    await this.page.locator("#chart circle").first().waitFor();
    assert.deepEqual(await this.page.locator("#chart circle").evaluateAll(points =>
        points.map(pt => pt.getAttribute("aria-label").split(" · ")[0])), list(families));
});
When("I hover the {string} point", async function (family) {
    await this.page.locator(`#chart circle[aria-label^="${family} ·"]`).hover();
});
When("I select family {string} on {string}", async function (family, date) {
    await this.page.locator("#family").selectOption(`${date}/${family}`);
});
When("I filter by kind {string} and majority {string}", async function (kind, passed) {
    await this.page.locator("#kind").selectOption(kind);
    await this.page.locator("#passed").selectOption(passed);
});
When("I select case {string}", async function (name) {
    await this.page.locator("#case-id").selectOption(name);
});
Given("returns use roles {string}", async function (roles) {
    this.withCoverage = true;
    await Promise.all(list(roles).map((role, i) => writeFile(join(this.returns, `T-${i}.${role}.yaml`), "{}")));
});
Given("the eval catalog covers {string}", async function (roles) {
    await Promise.all(list(roles).map(role => writeFile(join(this.cases, `${role}.yaml`), `role: ${role}\n`)));
});
Given("the harness records {string} as folded into {string}", async function (from, to) {
    await writeFile(join(this.dir, "tools/check_plan.py"), `FOLDED_INTO = ${JSON.stringify({ [from]: to })}\n`);
});

Given("eval issue {int} is assigned to Copilot and has WIP PR {int} started {int} minutes ago", function (issue, number, age) {
    const pr = this.pull(evalRepo, number, { title: "[WIP] Migrate LL-02", draft: true, age, author: bot, baseRef: base });
    this.issue(issue, age + 1, pr);
});
Given("eval issue {int} was assigned to Copilot {int} minutes ago with no PR", function (issue, age) {
    this.issue(issue, age);
});
Given("the PR head commit is {int} minutes old", function (age) {
    this.data().commits[this.lastPull.row.head.sha] = this.ago(age);
});
Given("its first assignment was {int} minutes ago", function (age) {
    this.data().timeline[this.lastIssue][0].created_at = this.ago(age);
});
When("Copilot is reassigned {int} minutes ago", function (age) {
    this.data().timeline[this.lastIssue].push({ event: "assigned", assignee: bot, created_at: this.ago(age) });
});
When("PR {int} dropped {string} {int} minutes ago", function (number, prefix, age) {
    const pr = this.data().pulls.find(p => p.number === number);
    const original = pr.title;
    assert.ok(original.startsWith(prefix));
    pr.title = original.slice(prefix.length).trim();
    this.data().timeline[number] = [{ event: "renamed", created_at: this.ago(age), rename: { from: original, to: pr.title } }];
});
Given("its workflow runs need approval", function () {
    const pr = this.lastPull.row;
    this.data().runs.push({ head_branch: pr.head.ref, created_at: this.ago(5), pull_requests: [{ number: pr.number }] });
});
Then("PR {int} links to {string}", async function (number, url) {
    assert.equal(await this.page.locator("#active").getByRole("link", { name: `#${number}` }).getAttribute("href"), url);
});
Then("there is no PR link in the active sessions table", async function () {
    assert.equal(await this.page.locator("#active tbody td:nth-child(3) a").count(), 0);
});
When("I group sessions by run", async function () { await this.page.getByLabel("Group by eval run").check(); });
When("I follow the session's {string} link", async function (label) {
    await this.page.locator("#active").getByRole("link", { name: label }).click();
});
Then("the targeted Needs row shows {string} for PR {int}", async function (label, pr) {
    const row = this.page.locator("#needs-data tbody tr:target");
    await row.getByText(label, { exact: true }).waitFor();
    assert.match(await row.getByRole("link").getAttribute("href"), new RegExp(`/pull/${pr}$`));
});
Then("the header shows {int} active, {int} near limit and {int} stalled", async function (active, near, stalled) {
    await this.page.locator("#summary strong").first().waitFor();
    assert.deepEqual(await this.page.locator("#summary strong").allTextContents(), [active, near, stalled].map(String));
});

Given("the runner is signed in to the GitHub CLI", function () {
    assert.ok(this.env.GH_TOKEN);
});
When("I generate {string}, {string} and {string}", async function (one, two, three) {
    for (const name of [one, two, three]) await this.generate(name);
});
Then("the GitHub reads used the runner's credentials", async function () {
    const log = await this.requestLog();
    for (const repo of repos) {
        assert.ok(log.some(record => record.endpoint.startsWith(`repos/martins-vds/${repo}/issues?`)));
        assert.ok(log.some(record => record.endpoint.startsWith(`repos/martins-vds/${repo}/pulls?`)));
    }
    assert.ok(log.every(record => record.authenticated && record.method === "GET"));
});
When("the runner cannot read {string}", function (repo) { this.fixture.denied = repo; });
Then("{string} and {string} generation fail with that repository's gh error", async function (one, two) {
    for (const name of [one, two]) {
        await assert.rejects(this.generate(name), error =>
            error.stderr.includes(`repos/martins-vds/${this.fixture.denied}/`) && error.stderr.includes("gh: Not Found (HTTP 404)"));
    }
});
Given("all five datasets were generated {int} minutes ago", async function (minutes) {
    await this.generatedTimes(minutes);
});
Then("every dataset shows its Generated time and no stale datasets", async function () {
    const times = this.page.locator(".meta time");
    assert.deepEqual(await times.evaluateAll(nodes => nodes.map(n => n.dateTime)), Array(5).fill(this.ago(4)));
    assert.equal(await this.page.getByText("Stale", { exact: true }).count(), 0);
});
Then("only {string} is stale", async function (names) {
    await this.page.locator("#sessions-meta").getByText("Stale", { exact: true }).waitFor();
    const ids = await this.page.getByText("Stale", { exact: true }).evaluateAll(nodes =>
        nodes.map(n => n.closest("[id]").id.replace(/-meta$/, "")));
    assert.deepEqual(ids, list(names));
});
When("I open the {string} generator details", async function (name) {
    this.details = this.page.locator(`#${name}-meta details`);
    await this.details.locator("summary").click();
});
Then("the details show the generator source and the command that actually ran", async function () {
    assert.equal(await this.details.getAttribute("open"), "");
    const [source, command] = await this.details.locator("pre").allTextContents();
    assert.match(source, /def needs\(repos\):/);
    assert.equal(command, this.commands.needs);
});
Then("the canvas has no GitHub write controls or endpoints", async function () {
    assert.equal(await this.page.locator("button, [role=button], form, input:not([type=checkbox])").count(), 0);
    const links = await this.page.locator("tbody a").evaluateAll(nodes => nodes.map(a => a.getAttribute("href")));
    assert.ok(links.length);
    assert.ok(links.every(url => url.startsWith("#") || new URL(url).origin === "https://github.com"));
    assert.ok(this.network.every(r => r.method === "GET" && r.url.startsWith(this.server.url)));
    const writes = await this.page.request.post(`${this.server.url}data`, { data: { human_check: "passed" } });
    assert.equal(writes.status(), 404);
});

Given("slice {string} finished ticket {string} with mutation {float}, CRAP {int}, tests {float}s and {int} flaky run(s)",
    async function (slice, id, mutation, crap, seconds, flaky) {
        await this.ticket(slice, id, { mutation, crap, seconds, flaky });
    });
When("I show slice {string}", async function (slice) {
    await this.page.getByLabel("Slice").selectOption({ label: `target/${slice}` });
});
