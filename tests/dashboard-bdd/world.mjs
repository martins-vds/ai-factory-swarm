import { execFile } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const root = fileURLToPath(new URL("../../", import.meta.url));
const fakeGh = fileURLToPath(new URL("fake-gh.py", import.meta.url));
const exec = promisify(execFile);
export const repos = ["ai-factory-pilot-target", "ai-factory-synthetic-target", "ai-factory-eval", "ai-factory-swarm"];
export const evalRepo = "ai-factory-eval";
export const base = "eval/2026-11-18-4ra-r1/synthetic-ll-02";
export const bot = { login: "Copilot" };
export const snapshotFiles = ["needs.json", "sessions.json", "trend.json", "trend-cases.json", "trend-coverage.json"];
export const list = text => text.split(/,\s*/);
export const github = (repo, path) => `https://github.com/martins-vds/${repo}/${path}`;

export class DashboardWorld {
    async init() {
        this.dir = await mkdtemp(join(tmpdir(), "afs-dashboard-bdd-"));
        this.now = Math.floor(Date.now() / 1000) * 1000;
        this.fixture = { repos: {} };
        this.results = join(this.dir, "evals/results");
        this.cases = join(this.dir, "evals/cases");
        this.returns = join(this.dir, "target/.migration/returns");
        this.snapshots = join(this.dir, "snapshots");
        this.bin = join(this.dir, "bin");
        const tools = join(this.dir, "tools");
        await Promise.all([this.results, this.cases, this.returns, this.snapshots, this.bin, tools]
            .map(path => mkdir(path, { recursive: true })));
        await copyFile(fakeGh, join(this.bin, "gh"));
        await writeFile(join(tools, "check_plan.py"), "FOLDED_INTO = {}\n");
        this.env = {
            PATH: `${this.bin}:${process.env.PATH}`,
            GH_TOKEN: "bdd-viewer-credential",
            DASHBOARD_GH_FIXTURE: join(this.dir, "github.json"),
            DASHBOARD_GH_LOG: join(this.dir, "github.log"),
        };
        this.commands = {};
        this.network = [];
    }

    ago(minutes) { return new Date(this.now - minutes * 60_000).toISOString(); }
    data(repo = evalRepo) {
        return this.fixture.repos[repo] ??= { pulls: [], issues: [], runs: [], files: {}, contents: {}, timeline: {}, commits: {} };
    }

    pull(repo, n, { title = `PR #${n}`, draft = false, age = 30, branch = `copilot/pr-${n}`, author = { login: "viewer" }, baseRef = "main" } = {}) {
        const row = { number: n, title, draft, state: "open", html_url: github(repo, `pull/${n}`), user: author,
            created_at: this.ago(age), updated_at: this.ago(0), head: { ref: branch, sha: `sha${n}` }, base: { ref: baseRef } };
        this.data(repo).pulls.push(row);
        this.data(repo).commits[row.head.sha] = this.ago(30);
        this.lastPull = { repo, row };
        return row;
    }

    issue(n, age, pr) {
        this.data().issues.push({ number: n, state: "open", assignees: [bot], updated_at: this.ago(0),
            title: "Migrate LL-02", body: "**Role:** `afs-migrator`", html_url: github(evalRepo, `issues/${n}`) });
        this.data().timeline[n] = [{ event: "assigned", assignee: bot, created_at: this.ago(age) }];
        if (pr) this.data().timeline[n].push({ event: "cross-referenced", source: { issue: {
            ...pr, repository_url: `https://api.github.com/repos/martins-vds/${evalRepo}`, pull_request: {},
        } } });
        this.lastIssue = n;
    }

    async writeFixture() {
        await writeFile(this.env.DASHBOARD_GH_FIXTURE, JSON.stringify(this.fixture));
    }

    async generate(dataset) {
        await this.writeFixture();
        const out = join(this.snapshots, `${dataset}.json`);
        const args = dataset === "trend"
            ? ["--eval-root", this.dir, ...(this.withCoverage ? ["--target", join(this.dir, "target")] : [])]
            : repos.flatMap(repo => ["--repo", `martins-vds/${repo}`]);
        const argv = [dataset, ...args, "--out", out];
        this.commands[dataset] = ["tools/afs-dashboard", ...argv].join(" ");
        await exec("python3", ["tools/afs-dashboard", ...argv], { cwd: root, env: { ...process.env, ...this.env } });
    }

    async generatedTimes(minutes) {
        for (const name of snapshotFiles) {
            const file = join(this.snapshots, name);
            let doc = { rows: [], meta: [{ label: "Generated" }] };
            if (this.generatedAll) doc = JSON.parse(await readFile(file, "utf8"));
            doc.meta.find(item => item.label === "Generated").value = this.ago(minutes);
            await writeFile(file, JSON.stringify(doc));
        }
        this.generatedAll = true;
    }

    async graded(family, date, cases, count, state = false) {
        for (let i = 0; i < count; i++) {
            const rows = {};
            for (const { case: id, outcomes, minutes } of cases) {
                const outcome = list(outcomes)[i];
                if (outcome) rows[id] = { passed: outcome === "pass", ...(minutes ? { usage: { minutes: Number(minutes) } } : {}) };
            }
            await writeFile(join(this.results, `${date}-${family}-r${i + 1}.json`), JSON.stringify({ cases: rows }));
        }
        if (state) await writeFile(join(this.results, `${date}-${family}-r1.state.json`), "not a graded result");
    }

    async requestLog() {
        return (await readFile(this.env.DASHBOARD_GH_LOG, "utf8")).trim().split("\n").map(line => JSON.parse(line));
    }
}
