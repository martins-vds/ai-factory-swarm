export function ageMinutes(value, now) {
    return (now - Date.parse(value)) / 60_000;
}

export function classify(row, now) {
    const elapsed = ageMinutes(row.started_at, now);
    if (row.status === "starting") return elapsed >= 15 ? "no PR" : "starting";
    if (row.status === "finished") return "finished";
    if (elapsed > 60 && ageMinutes(row.last_commit_at ?? row.started_at, now) >= 10) return "over limit";
    if (elapsed >= 50) return "near limit";
    return "running";
}

export function splitSessions(rows, now) {
    return {
        active: rows.filter(row => row.status !== "finished"),
        finished: rows.filter(row => row.status === "finished" && ageMinutes(row.finished_at, now) <= 1440)
            .sort((a, b) => Date.parse(b.finished_at) - Date.parse(a.finished_at)),
    };
}

export function approvalKey(row) {
    return row.branch ? `${row.repo}:${row.branch}` : row.id;
}

export function safeGitHubUrl(value) {
    try {
        const url = new URL(value);
        return url.origin === "https://github.com" && !url.username && !url.password ? url.href : null;
    } catch {
        return null;
    }
}
