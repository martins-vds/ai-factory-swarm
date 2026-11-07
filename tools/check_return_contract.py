#!/usr/bin/env python3
"""Fail an agent PR that does not commit its return file (harness rule, migration contract).

Usage (in CI, on pull_request events, with full history):
  python .migration/harness/tools/check_return_contract.py --base origin/<base branch>
                                                           [--event $GITHUB_EVENT_PATH]

Applies to agent PRs only: head branch `copilot/…` or a bot/Copilot author. Others pass untouched.
An agent PR must add or update at least one `.migration/returns/<ticket>.<role>.yaml` (diff against
--base). When the PR body says `Fixes #N` / `Closes #N` / `Resolves #N`, one of those files must have
`issue: <owner>/<repo>#N`, or name the ticket #N is a sub-issue of (a Verifier's or a fix's own issue). The file's content is validated against schemas/return.schema.json by
`validate.py` in the same workflow. If a later run supersedes that return, a schema-valid committed
version in this PR's history may establish attribution for the same ticket/role and this exact PR.
That proves attribution only, not a passing verdict. A return contract pasted into the PR description (instead of
linked) produces a warning, not a failure, because later sessions cannot edit the description. For
finished PR-bearing returns changed against this PR's base, this event check also requires `pr:` to
identify this PR unless first-parent merge history proves the file was inherited unchanged. Superseded
attribution applies only to the same return path. Neither check proves worker completion or merge
authorization.
Needs git, PyYAML and jsonschema.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

import yaml
from jsonschema import Draft202012Validator

AGENT_AUTHORS = {"Copilot", "copilot-swe-agent[bot]", "copilot-swe-agent"}
CLOSES = re.compile(r"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s+#(\d+)")
PR_REFERENCE = re.compile(
    r"^(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<ref>[1-9][0-9]*)|"
    r"https?://(?P<host>[^/\s?#]+)/(?P<url_repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/"
    r"(?P<url_ref>[1-9][0-9]*)/?)$")


def is_agent_pr(pr):
    author = (pr.get("user") or {}).get("login", "")
    return pr["head"]["ref"].startswith("copilot/") or author in AGENT_AUTHORS or author.endswith("[bot]")


def pasted_contract(body):
    """True if the PR body pastes a return file (a yaml block with role/ticket/issue) instead of linking it."""
    for block in re.findall(r"```ya?ml\s*\n(.*?)```", body or "", re.S):
        try:
            doc = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and "ticket" in doc and ("role" in doc or "gates" in doc):
            return True
    return False


def changed_return_files(base, root=".", head="HEAD"):
    out = subprocess.run(["git", "-C", root, "diff", "--name-only", "--diff-filter=AM", f"{base}...{head}", "--",
                          ".migration/returns/"], capture_output=True, text=True, check=True).stdout
    return [p for p in out.split() if re.search(r"\.ya?ml$", p)]


def pr_identity(value):
    """Return a normalized repository/number pair for a PR reference, without network lookup."""
    if not isinstance(value, str):
        return None
    match = PR_REFERENCE.fullmatch(value)
    if not match:
        return None
    return ((match.group("repo") or match.group("url_repo")).lower(),
            int(match.group("ref") or match.group("url_ref")),
            match.group("host").lower() if match.group("host") else None)


def identifies_same_pr(actual, expected):
    return (actual is not None and expected is not None and actual[:2] == expected[:2] and
            (actual[2] is None or actual[2] == expected[2]))


def inherited_from_merge(base, path, root=".", head="HEAD"):
    """Whether an unchanged return arrived on a merged side branch, not this PR's first-parent work."""
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    merges = git("rev-list", "--first-parent", "--merges", f"{base}..{head}")
    if merges is None:
        return False
    for merge in merges.splitlines():
        parents = (git("rev-list", "--parents", "-n", "1", merge) or "").split()
        if len(parents) != 3:
            continue
        _, first_parent, second_parent = parents
        merge_blob = git("rev-parse", "--verify", f"{merge}:{path}")
        first_blob = git("rev-parse", "--verify", f"{first_parent}:{path}")
        second_blob = git("rev-parse", "--verify", f"{second_parent}:{path}")
        if not merge_blob or not second_blob or merge_blob != second_blob or merge_blob == first_blob:
            continue
        later_changes = git("log", "--first-parent", "--format=%H", f"{merge}..{head}", "--", path)
        if later_changes == "":
            return True
    return False


def roles_with_pr():
    schema = pathlib.Path(__file__).resolve().parent.parent / "schemas/return.schema.json"
    doc = json.loads(schema.read_text(encoding="utf-8"))
    return {
        clause["if"]["properties"]["role"]["const"]
        for clause in doc.get("allOf", [])
        if "pr" in clause.get("then", {}).get("required", [])
    }


def github_parent(number):
    """The parent ticket of a sub-issue (a Verifier's or a fix's own issue), via the REST API in CI; else None."""
    import urllib.request
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not repo or not token:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues/{number}",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            url = json.load(r).get("parent_issue_url") or ""
    except (OSError, ValueError):
        return None
    m = re.search(r"/issues/(\d+)$", url)
    return m.group(1) if m else None


def superseded_attribution(base, current, accepted, pr_url, root, head="HEAD"):
    """Find this PR's own valid return before a later run replaced its attribution."""
    identity = re.fullmatch(r"https?://[^/]+/([^/]+/[^/]+)/pull/(\d+)", pr_url.rstrip("/"))
    if not identity:
        return None, ["the event has no canonical PR URL"]
    repo, number = identity.groups()
    pr_refs = {pr_url.rstrip("/"), f"{repo}#{number}"}
    issues = {f"{repo}#{n}" for n in accepted}
    schema = pathlib.Path(__file__).resolve().parent.parent / "schemas/return.schema.json"
    validator = Draft202012Validator(json.loads(schema.read_text(encoding="utf-8")))
    rejected = []
    for path, latest in current.items():
        if not validator.is_valid(latest):
            rejected.append(f"{path}: current return is not schema-valid")
            continue
        commits = subprocess.run(
            ["git", "-C", str(root), "log", "--format=%H", "--no-merges", "--diff-filter=AM",
             f"{base}..{head}", "--", path], capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        for commit in commits:
            text = subprocess.run(
                ["git", "-C", str(root), "show", f"{commit}:{path}"],
                capture_output=True, text=True, check=True,
            ).stdout
            try:
                previous = yaml.safe_load(text)
            except yaml.YAMLError:
                rejected.append(f"{path}@{commit}: invalid YAML")
                continue
            if not isinstance(previous, dict):
                continue
            if not isinstance(previous.get("issue"), str) or not isinstance(previous.get("pr"), str):
                continue
            if previous.get("issue") not in issues or previous.get("pr") not in pr_refs:
                continue
            if any(previous.get(k) != latest.get(k) for k in ("ticket", "role")):
                rejected.append(f"{path}@{commit}: ticket/role differs from current return")
                continue
            expected_name = f"{previous.get('ticket')}.{previous.get('role')}.yaml"
            if pathlib.Path(path).name != expected_name or not validator.is_valid(previous):
                rejected.append(f"{path}@{commit}: historical return is not schema-valid or misnamed")
                continue
            return (f"{path}@{commit} (issue: {previous['issue']}, pr: {previous['pr']})"), rejected
    return None, rejected


def check(body, files, root=".", parent_of=lambda n: None, *, base=None, head="HEAD", pr_url=None):
    if not files:
        return False, ("no return file in this PR: commit .migration/returns/<ticket>.<role>.yaml "
                       "(your agent's return contract plus role, ticket, issue)")
    issues = set(CLOSES.findall(body or ""))
    found = set()
    current = {}
    for f in files:
        try:
            if head == "HEAD":
                text = pathlib.Path(root, f).read_text(encoding="utf-8")
            else:
                text = subprocess.run(
                    ["git", "-C", str(root), "show", f"{head}:{f}"],
                    capture_output=True, text=True, check=True,
                ).stdout
            doc = yaml.safe_load(text) or {}
        except (OSError, yaml.YAMLError, subprocess.CalledProcessError):
            continue
        if not isinstance(doc, dict):
            continue
        current[f] = doc
        m = re.search(r"#(\d+)$", str(doc.get("issue") or ""))
        if m:
            found.add(m.group(1))
    accepted = set()
    if issues:
        # A Verifier or a fix runs on its own issue, a sub-issue of the ticket (agents/README.md): its PR closes
        # that issue while the return file names the ticket. Either counts.
        accepted = issues | {p for p in (parent_of(n) for n in issues) if p}
    mismatches = []
    rejected_identity = []
    if pr_url:
        expected = pr_identity(pr_url)
        pr_roles = roles_with_pr()
        for path, doc in current.items():
            if (doc.get("role") not in pr_roles or
                    doc.get("handoff") not in (None, "", "none")):
                continue
            if not identifies_same_pr(pr_identity(doc.get("pr")), expected):
                proof = None
                if base and accepted:
                    proof, rejected = superseded_attribution(base, {path: doc}, accepted, pr_url, root, head)
                    rejected_identity.extend(rejected)
                inherited = bool(base and inherited_from_merge(base, path, root, head))
                if proof or inherited:
                    continue
                mismatches.append(f"{path} has pr: {doc.get('pr')!r}")
    if issues and not accepted & found:
        rejected = []
        if base and pr_url:
            for path, doc in current.items():
                proof, rejected = superseded_attribution(base, {path: doc}, accepted, pr_url, root, head)
                if proof and not mismatches:
                    return True, (f"return file(s): {', '.join(files)}; superseded attribution: {proof}. "
                                  "Historical attribution is not a passing verdict; current gates still apply.")
        return False, (f"the PR closes #{', #'.join(sorted(issues))} but no changed return file has a "
                       f"matching `issue:` (the issue, or the ticket it is a sub-issue of; files: "
                       f"{', '.join(files)})"
                       + (f"; rejected historical evidence: {'; '.join(rejected or rejected_identity)}"
                          if rejected or rejected_identity else ""))
    if mismatches:
        rejected = "; ".join(rejected_identity)
        return False, (f"completed return(s) changed by this PR must identify this PR ({pr_url}); "
                       f"update {'; '.join(mismatches)}"
                       + (f"; rejected historical evidence: {rejected}" if rejected else ""))
    return True, f"return file(s): {', '.join(files)}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="e.g. origin/main")
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_PATH"))
    a = ap.parse_args()
    if not a.event or not pathlib.Path(a.event).exists():
        print("no event payload; nothing to check")
        return 0
    pr = json.loads(pathlib.Path(a.event).read_text(encoding="utf-8")).get("pull_request")
    if not pr:
        print("not a pull request event; nothing to check")
        return 0
    if not is_agent_pr(pr):
        print(f"not an agent PR ({pr['head']['ref']}); skipped")
        return 0
    head = (pr.get("head") or {}).get("sha")
    base = (pr.get("base") or {}).get("sha")
    if not head or not base:
        print("::error title=Return ownership context missing::PR event must include head.sha and base.sha; "
              "cannot establish changed return ownership.")
        return 1
    for label, revision in (("head", head), ("base", base)):
        exists = subprocess.run(
            ["git", "-C", ".", "cat-file", "-e", f"{revision}^{{commit}}"],
            capture_output=True,
        )
        if exists.returncode:
            print(f"::error title=Return ownership context unavailable::Event {label} commit {revision} "
                  "is not available locally; fetch full PR history and retry.")
            return 1
    configured_base = subprocess.run(
        ["git", "-C", ".", "rev-parse", "--verify", f"{a.base}^{{commit}}"],
        capture_output=True, text=True,
    )
    current = configured_base.stdout.strip() if not configured_base.returncode else ""
    # The event's base.sha is the base as of the PR's last event; the base branch may have moved on since
    # (pilot #243, #229, #260: every merge to main made open PRs fail here). Moving forward is fine: the
    # diff is taken from the merge base. Only a base the event's commit isn't part of is inconsistent.
    advanced = bool(current) and current != base and subprocess.run(
        ["git", "-C", ".", "merge-base", "--is-ancestor", base, current], capture_output=True).returncode == 0
    if not current or (current != base and not advanced):
        print(f"::error title=Return ownership context inconsistent::Configured --base {a.base!r} does not "
              f"resolve to event base.sha {base} or a commit after it; refresh the event/base checkout and retry.")
        return 1
    if advanced:
        print(f"base moved on since the PR's last event ({base[:7]} → {current[:7]}); comparing from the merge base")
        base = current
    files = changed_return_files(base, head=head)
    ok, msg = check(pr.get("body") or "", files, parent_of=github_parent,
                    base=base, head=head, pr_url=pr.get("html_url"))
    if pasted_contract(pr.get("body") or ""):
        # A warning, not a failure: a follow-up session cannot edit the description to fix it.
        print("::warning title=Return contract pasted into the PR description::Link to "
              ".migration/returns/<ticket>.<role>.yaml instead of pasting it; the pasted copy goes stale when "
              "the file changes.")
    if ok:
        print(msg)
        return 0
    print(f"::error title=Return contract invalid::{msg}. See afs-migration-contract → Return files.")
    return 1


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
