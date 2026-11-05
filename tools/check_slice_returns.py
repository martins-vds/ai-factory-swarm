#!/usr/bin/env python3
"""A slice epic closes only when every ticket under it is closed and left its return file (ADR-0024).

The return-contract check (check_return_contract.py) runs on agent pull requests, so work done without a PR
(an agent run locally, a ticket finished by hand) is never checked. The slice epic is where all of a
slice's tickets meet, so this check runs when the epic closes:

  * every in-scope descendant of the epic is closed (an open ticket means the slice isn't done);
  * every in-scope descendant closed as completed has a return file, `.migration/returns/<ticket>.<role>.yaml` with
    `issue: <owner>/<repo>#<n>`. A ticket closed as "not planned" needs none.

Tickets closed before this tool was first committed to the repo are exempt (the rule didn't exist yet);
the date comes from git history, so no list can be edited by hand.
If a later valid same-ticket/same-role return supersedes an issue, a schema-valid predecessor reachable
from HEAD may establish attribution only, never a passing verdict. A parent-ticket return can also cover a
child only when GitHub confirms the direct parent, the owning PR closes that child and contains the exact
return, and the current role outcome passes. Required history must be complete.

  check_slice_returns.py --repo owner/repo --epic 9 [--reopen]   (the AFS map fog workflow runs this)

With --reopen, a failing epic is reopened with a comment that lists what is missing. Exit 1 on failure,
0 otherwise (also when the issue is not a slice epic). Uses `gh api` and git; needs PyYAML and jsonschema.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

import yaml
from jsonschema import Draft202012Validator

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True       # installed harness files are drift-checked (check_installed.py)
sys.path.insert(0, str(HERE))
import fog_rewalk  # noqa: E402
from ticket_guard import descendants  # noqa: E402

SELF = ".migration/harness/tools/check_slice_returns.py"
VALIDATOR = Draft202012Validator(json.loads((HERE.parent / "schemas/return.schema.json").read_text(encoding="utf-8")))


def valid_return(text, path):
    """Schema-valid return with canonical issue and ticket/role/filename identity."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict) or not VALIDATOR.is_valid(doc):
        return None
    issue = doc.get("issue")
    if not isinstance(issue, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*", issue):
        return None
    return doc if pathlib.Path(path).name == f"{doc['ticket']}.{doc['role']}.yaml" else None


def current_returns(returns_dir=".migration/returns"):
    out = {}
    for p in sorted(pathlib.Path(returns_dir).glob("*.y*ml")):
        try:
            doc = valid_return(p.read_text(encoding="utf-8"), p)
        except (OSError, UnicodeError):
            continue
        if doc:
            out[p] = doc
    return out


def returned_issues(returns_dir=".migration/returns"):
    """Canonical issues of valid current return files."""
    return {doc["issue"] for doc in current_returns(returns_dir).values()}


def superseded_attribution(required, current, repo=None):
    """Attribute missing issues using only complete HEAD ancestry and valid, still-present returns."""
    if not required:
        return set(), []

    def git(*args):
        return subprocess.run(["git", "--no-replace-objects", *args],
                              capture_output=True, text=True, check=True).stdout

    if git("rev-parse", "--is-shallow-repository").strip() != "false":
        raise ValueError("shallow repository")
    root = pathlib.Path(git("rev-parse", "--show-toplevel").strip())
    git("rev-parse", "--verify", "HEAD")
    found, diagnostics = set(), []
    parent_numbers = {}
    if repo:
        from ticket_guard import _parent_issue_number

        for issue in sorted(required):
            child_repo, child_number = issue.rsplit("#", 1)
            if child_repo.lower() != repo.lower():
                continue
            try:
                parent_numbers[issue] = _parent_issue_number(repo, int(child_number))
            except (OSError, ValueError, subprocess.SubprocessError, SystemExit):
                parent_numbers[issue] = "unavailable"
                diagnostics.append(f"parent-ticket continuation for {issue} blocked: "
                                   "GitHub parent relationship could not be verified")
    for path, latest in current.items():
        path = path.resolve().relative_to(root).as_posix()
        if not git("ls-tree", "HEAD", "--", path).strip():
            continue
        # A working-tree edit is not a committed superseding return.
        committed = git("show", f"HEAD:{path}")
        if valid_return(committed, path) != latest:
            continue
        candidates = {
            issue for issue in required - found
            if issue.rsplit("#", 1)[0] == latest["issue"].rsplit("#", 1)[0]
            and (not repo or parent_numbers.get(issue) is None)
        }
        if not candidates:
            continue
        # Full history includes merged worker branches, but never arbitrary refs or dangling objects.
        commits = git("log", "-m", "--full-history", "--format=%H", "--diff-filter=AM", "HEAD", "--", path).splitlines()
        for commit in commits:
            previous = valid_return(git("show", f"{commit}:{path}"), path)
            if not previous or previous["issue"] not in candidates:
                continue
            if any(previous[k] != latest[k] for k in ("ticket", "role")):
                continue
            found.add(previous["issue"])
            candidates.remove(previous["issue"])
            diagnostics.append(f"superseded attribution: {path}@{commit} (issue: {previous['issue']}). "
                               "Historical attribution is not a passing verdict; current acceptance gates still apply.")
            if not candidates:
                break
    if repo:
        from ticket_guard import _parent_ticket_attribution
        for path, latest in current.items():
            path = path.resolve().relative_to(root).as_posix()
            for issue in sorted(required - found):
                child_repo, child_number = issue.rsplit("#", 1)
                if child_repo.lower() != repo.lower():
                    continue
                attributed, relevant, proof = _parent_ticket_attribution(
                    repo, int(child_number), path, latest)
                if attributed:
                    found.add(issue)
                    diagnostics.append(f"parent-ticket continuation: {issue} is attributed to {path}: "
                                       + "; ".join(proof))
                elif relevant:
                    diagnostics.append(f"parent-ticket continuation for {issue} blocked: "
                                       + "; ".join(proof))
    return found, diagnostics


def rule_since(path=SELF):
    """ISO time the rule entered the repo: the commit that first added this tool (None outside git)."""
    shallow = subprocess.run(["git", "--no-replace-objects", "rev-parse", "--is-shallow-repository"],
                             capture_output=True, text=True)
    if shallow.returncode != 0 or shallow.stdout.strip() != "false":
        return None
    r = subprocess.run(["git", "--no-replace-objects", "log", "--diff-filter=A", "--format=%cI", "--", path],
                       capture_output=True, text=True)
    dates = r.stdout.split() if r.returncode == 0 else []
    return dates[-1] if dates else None


def utc(iso):
    import datetime
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)


def requires_return(s, since):
    return (s["state"] == "closed" and s.get("state_reason") == "completed"
            and not (since and s.get("closed_at") and utc(s["closed_at"]) < utc(since)))


def problems(repo, subs, returned, since):
    """What blocks closing the epic: open tickets, and completed tickets without a return file."""
    out = []
    for s in sorted(subs, key=lambda x: x["number"]):
        ref = f"#{s['number']} {s['title']}"
        if s["state"] != "closed":
            out.append(f"{ref}: still open")
        elif requires_return(s, since) and f"{repo}#{s['number']}" not in returned:
            out.append(f"{ref}: closed as completed, but no `.migration/returns/*.yaml` has "
                       f"`issue: {repo}#{s['number']}`")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--epic", type=int, required=True)
    ap.add_argument("--reopen", action="store_true", help="reopen a failing epic with a comment")
    a = ap.parse_args(argv)
    R = f"repos/{a.repo}"
    epic = fog_rewalk.gh(f"{R}/issues/{a.epic}")
    if not fog_rewalk.is_slice_epic(a.epic, [lbl["name"] for lbl in epic.get("labels", [])]):
        print(f"#{a.epic} is not a slice epic; nothing to check.")
        return 0
    subs = list(descendants(a.repo, a.epic, gh_func=fog_rewalk.gh).values())
    since = rule_since()
    current = current_returns()
    returned = {doc["issue"] for doc in current.values()}
    required = {f"{a.repo}#{s['number']}" for s in subs if requires_return(s, since)} - returned
    history_errors = []
    try:
        historical, diagnostics = superseded_attribution(required, current, a.repo)
        returned.update(historical)
        for diagnostic in diagnostics:
            print(diagnostic)
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as e:
        history_errors.append(f"return history unavailable: {e}; fetch complete HEAD ancestry and retry")
    found = problems(a.repo, subs, returned, since) + history_errors
    print(f"slice epic #{a.epic}: {len(subs)} ticket(s); rule since {since or 'unknown'}")
    for p in found:
        print(f"::error::{p}")
    print(f"AFS-RESULT gate=slice-returns epic={a.epic} verdict={'fail' if found else 'pass'} "
          f"tickets={len(subs)} failures={len(found)}")
    if found and a.reopen and epic.get("state") == "closed":
        body = ("**Reopened by the harness (ADR-0024):** a slice epic closes only when every ticket under it is "
                "closed and left its return file.\n\n" + "\n".join(f"- {p}" for p in found) +
                "\n\nFinish or close the open tickets; for each completed ticket, commit its return file "
                "(`afs-migration-contract` → Durable outputs). Then close this epic again.")
        fog_rewalk.gh(f"{R}/issues/{a.epic}/comments", "-X", "POST", data={"body": body})
        fog_rewalk.gh(f"{R}/issues/{a.epic}", "-X", "PATCH", data={"state": "open"})
        print(f"reopened #{a.epic}")
    return 1 if found else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
