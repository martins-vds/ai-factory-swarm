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
  ticket_guard.py --repo owner/repo --reconcile-epic 9 --as-if-merged 42    # in PR #42's CI (ADR-0030)

**As if merged.** The reconciliation file is written in a Slice Coordinator's PR, but was only checked once the
epic closed: a wrong file merged green (pilot #474: 15 problems, epic reopened). In the PR's CI, with the
PR's merge commit checked out, `--as-if-merged N` checks it as main will see it: the issues PR #N closes
count as closed as completed, and PR #N counts as landed at HEAD.

Uses `gh api`; reconciliation also requires PyYAML and complete Git history.
"""
import argparse
import base64
import json
import math
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


def _return_at_head(path, repo, issue_number, cited_prs=None):
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
    if cited_prs is not None:
        attributed, relevant, continuation_problems = _parent_ticket_attribution(
            repo, issue_number, path, doc, cited_prs)
        if attributed:
            return doc, [f"{path}: {'; '.join(continuation_problems)}"]
        if relevant:
            detail = f": {'; '.join(continuation_problems)}" if continuation_problems else ""
            raise ValueError(f"parent-ticket continuation for issue #{issue_number} is not verified{detail}")
    snapshot = _continuation_snapshot(repo, issue_number, path, cited_prs) if cited_prs else None
    if snapshot is not None:
        # The continuation's evidence is the return it landed; later same-path rewrites don't erase it.
        return snapshot, [f"{path}: attributed to issue #{issue_number} by its landed snapshot of the parent return"]
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


def _continuation_snapshot(repo, issue_number, path, cited_prs):
    """A continuation (child issue C of ticket P) is evidenced by one of C's own cited landing PRs that closes C,
    changed the return file, where the return in that PR's landed commit names P and passes. Planner, Auditor and
    Coordinator returns carry no `pr:` field, so the parent-ticket rule could not find their owning PR (pilot
    BK-RECON: restarts #262 and #276 of the Planner's BK-04, re-audit #477 of the Auditor's BK-05J)."""
    try:
        parent = _parent_issue_number(repo, issue_number)
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit):
        return None
    if parent is None:
        return None
    for number in cited_prs:
        if type(number) is not int:
            continue
        try:
            if not _pull_closes_issue(_pull(repo, number), repo, issue_number):
                continue
            commit = _landed_pull(repo, number)
            if not _pull_changes_return_file(repo, number, path):
                continue
            snapshot = _valid_return(git("show", f"{commit}:{path}"), path)
        except (OSError, ValueError, subprocess.SubprocessError, SystemExit):
            continue
        if not snapshot or _role_outcome_problem(snapshot):
            continue
        if str(snapshot.get("issue", "")).strip() == _issue_ref(repo, parent):
            return snapshot
    return None


def _handed_off(repo, path, failed_pull):
    """ADR-0030 amendment: a session that stopped and handed off is evidenced by the handoff its closed,
    unmerged PR committed (pilot BK-ACCEPT #470/#471: blocked by Copilot's firewall, restarted as #473)."""
    path = str(path or "")
    if not re.fullmatch(r"\.migration/handoffs/[A-Za-z0-9][A-Za-z0-9_.-]*\.md", path):
        raise ValueError(f"failure.handoff must name a `.migration/handoffs/<ticket>.md` file, not {path!r}")
    if not _pull_changes_return_file(repo, failed_pull["number"], path):
        raise ValueError(f"failure PR #{failed_pull['number']} doesn't change {path}")
    head = (failed_pull.get("head") or {}).get("sha")
    content = gh(f"repos/{repo}/contents/{quote(path, safe='/')}?ref={head}")
    try:
        text = base64.b64decode(content["content"], validate=False).decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError(f"handoff {path} at PR #{failed_pull['number']} is unreadable: {exc}") from exc
    if not re.search(r"(?m)^## Handoff\b", text) or not re.search(r"(?mi)^### Blockers", text):
        raise ValueError(f"{path} at PR #{failed_pull['number']} is not a handoff with blockers")


def _parent_issue_number(repo, issue_number):
    issue = gh(f"repos/{repo}/issues/{issue_number}")
    if not isinstance(issue, dict) or issue.get("number") != issue_number:
        raise ValueError(f"GitHub issue #{issue_number} identity is unavailable")
    url = issue.get("parent_issue_url")
    if not url:
        return None
    match = re.fullmatch(r"https://api\.github\.com/repos/([^/]+/[^/]+)/issues/([1-9][0-9]*)",
                         url)
    if not match or match[1].lower() != repo.lower():
        raise ValueError(f"GitHub parent relationship for issue #{issue_number} is invalid")
    return int(match[2])


def _issue_is_slice_epic(repo, issue_number):
    import yaml
    issue = gh(f"repos/{repo}/issues/{issue_number}")
    if not isinstance(issue, dict) or issue.get("number") != issue_number:
        raise ValueError(f"GitHub issue #{issue_number} identity is unavailable")
    raw_labels = issue.get("labels", [])
    if not isinstance(raw_labels, list):
        raise ValueError(f"GitHub issue #{issue_number} labels are unavailable")
    labels = [label.get("name") for label in raw_labels if isinstance(label, dict)]
    from fog_rewalk import is_slice_epic
    try:
        return is_slice_epic(issue_number, labels)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"slice-epic metadata for issue #{issue_number} is unavailable: {exc}") from exc


def _pull_closes_issue(pull, repo, issue_number):
    pattern = re.compile(
        rf"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+"
        rf"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#{issue_number}\b"
    )
    return any(match.group("repo") is None or match.group("repo").lower() == repo.lower()
               for match in pattern.finditer(pull.get("body") or ""))


def _issue_pull_references(repo, issue_number):
    """Return PRs GitHub's issue timeline actually cross-references for this issue."""
    references, page = set(), 1
    while True:
        events = gh(f"repos/{repo}/issues/{issue_number}/timeline?per_page=100&page={page}")
        if not isinstance(events, list):
            raise ValueError(f"issue #{issue_number} pull-request references are unavailable")
        for event in events:
            if not isinstance(event, dict) or event.get("event") != "cross-referenced":
                continue
            source = event.get("source")
            source_issue = source.get("issue") if isinstance(source, dict) else None
            if not isinstance(source_issue, dict) or not source_issue.get("pull_request"):
                continue
            number = source_issue.get("number")
            if type(number) is int and number > 0:
                references.add(number)
        if len(events) < 100:
            return sorted(references)
        page += 1


def _pull_changes_return_file(repo, pull_number, path):
    page = 1
    while True:
        files = gh(f"repos/{repo}/pulls/{pull_number}/files?per_page=100&page={page}")
        if not isinstance(files, list):
            raise ValueError(f"PR #{pull_number} changed-file evidence is unavailable")
        if any(isinstance(item, dict) and item.get("filename") == path for item in files):
            return True
        if len(files) < 100:
            return False
        page += 1


def _parent_ticket_return(repo, issue_number, path, doc, *, pull=None, require_landed=True,
                          check_owner=True, verified_parent=None):
    """Verify a return owned by a parent ticket's child work PR, never by parentage alone."""
    issue_ref = doc.get("issue", "")
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]*)", issue_ref)
    if not match or f"{match[1]}/{match[2]}".lower() != repo.lower():
        raise ValueError(f"return does not identify a same-repository parent ticket")
    actual_parent = verified_parent if verified_parent is not None else _parent_issue_number(repo, issue_number)
    if actual_parent != int(match[3]):
        raise ValueError(f"issue #{issue_number} is not a child of return ticket #{match[3]}")
    owner_pr = _return_pr_number(doc, repo, return_path=path)
    if owner_pr is None and check_owner:
        raise ValueError(f"parent-owned return for issue #{issue_number} has no owning PR")
    if pull is None and owner_pr is not None:
        pull = _pull(repo, owner_pr)
    if not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
        raise ValueError(f"parent-owned return for issue #{issue_number} has no attributable PR")
    if check_owner and owner_pr != pull["number"]:
        raise ValueError(f"return does not identify PR #{pull['number']} as its owning PR")
    if not _pull_closes_issue(pull, repo, issue_number):
        raise ValueError(f"PR #{pull['number']} does not close child issue #{issue_number}")
    if require_landed:
        commit = _landed_pull(repo, pull["number"])
        if not _return_in_commit(_return_path(path), doc, commit):
            raise ValueError(f"PR #{pull['number']} does not contain this exact role return")
    return pull["number"]


def _parent_ticket_attribution(repo, issue_number, path, current, cited_prs=None):
    problems = []
    try:
        parent_number = _parent_issue_number(repo, issue_number)
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
        return False, True, [f"GitHub parent relationship for issue #{issue_number} is unavailable: {exc}"]
    if parent_number is None:
        return False, False, []
    relevant = True
    current_issue = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]*)",
                                 current.get("issue", ""))
    if not current_issue or f"{current_issue[1]}/{current_issue[2]}".lower() != repo.lower():
        return False, relevant, ["current return does not name a same-repository issue"]
    current_number = int(current_issue[3])
    if current_number != parent_number:
        try:
            current_parent = _parent_issue_number(repo, current_number)
        except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
            return False, relevant, [f"current return issue #{current_number} parent is unavailable: {exc}"]
        if current_parent == issue_number:
            return False, False, []
        if current_parent != parent_number:
            return False, relevant, ["current return issue is not the parent or a sibling of the child"]

    path = _return_path(path)
    try:
        committed = _valid_return(git("show", f"HEAD:{path}"), path)
    except ValueError as exc:
        return False, True, [f"current return snapshot is unavailable at HEAD: {exc}"]
    if committed != current:
        return False, True, [f"current return at {path} differs from its committed HEAD snapshot"]
    outcome_problem = _role_outcome_problem(current)
    if outcome_problem:
        return False, True, [f"current role outcome does not pass: {outcome_problem}"]
    try:
        if _issue_is_slice_epic(repo, parent_number):
            return False, False, []
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
        return False, True, [f"parent issue #{parent_number} identity is unavailable: {exc}"]
    try:
        current_pr = _return_pr_number(current, repo, return_path=path)
    except ValueError as exc:
        return False, True, [str(exc)]
    if current_pr is None:
        # Ordinary history may still use the existing no-owning-PR contract or verified exemption.
        return False, False, []
    if cited_prs is not None and not any(type(number) is int and number == current_pr for number in cited_prs):
        return False, True, [f"current owning PR #{current_pr} is not among the cited landing PRs"]
    try:
        current_pull = _pull(repo, current_pr)
        current_commit = _landed_pull(repo, current_pr)
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
        return False, True, [f"current owning PR #{current_pr} has no verified landing: {exc}"]
    if not _return_in_commit(path, current, current_commit):
        return False, True, [f"current owning PR #{current_pr} does not contain the exact current return"]
    if current_number != parent_number and not _pull_closes_issue(current_pull, repo, current_number):
        return False, True, [f"current owning PR #{current_pr} does not close current issue #{current_number}"]

    try:
        work_pr_numbers = (sorted(number for number in cited_prs
                                  if type(number) is int and number > 0) if cited_prs is not None
                           else _issue_pull_references(repo, issue_number))
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
        return False, True, [f"child-work PR references for issue #{issue_number} are unavailable: {exc}"]
    if not work_pr_numbers:
        return False, relevant, ["no cited or GitHub-referenced child-work PR proves the child work"]

    current_issue_ref = current.get("issue")
    for work_pr_number in work_pr_numbers:
        try:
            work_pull = _pull(repo, work_pr_number)
            if not _pull_closes_issue(work_pull, repo, issue_number):
                problems.append(f"child-work PR #{work_pr_number} does not close child issue #{issue_number}")
                continue
            work_commit = _landed_pull(repo, work_pr_number)
            if not _pull_changes_return_file(repo, work_pr_number, path):
                problems.append(f"child-work PR #{work_pr_number} did not change the exact role return file")
                continue
            snapshot = _valid_return(git("show", f"{work_commit}:{path}"), path)
            if not snapshot or any(snapshot.get(key) != current.get(key) for key in ("ticket", "role")):
                problems.append(f"child-work PR #{work_pr_number} has no matching role return at its landing")
                continue
            snapshot_issue = snapshot.get("issue")
            if snapshot_issue == current_issue_ref or snapshot_issue == _issue_ref(repo, parent_number):
                return True, relevant, [f"parent-ticket continuation verified by current PR #{current_pr} "
                                        f"and child PR #{work_pr_number}"]
            snapshot_match = re.fullmatch(
                r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]*)", snapshot_issue or "")
            if not snapshot_match or \
                    f"{snapshot_match[1]}/{snapshot_match[2]}".lower() != repo.lower():
                problems.append(f"child-work PR #{work_pr_number} return has no same-repository issue")
                continue
            snapshot_number = int(snapshot_match[3])
            if snapshot_number in {issue_number, current_number} and \
                    _parent_issue_number(repo, snapshot_number) == parent_number:
                return True, relevant, [f"parent-ticket continuation verified by current PR #{current_pr} "
                                        f"and child PR #{work_pr_number}"]
            problems.append(f"child-work PR #{work_pr_number} return is outside the verified parent lineage")
        except (OSError, ValueError, subprocess.SubprocessError, SystemExit) as exc:
            problems.append(f"child-work PR #{work_pr_number} is not verified: {exc}")
    return False, relevant, problems or ["no landed child-work PR changed and contains the matching role return"]


def _pull(repo, number):
    if type(number) is not int or number <= 0:
        raise ValueError(f"invalid pull request number: {number!r}")
    pull = gh(f"repos/{repo}/pulls/{number}")
    if not isinstance(pull, dict) or pull.get("number") != number:
        raise ValueError(f"pull request #{number} evidence is unavailable")
    return pull


PENDING = {"pull": None, "closes": frozenset()}   # --as-if-merged: the PR under test and the issues it closes


def _landed_pull(repo, number):
    if PENDING["pull"] == number:   # the PR under test: its merge commit is HEAD
        return git("rev-parse", "HEAD")
    pull = _pull(repo, number)
    if pull.get("state") != "closed":
        raise ValueError(f"PR #{number} is still open")
    commit = pull.get("merge_commit_sha") if pull.get("merged_at") else (pull.get("head") or {}).get("sha")
    if commit and integrated(commit):
        return commit
    via = _stacked_landing(repo, pull) if pull.get("merged_at") else None
    if via is not None:
        return via
    raise ValueError(f"PR #{number} has no verified landing in default-branch history")


def _stacked_landing(repo, pull, depth=3):
    """The landing of a PR merged into another PR's branch (ADR-0040's Verifier PR into the migrator's branch).

    Its own merge commit is gone from the default branch when the branch below it was squash-merged; its content
    landed with that PR. So: the PR whose head was this PR's base, merged after it, whose landing is verified
    (recursively, for deeper stacks). Returns that landing commit, or None."""
    base = (pull.get("base") or {}).get("ref")
    default = ((pull.get("base") or {}).get("repo") or {}).get("default_branch")
    if not base or base == default or depth <= 0:
        return None
    owner = repo.split("/")[0]
    try:
        below = gh(f"repos/{repo}/pulls?state=closed&head={owner}:{base}&per_page=20")
    except (OSError, ValueError, subprocess.SubprocessError, SystemExit):
        return None
    for candidate in below if isinstance(below, list) else []:
        if not candidate.get("merged_at") or candidate["merged_at"] < pull["merged_at"]:
            continue
        commit = candidate.get("merge_commit_sha")
        if commit and integrated(commit):
            return commit
        deeper = _stacked_landing(repo, candidate, depth - 1)
        if deeper is not None:
            return deeper
    return None


def _return_pr_number(doc, repo, *, return_path=None):
    role = doc.get("role")
    field = "setup_pr" if role == "afs-bootstrapper" else "pr"
    value = doc.get(field)
    if value is None and role not in {"afs-bootstrapper", "afs-migrator",
                                      "afs-specialist-migrator", "afs-verifier"}:
        return None
    if value is None and field == "pr" and return_path is not None:
        from validate import pre_rule_null_pr
        path = pathlib.Path(_return_path(return_path))
        if pre_rule_null_pr(path, pathlib.Path(".migration")):
            print(f"::notice::{path}: unchanged pre-rule null-PR return; "
                  "a cited landed PR must still contain its exact snapshot")
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
        handoff = doc.get("handoff")
        has_blocker = isinstance(handoff, str) and handoff.strip() and handoff != "none"
        if not has_failed_gate and not has_blocker:
            return f"{role} return has no explicit failed gate or blocker handoff"
    elif role in {"afs-migrator", "afs-specialist-migrator"}:
        gates = doc.get("gates")
        if not isinstance(gates, dict):
            return f"{role} return has no gate outcome evidence"

        def reasoned_na(value):
            return isinstance(value, str) and re.match(r"^n/a: \S", value) is not None

        for gate in ("build", "behavior", "idiom", "regression"):
            result = gates.get(gate)
            if (type(result) is int and result == 0) or \
                    reasoned_na(result):
                continue
            return f"{role} gate `{gate}` has no passing result"
        crap, mutation = gates.get("crap"), gates.get("mutation_changed")
        if not reasoned_na(crap) and (
                type(crap) not in {int, float} or crap < 0 or
                (type(crap) is float and not math.isfinite(crap))):
            return f"{role} gate `crap` has no score"
        if not reasoned_na(mutation) and (
                type(mutation) not in {int, float} or not 0 <= mutation <= 1 or
                (type(mutation) is float and not math.isfinite(mutation))):
            return f"{role} gate `mutation_changed` has no score"
        if doc.get("handoff") not in (None, "", "none"):
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


KILLED = {"cancelled", "timed_out", "failure"}


def _killed_session(repo, run_id, failed_pull):
    """ADR-0030 amendment: a session killed before it could write a return (e.g. the cloud agent's time limit)
    is evidenced by its own Actions run: the agent run on the failure PR's branch that ended cancelled, timed
    out or failed. Only when that PR has no return of its own; a session that wrote one is judged by it."""
    if not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("failure.session_run must be the agent session's Actions run id")
    run = gh(f"repos/{repo}/actions/runs/{run_id}")
    head = (failed_pull.get("head") or {}).get("ref")
    if "copilot" not in str(run.get("name", "")).lower() and "agent" not in str(run.get("name", "")).lower():
        raise ValueError(f"run {run_id} is not an agent session run ({run.get('name')!r})")
    if run.get("head_branch") != head:
        raise ValueError(f"run {run_id} ran on {run.get('head_branch')!r}, not the failure PR's branch {head!r}")
    if run.get("conclusion") not in KILLED:
        raise ValueError(f"run {run_id} ended {run.get('conclusion')!r}, not cancelled, timed out or failed")
    files = gh(f"repos/{repo}/pulls/{failed_pull['number']}/files?per_page=100")
    if any(str(f.get("filename", "")).startswith(".migration/returns/") for f in files):
        raise ValueError("the failure PR has a return file: cite it as failure.return instead of session_run")


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
    if not doc:
        raise ValueError(f"{path} does not belong to issue #{issue_number}")
    if not match or f"{match[1]}/{match[2]}#{match[3]}" != _issue_ref(repo, issue_number):
        try:
            _parent_ticket_return(repo, issue_number, path, doc, pull=pull, require_landed=False,
                                  check_owner=False)
        except (ValueError, OSError, subprocess.SubprocessError, SystemExit) as exc:
            raise ValueError(f"{path} does not belong to issue #{issue_number}: {exc}") from exc
    outcome_problem = _role_outcome_problem(doc, failed=True)
    if outcome_problem:
        raise ValueError(f"{path} does not preserve an explicit failed role outcome: {outcome_problem}")
    owner_pr = _return_pr_number(doc, repo)
    if owner_pr is not None and owner_pr != pull_number:
        raise ValueError(f"{path} does not identify failed PR #{pull_number} as its owning PR")


def completed_evidence_problems(repo, number, item, notice=print):
    """Problems with one `completed` disposition's evidence: its landing PRs and the role returns they landed.
    The single attribution rule for a completed ticket, shared by the reconciliation check (ADR-0030) and the
    epic's return-file check (ADR-0024), so the two can't disagree about what counts as a ticket's return."""
    prs = item.get("pull_requests")
    returns = item.get("returns")
    if not isinstance(prs, list) or not prs:
        return ["completed disposition needs verified landing PR(s)"]
    if not isinstance(returns, list) or not returns:
        return ["completed disposition needs relevant role return(s)"]
    problems, landed = [], {}
    for pr_number in prs:
        try:
            landed[pr_number] = _landed_pull(repo, pr_number)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            problems.append(str(exc))
    for return_path in returns:
        try:
            doc, diagnostics = _return_at_head(return_path, repo, number, set(landed))
            for diagnostic in diagnostics:
                notice(f"::notice::{diagnostic}")
            outcome_problem = _role_outcome_problem(doc)
            if outcome_problem:
                raise ValueError(outcome_problem)
            owner_pr = _return_pr_number(doc, repo, return_path=return_path)
            if owner_pr is not None and owner_pr not in landed:
                raise ValueError(f"owning PR #{owner_pr} is missing from completed evidence")
            candidates = [landed[owner_pr]] if owner_pr is not None else list(landed.values())
            if not any(_return_in_commit(_return_path(return_path), doc, commit) for commit in candidates):
                raise ValueError("no cited landed PR contains this role return")
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            problems.append(str(exc))
    return problems


def reconciliation_problems(repo, epic_number, epic, report_path=None):
    """Validate a committed, explicit disposition for every non-decision descendant of a slice epic."""
    from fog_rewalk import is_slice_epic
    labels = [label.get("name") for label in epic.get("labels", [])]
    if not is_slice_epic(epic_number, labels):
        return None, []

    descendants_by_number = descendants(repo, epic_number)
    for number in PENDING["closes"] & set(descendants_by_number):   # closed as completed when the PR merges
        descendants_by_number[number] = dict(descendants_by_number[number], state="closed",
                                             state_reason="completed")
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
                problems.extend(f"#{number}: {problem}" for problem in completed_evidence_problems(repo, number, item))
            elif disposition == "superseded":
                if issue.get("state") != "closed" or issue.get("state_reason") != "not_planned":
                    problems.append(f"#{number}: superseded disposition requires closure as not planned")
                replacement = item.get("replacement")
                if not isinstance(replacement, int) or replacement <= 0 or replacement == number:
                    problems.append(f"#{number}: superseded disposition needs a replacement issue link")
                else:
                    try:
                        replacement_issue = gh(f"repos/{repo}/issues/{replacement}")
                        if replacement in PENDING["closes"]:
                            replacement_issue = dict(replacement_issue, state="closed", state_reason="completed")
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
                    if failure.get("session_run") is not None:
                        _killed_session(repo, failure["session_run"], failed_pull)
                    elif failure.get("handoff") is not None:
                        _handed_off(repo, failure["handoff"], failed_pull)
                    else:
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


def pending_merge(repo, pull_number):
    """The open PR under test and the issues its description closes (GitHub closes them on merge)."""
    pull = _pull(repo, pull_number)
    if pull.get("state") != "open":
        raise ValueError(f"--as-if-merged needs an open PR; #{pull_number} is {pull.get('state')}")
    body = pull.get("body") or ""
    closes = set()
    for match in re.finditer(r"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+"
                             r"(?:([\w.-]+/[\w.-]+))?#([1-9][0-9]*)\b", body):
        if match[1] in (None, repo):
            closes.add(int(match[2]))
    return {"pull": pull_number, "closes": frozenset(closes)}


def reconcile_epic(repo, number, reopen=False, as_if_merged=None):
    R = f"repos/{repo}"
    if as_if_merged is not None:
        PENDING.update(pending_merge(repo, as_if_merged))
        print(f"as if PR #{as_if_merged} were merged: it closes {sorted(PENDING['closes']) or 'no issues'}")
        reopen = False
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
    ap.add_argument("--as-if-merged", type=int, metavar="PR",
                    help="with --reconcile-epic, in PR's CI: check as main will see it once PR merges (never reopens)")
    a = ap.parse_args(argv)
    if a.as_if_merged is not None and a.reconcile_epic is None:
        ap.error("--as-if-merged needs --reconcile-epic")
    if a.reconcile_epic is not None:
        try:
            return reconcile_epic(a.repo, a.reconcile_epic, a.reopen, a.as_if_merged)
        except ValueError as exc:
            print(f"::error::{exc}")
            return 2
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
