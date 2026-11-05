#!/usr/bin/env python3
"""Guard premature ticket closure and require evidence-backed slice reconciliation.

GitHub closes an issue when a PR that says "Fixes #N" merges, and it also closes the issues of a whole
stack when a PR merges into another PR's branch (pilot HR-04C: merging a Verifier PR into the work branch
closed the work ticket while the work PR was still open). A closed ticket is read as done: its blockers
lift, and the slice-epic check counts it. So when a ticket closes as completed while an **open PR into the
default branch** still says it fixes, closes or resolves that ticket, the ticket is reopened, with a
comment naming the PR. Closing as "not planned", or with no such PR, is left alone.

  ticket_guard.py --repo owner/repo --issue 129
  ticket_guard.py --repo owner/repo --reconcile-epic 9 --reopen

Uses `gh api`; reconciliation also requires PyYAML and complete Git history.
"""
import argparse
import base64
import json
import pathlib
import re
import subprocess
import sys
from urllib.parse import quote

CLOSES = r"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#{n}\b"
RECONCILIATION_DIR = pathlib.Path(".migration/evidence/ticket-reconciliation")
RESEARCH_LABELS = {"wayfinder:map", "wayfinder:research", "wayfinder:prototype",
                   "wayfinder:grilling", "wayfinder:task"}


def gh(*args, data=None):
    cmd = ["gh", "api", *args] + (["--input", "-"] if data is not None else [])
    r = subprocess.run(cmd, input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"gh api {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def open_fixers(pulls, number):
    """Open PRs whose description says they fix, close or resolve issue #number."""
    pat = re.compile(CLOSES.format(n=number))
    return [p for p in pulls if p.get("state") == "open" and pat.search(p.get("body") or "")]


def git(*args):
    result = subprocess.run(["git", "--no-replace-objects", *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def has_complete_history():
    return git("rev-parse", "--is-shallow-repository") == "false"


def integrated(commit):
    """Whether an evidence commit is present in the checked-out default-branch history."""
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(commit or "")):
        raise ValueError(f"invalid or unavailable landing commit: {commit!r}")
    check = subprocess.run(["git", "--no-replace-objects", "cat-file", "-e", f"{commit}^{{commit}}"],
                           capture_output=True, text=True)
    if check.returncode:
        raise ValueError(f"landing commit {commit} is unavailable in local history")
    result = subprocess.run(["git", "--no-replace-objects", "merge-base", "--is-ancestor", commit, "HEAD"],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise ValueError(result.stderr.strip() or f"cannot check ancestry for {commit}")
    return result.returncode == 0


def descendants(repo, epic, gh_func=None):
    """All work issues under the slice epic; decision-map/research issues are out of scope."""
    gh_func = gh_func or gh
    found, seen, pending = {}, {epic}, [epic]
    while pending:
        parent = pending.pop()
        page = 1
        while True:
            batch = gh_func(f"repos/{repo}/issues/{parent}/sub_issues?per_page=100&page={page}") or []
            for issue in batch:
                number = issue.get("number")
                if not isinstance(number, int) or number <= 0 or number in seen:
                    continue
                seen.add(number)
                labels = {label.get("name") for label in issue.get("labels", [])}
                if labels & RESEARCH_LABELS:
                    continue
                found[number] = issue
                pending.append(number)
            if len(batch) < 100:
                break
            page += 1
    return found


def _return_path(value):
    path = pathlib.PurePosixPath(value) if isinstance(value, str) else None
    if (path is None or path.is_absolute() or path.as_posix() != value
            or not path.parts or path.parts[0:2] != (".migration", "returns")
            or ".." in path.parts):
        raise ValueError(f"return evidence must name a committed `.migration/returns/` file: {value!r}")
    return value


def _valid_return(text, path):
    import yaml
    from check_slice_returns import valid_return
    try:
        return valid_return(text, path)
    except (UnicodeError, yaml.YAMLError):
        return None


def _issue_ref(repo, number):
    return f"{repo}#{number}"


def _return_at_head(path, repo, issue_number):
    path = _return_path(path)
    try:
        text = git("show", f"HEAD:{path}")
    except ValueError as exc:
        raise ValueError(f"return evidence {path} is unavailable at HEAD: {exc}") from exc
    doc = _valid_return(text, path)
    if not doc:
        raise ValueError(f"return evidence {path} is not a valid role return")
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]*)", doc.get("issue", ""))
    expected = _issue_ref(repo, issue_number)
    if match and f"{match[1]}/{match[2]}#{match[3]}" == expected:
        return doc, []
    try:
        from check_slice_returns import superseded_attribution
        attributed, diagnostics = superseded_attribution(
            {expected}, {pathlib.Path(path): doc})
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"return attribution history for {path} is unavailable: {exc}") from exc
    if expected not in attributed:
        raise ValueError(f"return evidence {path} does not attribute to issue #{issue_number} "
                         "directly or through same-path ticket/role history")
    return doc, diagnostics


def _pull(repo, number):
    if not isinstance(number, int) or number <= 0:
        raise ValueError(f"invalid pull request number: {number!r}")
    pull = gh(f"repos/{repo}/pulls/{number}")
    if not isinstance(pull, dict) or pull.get("number") != number:
        raise ValueError(f"pull request #{number} evidence is unavailable")
    return pull


def _landed_pull(repo, number):
    pull = _pull(repo, number)
    if pull.get("state") != "closed":
        raise ValueError(f"PR #{number} is still open")
    commit = pull.get("merge_commit_sha") if pull.get("merged_at") else (pull.get("head") or {}).get("sha")
    if not commit or not integrated(commit):
        raise ValueError(f"PR #{number} has no verified landing in default-branch history")
    return commit


def _return_pr_number(doc, repo):
    role = doc.get("role")
    field = "setup_pr" if role == "afs-bootstrapper" else "pr"
    value = doc.get(field)
    if value is None and role not in {"afs-bootstrapper", "afs-migrator",
                                      "afs-specialist-migrator", "afs-verifier"}:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{role} return has no owning PR reference in `{field}`")
    value = value.strip()
    match = re.fullmatch(rf"{re.escape(repo)}#([1-9][0-9]*)", value)
    if match:
        return int(match[1])
    match = re.fullmatch(rf"https?://github\.com/{re.escape(repo)}/pull/([1-9][0-9]*)(?:/)?", value)
    if match:
        return int(match[1])
    match = re.fullmatch(r"#([1-9][0-9]*)", value)
    if match:
        return int(match[1])
    raise ValueError(f"{role} return has an invalid owning PR reference in `{field}`: {value!r}")


def _role_outcome_problem(doc, *, failed=False):
    role = doc.get("role")
    if role == "afs-verifier":
        acceptable = {"changes-required", "blocked"} if failed else {"pass"}
        if doc.get("verdict") not in acceptable:
            return f"Verifier verdict is not {'an explicit failure' if failed else 'pass'}"
    elif role == "afs-bootstrapper":
        validation = doc.get("validation")
        pattern = r"^(?:fail|failed|blocked)(?:$|[\s:;,.(\-])" if failed else r"^(?:pass|passed)(?:$|[\s:;,.(\-])"
        if not isinstance(validation, str) or not re.match(pattern, validation.strip(), re.IGNORECASE):
            return f"Bootstrapper validation is not an explicit {'failure' if failed else 'pass'}"
    elif role == "afs-auditor":
        acceptable = {"gaps-remain"} if failed else {"complete"}
        if doc.get("verdict") not in acceptable:
            return f"Auditor verdict is not {'gaps-remain' if failed else 'complete'}"
    elif role in {"afs-migrator", "afs-specialist-migrator"} and failed:
        gates = doc.get("gates")
        failed_gates = {"build", "behavior", "idiom", "regression"}
        has_failed_gate = isinstance(gates, dict) and any(
            type(gates.get(gate)) is int and gates[gate] != 0 for gate in failed_gates)
        if not has_failed_gate and not (isinstance(doc.get("handoff"), str) and doc["handoff"].strip()):
            return f"{role} return has no explicit failed gate or blocker handoff"
    elif role in {"afs-migrator", "afs-specialist-migrator"}:
        gates = doc.get("gates")
        if not isinstance(gates, dict):
            return f"{role} return has no gate outcome evidence"
        for gate in ("build", "behavior", "idiom", "regression"):
            result = gates.get(gate)
            if (type(result) is int and result == 0) or \
                    (isinstance(result, str) and result.startswith("n/a: ") and result[5:].strip()):
                continue
            return f"{role} gate `{gate}` has no passing result"
        crap, mutation = gates.get("crap"), gates.get("mutation_changed")
        if type(crap) not in {int, float} or crap < 0:
            return f"{role} gate `crap` has no score"
        if type(mutation) not in {int, float} or not 0 <= mutation <= 1:
            return f"{role} gate `mutation_changed` has no score"
        if isinstance(doc.get("handoff"), str) and doc["handoff"].strip():
            return f"{role} return still has an outstanding handoff"
    elif role == "afs-characterizer" and failed:
        suite = doc.get("suite")
        if (not isinstance(suite, dict) or type(suite.get("cases")) is not int
                or type(suite.get("passing")) is not int or suite["passing"] >= suite["cases"]):
            return "Characterizer return has no explicit failing case evidence"
    elif role == "afs-characterizer":
        suite = doc.get("suite")
        if (not isinstance(suite, dict) or type(suite.get("cases")) is not int
                or type(suite.get("passing")) is not int or suite["cases"] <= 0
                or suite["passing"] != suite["cases"]):
            return "Characterizer return does not show all characterization cases passing"
    else:
        return f"role {role!r} has no supported explicit failure outcome" if failed else None
    return None


def _return_in_commit(path, doc, commit):
    try:
        committed = git("show", f"{commit}:{path}")
    except ValueError:
        return False
    return _valid_return(committed, path) == doc


def _failed_role_return(repo, issue_number, pull_number, path, pull):
    path = _return_path(path)
    head = (pull.get("head") or {}).get("sha")
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(head or "")):
        raise ValueError(f"failed PR #{pull_number} has no exact head SHA")
    content = gh(f"repos/{repo}/contents/{quote(path, safe='/')}?ref={head}")
    if not isinstance(content, dict) or content.get("encoding") != "base64":
        raise ValueError(f"failure return {path} at PR #{pull_number} is unavailable")
    try:
        text = base64.b64decode(content["content"], validate=False).decode("utf-8")
    except (KeyError, ValueError, UnicodeError) as exc:
        raise ValueError(f"failure return {path} at PR #{pull_number} is unreadable: {exc}") from exc
    doc = _valid_return(text, path)
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]*)",
                         doc.get("issue", "") if doc else "")
    if not doc or not match or f"{match[1]}/{match[2]}#{match[3]}" != _issue_ref(repo, issue_number):
        raise ValueError(f"{path} does not belong to issue #{issue_number}")
    outcome_problem = _role_outcome_problem(doc, failed=True)
    if outcome_problem:
        raise ValueError(f"{path} does not preserve an explicit failed role outcome: {outcome_problem}")
    owner_pr = _return_pr_number(doc, repo)
    if owner_pr is not None and owner_pr != pull_number:
        raise ValueError(f"{path} does not identify failed PR #{pull_number} as its owning PR")


def reconciliation_problems(repo, epic_number, epic, report_path=None):
    """Validate a committed, explicit disposition for every non-decision descendant of a slice epic."""
    from fog_rewalk import is_slice_epic
    labels = [label.get("name") for label in epic.get("labels", [])]
    if not is_slice_epic(epic_number, labels):
        return None, []

    descendants_by_number = descendants(repo, epic_number)
    scope = set(descendants_by_number)
    path = pathlib.Path(report_path or (RECONCILIATION_DIR / f"{epic_number}.yaml"))
    load_problem = None
    import yaml
    try:
        report = yaml.safe_load(git("show", f"HEAD:{path.as_posix()}"))
    except ValueError:
        report = None
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        report = None
        load_problem = f"cannot read or parse reconciliation evidence {path}: {exc}"
    else:
        load_problem = None

    problems = []
    if load_problem:
        problems.append(load_problem)
    elif not isinstance(report, dict):
        problems.append(f"missing reconciliation evidence `{path}`")
    elif report.get("epic") != epic_number or report.get("scope") != "slice-epic-descendants":
        problems.append(f"`{path}` must name epic {epic_number} and scope `slice-epic-descendants`")
    entries = report.get("issues") if isinstance(report, dict) else None
    if not isinstance(entries, list):
        entries = []
        if report is not None:
            problems.append(f"`{path}` must contain an `issues` list")

    by_number = {}
    for item in entries:
        number = item.get("number") if isinstance(item, dict) else None
        if not isinstance(number, int) or number <= 0:
            problems.append(f"`{path}` contains an issue without a positive number")
        elif number in by_number:
            problems.append(f"`{path}` lists issue #{number} more than once")
        else:
            by_number[number] = item
    for number in sorted(scope - by_number.keys()):
        problems.append(f"#{number}: missing explicit disposition")
    for number in sorted(by_number.keys() - scope):
        problems.append(f"#{number}: outside slice-epic descendant scope")
    for number in sorted(scope & by_number.keys()):
        print(f"::notice::#{number} disposition={by_number[number].get('disposition')}")
    try:
        complete_history = has_complete_history()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        complete_history = False
        history_problem = f"default-branch history unavailable: {exc}"
    else:
        history_problem = "default-branch history unavailable or shallow; fetch complete history and retry"
    if not complete_history:
        problems.append(history_problem)
    else:
        for number in sorted(scope & by_number.keys()):
            item = by_number[number]
            issue = descendants_by_number[number]
            disposition = item.get("disposition")
            if disposition == "completed":
                if issue.get("state") != "closed" or issue.get("state_reason") != "completed":
                    problems.append(f"#{number}: completed disposition requires an issue closed as completed")
                    continue
                prs = item.get("pull_requests")
                returns = item.get("returns")
                if not isinstance(prs, list) or not prs:
                    problems.append(f"#{number}: completed disposition needs verified landing PR(s)")
                    continue
                if not isinstance(returns, list) or not returns:
                    problems.append(f"#{number}: completed disposition needs relevant role return(s)")
                    continue
                landed = {}
                for pr_number in prs:
                    try:
                        landed[pr_number] = _landed_pull(repo, pr_number)
                    except (ValueError, OSError, subprocess.SubprocessError) as exc:
                        problems.append(f"#{number}: {exc}")
                for return_path in returns:
                    try:
                        doc, diagnostics = _return_at_head(return_path, repo, number)
                        for diagnostic in diagnostics:
                            print(f"::notice::{diagnostic}")
                        outcome_problem = _role_outcome_problem(doc)
                        if outcome_problem:
                            raise ValueError(outcome_problem)
                        owner_pr = _return_pr_number(doc, repo)
                        if owner_pr is not None and owner_pr not in landed:
                            raise ValueError(f"owning PR #{owner_pr} is missing from completed evidence")
                        candidates = [landed[owner_pr]] if owner_pr is not None else list(landed.values())
                        if not any(_return_in_commit(_return_path(return_path), doc, commit)
                                   for commit in candidates):
                            raise ValueError(f"no cited landed PR contains this role return")
                    except (ValueError, OSError, subprocess.SubprocessError) as exc:
                        problems.append(f"#{number}: {exc}")
            elif disposition == "superseded":
                if issue.get("state") != "closed" or issue.get("state_reason") != "not_planned":
                    problems.append(f"#{number}: superseded disposition requires closure as not planned")
                replacement = item.get("replacement")
                if not isinstance(replacement, int) or replacement <= 0 or replacement == number:
                    problems.append(f"#{number}: superseded disposition needs a replacement issue link")
                else:
                    try:
                        replacement_issue = gh(f"repos/{repo}/issues/{replacement}")
                        if replacement_issue.get("pull_request"):
                            raise ValueError(f"replacement #{replacement} is not an issue")
                        if replacement_issue.get("state") != "closed" or \
                                replacement_issue.get("state_reason") != "completed":
                            raise ValueError(f"replacement #{replacement} is not completed")
                        replacement_entry = by_number.get(replacement)
                        if replacement_entry and replacement_entry.get("disposition") != "completed":
                            raise ValueError(f"replacement #{replacement} lacks a completed disposition")
                    except (AttributeError, ValueError) as exc:
                        problems.append(f"#{number}: invalid replacement issue #{replacement}: {exc}")
                failure = item.get("failure")
                if not isinstance(failure, dict) or not isinstance(failure.get("pull_request"), int):
                    problems.append(f"#{number}: superseded disposition needs a failed role PR and its return evidence")
                    continue
                try:
                    failed_pull = _pull(repo, failure["pull_request"])
                    if failed_pull.get("state") != "closed" or failed_pull.get("merged_at"):
                        raise ValueError(f"failure PR #{failure['pull_request']} must be closed unmerged")
                    _failed_role_return(repo, number, failure["pull_request"], failure.get("return"), failed_pull)
                except (ValueError, OSError, subprocess.SubprocessError) as exc:
                    problems.append(f"#{number}: {exc}")
            elif disposition == "retained-open":
                if issue.get("state") != "open":
                    problems.append(f"#{number}: retained-open disposition requires an open issue")
                for field in ("outstanding", "blocker"):
                    if not isinstance(item.get(field), str) or not item[field].strip():
                        problems.append(f"#{number}: retained-open disposition needs actual `{field}` work")
            else:
                problems.append(f"#{number}: disposition must be completed, superseded or retained-open")
    return len(scope), problems


def reconcile_epic(repo, number, reopen=False):
    R = f"repos/{repo}"
    epic = gh(f"{R}/issues/{number}")
    count, problems = reconciliation_problems(repo, number, epic)
    if count is None:
        print(f"#{number} is not a slice epic; ticket reconciliation is out of scope.")
        return 0
    print(f"slice epic #{number}: {count} in-scope issue(s)")
    for problem in problems:
        print(f"::error::{problem}")
    print(f"AFS-RESULT gate=ticket-reconciliation epic={number} "
          f"verdict={'fail' if problems else 'pass'} tickets={count} failures={len(problems)}")
    if problems and reopen and epic.get("state") == "closed":
        body = ("**Reopened by the harness (ADR-0030):** ticket lifecycle reconciliation is incomplete.\n\n"
                + "\n".join(f"- {problem}" for problem in problems)
                + "\n\nCommit `.migration/evidence/ticket-reconciliation/"
                f"{number}.yaml` with evidence-backed dispositions, then close this epic again.")
        gh(f"{R}/issues/{number}/comments", "-X", "POST", data={"body": body})
        gh(f"{R}/issues/{number}", "-X", "PATCH", data={"state": "open"})
        print(f"reopened #{number}")
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    operation = ap.add_mutually_exclusive_group(required=True)
    operation.add_argument("--issue", type=int)
    operation.add_argument("--reconcile-epic", type=int)
    ap.add_argument("--reopen", action="store_true", help="reopen a failing slice epic")
    a = ap.parse_args(argv)
    if a.reconcile_epic is not None:
        return reconcile_epic(a.repo, a.reconcile_epic, a.reopen)
    R = f"repos/{a.repo}"
    issue = gh(f"{R}/issues/{a.issue}")
    if issue.get("pull_request") or issue.get("state") != "closed" or issue.get("state_reason") != "completed":
        print(f"#{a.issue}: not a ticket closed as completed; nothing to do")
        return 0
    default = gh(R)["default_branch"]
    pulls, page = [], 1
    while True:
        batch = gh(f"{R}/pulls?state=open&base={default}&per_page=100&page={page}") or []
        pulls += batch
        if len(batch) < 100:
            break
        page += 1
    fixers = open_fixers(pulls, a.issue)
    if not fixers:
        print(f"#{a.issue}: no open PR into {default} fixes it; closed stays closed")
        return 0
    links = ", ".join(f"#{p['number']}" for p in fixers)
    gh(f"{R}/issues/{a.issue}", "-X", "PATCH", data={"state": "open"})
    gh(f"{R}/issues/{a.issue}/comments", "-X", "POST", data={"body": (
        f"**Reopened by the harness (ADR-0029):** this ticket closed while {links} (into `{default}`), which "
        f"fixes it, is still open. A ticket is done when its work reaches `{default}`; it will close when "
        f"{links} merges.")})
    print(f"#{a.issue}: reopened; open fixing PR(s) into {default}: {links}")
    return 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
