#!/usr/bin/env python3
"""Install AI Factory Swarm into a target repository (Phase 1, ADR-0003/0008/0012/0015).

Usage:
  bootstrap.py --target <dir> --profile <profile.yaml> --capabilities <capabilities.yaml>
               [--stack-pack stacks/<pack>.json ...] [--create-gap-issues] [--offline]

<dir> is a clone of the target repo; bootstrap writes files there and never commits. Review the diff
and open it as the setup PR. What it writes:

  .migration/source.lock, profile.yaml, capabilities.yaml, ledger/   migration state (validated)
  .migration/harness/tools/, schemas/, patches/, installed.json        pinned harness tools
  .github/agents/afs-*.agent.md                                        role agents
  .github/skills/<name>/                                               built-in menu + stack pack, pinned
  .github/hooks/rtk-rewrite.json                                       RTK hook (RTK's own file)
  .github/hooks/afs-cost.json, afs-finish.json                         cost record; finish check (ADR-0021, 0034)
  .github/copilot-instructions.md                                      harness block, then RTK block (upserted)
  .github/workflows/copilot-setup-steps.yml, afs-harness-check.yml,
                    afs-understand.yml, afs-acceptance.yml             generated workflows
  .gitignore                                                           .source/, .migration/runs/, __pycache__/

Gap capabilities whose `ticket` is `new` become operator issues on the target repo
(`--create-gap-issues`, uses the `gh api` REST calls; set AFS_GH to use another executable). Without the flag, bootstrap
refuses to write a `new` ticket. Labels for the tracker are created with the same flag.

`--skip-private-sources` leaves out skills from sources the lock marks `private` (for CI without access).
`--offline` skips skills fetched from upstream (harness and vendored skills only); use it for local
dry runs, never for the setup PR. Needs git, network access to GitHub, jsonschema and pyyaml.
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_runtime  # noqa: E402
import check_installed  # noqa: E402
import validate  # noqa: E402

HARNESS_TOOLS = ["afs-run", "stack_refresh.py", "validate.py", "check_plan.py", "afs-finish-check", "crap.py", "check_installed.py", "extract_slice.py", "check_graph.py",
                 "understand.py", "check_domain_coverage.py", "check_return_contract.py", "afs-mutation", "check_inputs.py",
                 "afs-services", "check_runtime.py", "check_graph_fresh.py",
                 "enrich_graph.py", "graph_gate.py", "afs-cost-hook", "afs-costs",
                 "fog_rewalk.py", "check_slice_returns.py", "locks/graphify.lock",
                 "afs_trace.py", "harness_coverage.py", "ticket_guard.py", "check_stack_base.py", "afs-acceptance", "check_signoff.py", "afs-drill", "drills.json", "data_reconcile.py", "data_snapshot.py", "java/JdbcSnapshot.java", "preserve_graph.py"]
COPILOT_CLI_VERSION = "1.0.105"   # spike M1-1
COPILOT_SDK_VERSION = "1.0.28"
PIP_PACKAGES = "jsonschema pyyaml lizard"
DEFAULT_PYTHON = "3.12"   # when the profile declares no python-X.Y stack
BOOTSTRAP_LOCK = ".afs-bootstrap.lock"
TRANSACTION_PREFIX = ".afs-bootstrap-txn-"
TRANSACTION_MARKER = ".afs-bootstrap-transaction"
TRANSACTION_MARKER_CONTENT = "AI Factory Swarm bootstrap transaction\n"
PUBLISH_PATHS = (".github/skills", ".github/agents", ".github/workflows", ".github/hooks",
                 ".github/copilot-instructions.md", ".gitignore", ".migration/source.lock",
                 ".migration/profile.yaml", ".migration/capabilities.yaml", ".migration/ledger",
                 ".migration/harness")
BLOCKS = {
    "afs": ("<!-- afs-instructions v", "<!-- /afs-instructions -->"),
    "rtk": ("<!-- rtk-instructions v", "<!-- /rtk-instructions -->"),
}
LABELS = [
    ("wayfinder:map", "5319e7", "Decision map for the migration (wayfinder)"),
    ("wayfinder:research", "c5def5", "Decision ticket: research"),
    ("wayfinder:prototype", "c5def5", "Decision ticket: prototype"),
    ("wayfinder:grilling", "c5def5", "Decision ticket: needs a human ruling (incl. quirks)"),
    ("wayfinder:task", "c5def5", "Decision ticket: task"),
    ("afs:slice", "5319e7", "Slice epic: closing it opens a fog re-walk task on the decision map (ADR-0022)"),
    ("ready-for-agent", "0e8a16", "Slice ticket an agent can claim"),
    ("afs:capability-gap", "d93f0b", "Capability gap found by bootstrap; blocks Phase 2"),
]


OPERATOR_CHECKLIST = [
    "Merge the setup PR before dispatching any Copilot session: setup steps run only from the default branch, "
    "while a branch's hooks are live, so a session based on the unmerged setup branch has no RTK and its "
    "pre-tool hook blocks every tool call (synthetic target, SY-01)",
    "Actions enabled: allow all actions and reusable workflows",
    "Workflow permissions: allow GitHub Actions to create and approve pull requests",
    "Copilot coding agent enabled for this repository",
    "Copilot PR workflow runs: keep Require approval for workflow runs on (ADR-0039 default) and approve each push "
    "after checking its .github/ changes; turning it off needs ADR-0039's mitigations (one AFS_STACK_TOKEN per repo, "
    "main protected, read-only default workflow permissions)",
    "Public repo, or an Actions budget (Copilot sessions and CI use Actions minutes)",
    "Private source only: SOURCE_READ_TOKEN secret in Actions and in the `copilot` environment",
    "Dispatcher (L0 or you) has gh logged in as a user with write access",
    "Copilot firewall lets setup steps pull the compose images (add the registry to the allowlist if a session reports services DOWN)",
    "Sign-off: profile signoff.approvers names who approves slice sign-off PRs (ADR-0031); open those PRs from a login that isn't an approver",
    "Costs (optional): profile costs.billing names the account that pays for Copilot (user, organization or enterprise); BILLING_READ_TOKEN secret that can read that account's billing (docs/operator-setup.md, ADR-0021)",
    "Graph first: after this PR merges, run the afs-understand workflow (side=source) on main and merge its PR; graph_gate.py --side source --require-graph must pass before Phase 2 (ADR-0020)",
]


class BootstrapError(Exception):
    pass


class BootstrapLockError(BootstrapError):
    pass


# ---------- helpers ----------

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout


def fetch(repo, commit, cache):
    """Shallow-fetch `repo` at `commit` once per run. Tests replace this function."""
    if (repo, commit) not in cache:
        d = pathlib.Path(tempfile.mkdtemp(prefix="afs-src-"))
        run(["git", "init", "-q", str(d)])
        run(["git", "-C", str(d), "fetch", "-q", "--depth", "1", f"https://github.com/{repo}", commit])
        run(["git", "-C", str(d), "checkout", "-q", "FETCH_HEAD"])
        cache[(repo, commit)] = d
    return cache[(repo, commit)]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_of(root, rel):
    base = root / rel
    if base.is_file():
        return {rel: sha256(base)}
    return {str(p.relative_to(root)): sha256(p) for p in sorted(base.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode:
        path.chmod(mode)


@contextlib.contextmanager
def bootstrap_lock(target):
    target = pathlib.Path(target).resolve()
    path = target / BOOTSTRAP_LOCK
    lock = {"pid": os.getpid(),
            "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "token": uuid.uuid4().hex}
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
            pid = int(owner["pid"])
            if pid <= 0:
                raise ValueError("PID must be positive")
        except (OSError, ValueError, KeyError, TypeError):
            raise BootstrapLockError(
                f"bootstrap lock {path} exists but its owner cannot be read; verify no bootstrap is running "
                f"before removing it with: rm -f -- {shlex.quote(str(path))}") from exc
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            raise BootstrapLockError(
                f"stale bootstrap lock {path}: PID {pid} is not running; after confirming the target is idle, "
                f"clear it with: rm -f -- {shlex.quote(str(path))}; rerun bootstrap to recover any staged install"
            ) from exc
        except PermissionError:
            pass
        raise BootstrapLockError(
            f"bootstrap is already running for {target} (PID {pid}); wait for it to finish") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(json.dumps(lock) + "\n")
            lock_file.flush()
            os.fsync(lock_file.fileno())
        yield
    finally:
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
            if owner.get("token") == lock["token"]:
                path.unlink()
        except (FileNotFoundError, OSError, ValueError):
            pass


def _exists(path):
    return path.exists() or path.is_symlink()


def _remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif _exists(path):
        path.unlink()


def _save_transaction(path, transaction):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(transaction, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def _load_transaction(journal):
    try:
        transaction = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BootstrapError(f"cannot read interrupted bootstrap journal {journal}: {exc}") from exc
    if not isinstance(transaction, dict):
        raise BootstrapError(f"invalid interrupted bootstrap journal {journal}; leave it in place for inspection")
    valid_states = {"publishing", "committed"}
    state = transaction.get("state")
    outputs = transaction.get("outputs")
    if not isinstance(state, str) or state not in valid_states or not isinstance(outputs, list) \
            or len(outputs) != len(PUBLISH_PATHS):
        raise BootstrapError(f"invalid interrupted bootstrap journal {journal}; leave it in place for inspection")
    valid_statuses = {"pending", "publishing", "published"}
    for i, (entry, rel) in enumerate(zip(outputs, PUBLISH_PATHS)):
        status = entry.get("status") if isinstance(entry, dict) else None
        if (not isinstance(entry, dict) or entry.get("path") != rel or entry.get("backup") != str(i)
                or type(entry.get("had_old")) is not bool or not isinstance(status, str)
                or status not in valid_statuses):
            raise BootstrapError(f"invalid interrupted bootstrap journal {journal}; leave it in place for inspection")
    return transaction


def _publish_output(target, staging, backup, entry):
    destination = target / entry["path"]
    staged = staging / entry["path"]
    saved = backup / entry["backup"]
    if _exists(destination):
        saved.parent.mkdir(parents=True, exist_ok=True)
        os.replace(destination, saved)
    if _exists(staged):
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, destination)


def _rollback_transaction(target, transaction_dir):
    journal = transaction_dir / "transaction.json"
    transaction = _load_transaction(journal)
    errors = []
    for entry in reversed(transaction["outputs"]):
        destination = target / entry["path"]
        saved = transaction_dir / "backup" / entry["backup"]
        try:
            if _exists(saved):
                _remove(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(saved, destination)
            elif not entry["had_old"] and entry["status"] != "pending":
                _remove(destination)
        except OSError as exc:
            errors.append(f"{entry['path']}: {exc}")
    if errors:
        raise BootstrapError("could not restore the previous install; transaction journal remains at "
                             f"{journal}:\n  " + "\n  ".join(errors))
    shutil.rmtree(transaction_dir)


def recover_interrupted_install(target):
    """Roll back an incomplete publication or discard an unpublished staging directory."""
    target = pathlib.Path(target)
    for transaction_dir in sorted(target.glob(f"{TRANSACTION_PREFIX}*")):
        marker = transaction_dir / TRANSACTION_MARKER
        if transaction_dir.is_symlink() or not transaction_dir.is_dir():
            raise BootstrapError(f"unrecognized bootstrap transaction path {transaction_dir}; inspect it before "
                                 "removing it")
        try:
            is_ours = not marker.is_symlink() and marker.read_text(encoding="utf-8") == TRANSACTION_MARKER_CONTENT
        except (OSError, UnicodeDecodeError):
            is_ours = False
        if not is_ours:
            continue
        journal = transaction_dir / "transaction.json"
        if not journal.exists():
            shutil.rmtree(transaction_dir)
            continue
        transaction = _load_transaction(journal)
        if transaction.get("state") == "committed":
            try:
                shutil.rmtree(transaction_dir)
            except OSError as exc:
                raise BootstrapError(f"could not clean committed bootstrap transaction {transaction_dir}: {exc}") from exc
        else:
            _rollback_transaction(target, transaction_dir)


def publish_install(target, transaction_dir):
    """Publish staged paths individually; the journal permits rollback, not multi-path atomicity."""
    target = pathlib.Path(target)
    transaction_dir = pathlib.Path(transaction_dir)
    staging = transaction_dir / "stage"
    backup = transaction_dir / "backup"
    outputs = [{"path": rel, "backup": str(i), "had_old": _exists(target / rel), "status": "pending"}
               for i, rel in enumerate(PUBLISH_PATHS)]
    transaction = {"state": "publishing", "outputs": outputs}
    journal = transaction_dir / "transaction.json"
    _save_transaction(journal, transaction)
    try:
        for entry in outputs:
            entry["status"] = "publishing"
            _save_transaction(journal, transaction)
            _publish_output(target, staging, backup, entry)
            entry["status"] = "published"
            _save_transaction(journal, transaction)
        transaction["state"] = "committed"
        _save_transaction(journal, transaction)
    except BaseException as exc:
        try:
            _rollback_transaction(target, transaction_dir)
        except Exception as rollback_exc:
            raise BootstrapError(f"publication failed ({exc}); recovery is required: {rollback_exc}") from exc
        if isinstance(exc, Exception):
            raise BootstrapError(f"publication failed; previous install was restored: {exc}") from exc
        raise
    try:
        shutil.rmtree(transaction_dir)
    except OSError as exc:
        raise BootstrapError(f"install was published, but transaction cleanup failed at {transaction_dir}: {exc}; "
                             "the next bootstrap run will retry cleanup") from exc


def _copy_existing(source, destination):
    if source.is_dir():
        root = source.resolve() if source.is_symlink() else source
        shutil.copytree(root, destination, symlinks=True, dirs_exist_ok=True)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _seed_staging(target, staging):
    for rel in (".github/agents", ".github/workflows", ".github/hooks", ".migration/ledger",
                ".migration/returns", ".migration/evidence/runs",
                ".migration/harness/legacy-returns.json", ".github/copilot-instructions.md", ".gitignore"):
        _copy_existing(target / rel, staging / rel)


def frontmatter_name(skill_md):
    m = re.match(r"^---\n(.*?)\n---", skill_md.read_text(encoding="utf-8"), re.S)
    if not m:
        return None
    n = re.search(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", m.group(1), re.M)
    return n.group(1) if n else None


def harness_identity():
    version = yaml.safe_load((ROOT / "templates/migration/profile.yaml").read_text())["harness_version"]
    try:
        commit = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip()
        dirty = bool(run(["git", "-C", str(ROOT), "status", "--porcelain"]).strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit, dirty = "0" * 40, True
    return version, commit, dirty


def upsert_block(text, key, block):
    """Insert or replace one marked block; content outside the markers is preserved."""
    start, end = BLOCKS[key]
    block = block.strip("\n") + "\n"
    m = re.search(re.escape(start) + r".*?" + re.escape(end) + r"\n?", text, re.S)
    if m:
        return text[:m.start()] + block + text[m.end():]
    if key == "afs":  # harness block goes first (ADR-0015)
        return block + ("\n" + text if text.strip() else "")
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + block


# ---------- steps ----------

def load_inputs(profile_path, caps_path):
    errors = []
    schemas = ROOT / "schemas"
    profile = validate.check(validate.load_schema(schemas, "profile.schema.json"), profile_path, errors)
    caps = validate.check(validate.load_schema(schemas, "capabilities.schema.json"), caps_path, errors)
    if errors:
        raise BootstrapError("invalid inputs:\n  " + "\n  ".join(errors))
    return profile, caps


def plan_skills(lock, packs, offline, skip_private=False):
    """Every skill to install: (name, origin, source dict|None, path)."""
    plan, seen = [], {}
    for origin, l in [("menu", lock)] + [(f"stack:{p['stack']}", p) for p in packs]:
        for s in l["skills"]:
            if s["name"] in seen:
                raise BootstrapError(f"skill {s['name']} is in both {seen[s['name']]} and {origin}")
            seen[s["name"]] = origin
            if s["install"] == "upstream" and offline:
                continue
            if skip_private and s["install"] == "upstream" and l["sources"][s["source"]].get("private"):
                continue
            src = l["sources"][s["source"]] if s["install"] == "upstream" else None
            plan.append({"name": s["name"], "origin": origin, "install": s["install"], "source": src,
                         "source_key": s.get("source"), "path": s["path"], "roles": s.get("roles", []),
                         "status": s.get("status"), "license": s.get("license")})
    return plan


def install_skills(target, plan, cache, notes):
    dest_root = target / ".github/skills"
    if dest_root.exists():  # harness-owned folder: a re-run replaces it whole
        shutil.rmtree(dest_root)
    for s in plan:
        dest = dest_root / s["name"]
        if s["install"] == "harness":
            shutil.copytree(ROOT / s["path"], dest)
            continue
        if s["install"] == "vendored":  # committed afs- copy with its own PROVENANCE.md and LICENSE
            shutil.copytree(ROOT / "skills" / s["name"], dest)
            continue
        src = s["source"]
        repo_dir = fetch(src["repo"], src["commit"], cache)
        shutil.copytree(repo_dir / s["path"], dest, ignore=shutil.ignore_patterns(".git"))
        fm = frontmatter_name(dest / "SKILL.md")
        if fm != s["name"]:
            notes.append(f"skill {s['name']}: upstream frontmatter name is {fm!r}")
        license_note = s.get("license") or src["license"]
        if not (dest / "LICENSE").exists() and (repo_dir / "LICENSE").exists():
            shutil.copyfile(repo_dir / "LICENSE", dest / "LICENSE")
        if s.get("status") == "needs-license":
            license_note = "none declared upstream yet (the author's own skill; license pending)"
            notes.append(f"skill {s['name']}: needs a license before it ships publicly")
        write(dest / "PROVENANCE.md",
              f"# Provenance: {s['name']}\n\n"
              f"- Upstream: [{src['repo']}](https://github.com/{src['repo']}/tree/{src['commit']}/{s['path']})\n"
              f"- Commit: `{src['commit']}`\n"
              f"- License: {license_note}\n"
              f"- Installed by AI Factory Swarm bootstrap ({s['origin']}); unchanged except this file"
              f"{' and the upstream LICENSE' if (dest / 'LICENSE').exists() and not (repo_dir / s['path'] / 'LICENSE').exists() else ''}.\n")


LEGACY_RETURNS = ".migration/harness/legacy-returns.json"


def legacy_returns(target):
    """Return files committed before ADR-0017 (journal missing or without a Result column).

    Written once, at the first install that knows the rule, and kept as-is by later installs, so a return
    added afterwards can never become exempt. check_installed keeps it unchanged."""
    existing = target / LEGACY_RETURNS
    if existing.exists():
        return existing.read_text(encoding="utf-8")
    names = []
    for ret in sorted((target / ".migration/returns").glob("*.y*ml")):
        journal = target / ".migration/evidence/runs" / f"{ret.name.split('.')[0]}.md"
        if not journal.exists() or "| Result |" not in journal.read_text(encoding="utf-8"):
            names.append(ret.name)
    return json.dumps({"rule": "ADR-0017", "returns": names}, indent=2) + "\n"


def install_harness(target, lock):
    h = target / ".migration/harness"
    legacy = legacy_returns(target)
    if h.exists():
        shutil.rmtree(h)
    write(target / LEGACY_RETURNS, legacy)
    for t in HARNESS_TOOLS:
        dst = h / "tools" / t
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "tools" / t, dst)
        dst.chmod(0o755)
    shutil.copytree(ROOT / "schemas", h / "schemas")
    for plugin in lock.get("plugins", []):
        for p in plugin.get("patches", []):
            dst = h / "patches" / p
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "patches" / p, dst)


def install_agents(target):
    d = target / ".github/agents"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("afs-*.agent.md"):
        old.unlink()
    for a in sorted((ROOT / "agents").glob("afs-*.agent.md")):
        shutil.copyfile(a, d / a.name)


def write_state(target, profile, profile_path, caps_doc):
    m = target / ".migration"
    write(m / "source.lock",
          f"# Pinned, read-only migration source. Written by bootstrap; change only through a new setup PR.\n"
          f"repo: {profile['source']['repo']}\nsha: {profile['source']['sha']}\npath: {profile['source'].get('path', '')}\n")
    if not (m / "profile.yaml").exists() or not (m / "profile.yaml").samefile(profile_path):
        shutil.copyfile(profile_path, m / "profile.yaml")
    write(m / "capabilities.yaml",
          "# Capability checklist (ADR-0012), written by bootstrap. A gap blocks Phase 2 until its ticket is resolved.\n"
          + yaml.safe_dump(caps_doc, sort_keys=False, allow_unicode=True, width=110))
    (m / "ledger").mkdir(exist_ok=True)
    if not any((m / "ledger").iterdir()):
        write(m / "ledger/.gitkeep", "")


def write_copilot_files(target, lock, version, commit, profile=None):
    rtk = lock["tools"][0]
    ua_src = lock["sources"]["understand-anything"]
    patches = [p for pl in lock.get("plugins", []) for p in pl.get("patches", [])]
    ua_patch_steps = "\n".join(
        f'          git -C "$ua" apply "$GITHUB_WORKSPACE/.migration/harness/patches/{p}"' for p in patches)
    fmt = dict(harness_version=version, harness_commit_short=commit[:7], rtk_version=rtk["version"],
               rtk_repo=rtk["repo"], rtk_asset=rtk["asset"], python_version=check_runtime.python_version(profile or {}, DEFAULT_PYTHON),
               pip_packages=PIP_PACKAGES, ua_repo=ua_src["repo"], ua_commit=ua_src["commit"],
               ua_commit_short=ua_src["commit"][:7], ua_patch_steps=ua_patch_steps,
               project_marker="manage.py", copilot_cli_version=COPILOT_CLI_VERSION,
               copilot_sdk_version=COPILOT_SDK_VERSION)
    tpl = ROOT / "templates/target"
    for name in ("copilot-setup-steps.yml", "afs-harness-check.yml", "afs-understand.yml", "afs-acceptance.yml", "afs-costs.yml",
                 "afs-map-fog.yml", "afs-ticket-guard.yml", "afs-signoff.yml", "afs-snapshot.yml", "afs-stack-refresh.yml"):
        write(target / ".github/workflows" / name, (tpl / name).read_text(encoding="utf-8").format(**fmt))
    (target / ".github/hooks").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "templates/rtk/rtk-rewrite.json", target / ".github/hooks/rtk-rewrite.json")
    shutil.copyfile(ROOT / "templates/hooks/afs-cost.json", target / ".github/hooks/afs-cost.json")   # ADR-0021
    shutil.copyfile(ROOT / "templates/hooks/afs-finish.json", target / ".github/hooks/afs-finish.json")   # ADR-0034
    ci = target / ".github/copilot-instructions.md"
    text = ci.read_text(encoding="utf-8") if ci.exists() else ""
    text = upsert_block(text, "afs", (tpl / "afs-instructions.md").read_text(encoding="utf-8"))
    text = upsert_block(text, "rtk", (ROOT / "templates/rtk/copilot-instructions-block.md").read_text(encoding="utf-8"))
    write(ci, text)


def merge_gitignore(target):
    gi = target / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    for entry in (".source/", ".migration/runs/", ".migration/data/snapshot/", ".migration/data/target-export/",   # ADR-0032: data never committed
                  "__pycache__/"):   # synthetic SY-01: a session committed the harness tools' bytecode
        if entry not in lines:
            lines.append(entry)
    write(gi, "\n".join(lines) + "\n")


def write_manifest(target, version, commit, plan):
    entries = [{"path": f".github/agents/{a.name}", "kind": "agent"} for a in sorted((target / ".github/agents").glob("afs-*.agent.md"))]
    entries += [{"path": f".github/skills/{s['name']}", "kind": "skill", "origin": s["origin"],
                 "install": s["install"],
                 **({"repo": s["source"]["repo"], "commit": s["source"]["commit"], "upstream_path": s["path"]}
                    if s["source"] else {})} for s in plan]
    entries += [{"path": ".github/hooks/rtk-rewrite.json", "kind": "hook"},
                {"path": ".github/hooks/afs-cost.json", "kind": "hook"},
                {"path": ".github/hooks/afs-finish.json", "kind": "hook"},
                {"path": ".migration/harness/tools", "kind": "tools"},
                {"path": ".migration/harness/schemas", "kind": "schemas"},
                {"path": LEGACY_RETURNS, "kind": "legacy"}]
    if (target / ".migration/harness/patches").exists():
        entries.append({"path": ".migration/harness/patches", "kind": "patches"})
    for e in entries:
        e["files"] = files_of(target, e["path"])
    write(target / ".migration/harness/installed.json", json.dumps(
        {"harness_version": version, "harness_commit": commit,
         "installed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "entries": entries}, indent=2) + "\n")


def gh(*args):
    return run([os.environ.get("AFS_GH", "gh"), *args])


def open_gap_issues(caps_doc, target_repo):
    created = []
    for c in caps_doc["capabilities"]:
        if c["status"] != "gap" or c.get("ticket") != "new":
            continue
        body = (f"Bootstrap found a **capability gap**: `{c['id']}` ({c['applies_to']}).\n\n"
                f"{c.get('notes', '').strip()}\n\n"
                "**Blocks Phase 2** until resolved (ADR-0012). Resolve it by one of:\n"
                "- pinning a skill or tool that provides it (harness PR to the skill lock or a stack pack), or\n"
                "- writing a skill for it (e.g. with `skill-creator`), or\n"
                "- recording an approved waiver in `.migration/capabilities.yaml`.\n\n"
                "Then set its status in `.migration/capabilities.yaml` and close this issue.\n")
        url = gh("api", f"repos/{target_repo}/issues", "--method", "POST",
                 "-f", f"title=Capability gap: {c['id']} ({c['applies_to']})", "-f", f"body={body}",
                 "-f", "labels[]=afs:capability-gap", "--jq", ".html_url").strip().splitlines()[-1]
        m = re.search(r"github\.com/([^/]+/[^/]+)/issues/(\d+)", url)
        if not m:
            raise BootstrapError(f"could not parse issue URL from gh output: {url!r}")
        c["ticket"] = f"{m.group(1)}#{m.group(2)}"
        created.append(c["ticket"])
    return created


def ensure_labels(target_repo):
    """Create or update the tracker labels (REST only: the GraphQL API may be unavailable)."""
    existing = set(gh("api", f"repos/{target_repo}/labels", "--paginate", "--jq", ".[].name").split("\n"))
    for name, color, desc in LABELS:
        if name in existing:
            gh("api", f"repos/{target_repo}/labels/{name}", "--method", "PATCH",
               "-f", f"color={color}", "-f", f"description={desc}")
        else:
            gh("api", f"repos/{target_repo}/labels", "--method", "POST",
               "-f", f"name={name}", "-f", f"color={color}", "-f", f"description={desc}")


def check_profile_services(profile, target):
    """The profile's test services must name a compose file the target has: every CI job and Copilot setup
    step starts them, so a missing file fails the setup PR's every check (synthetic target, SY-01)."""
    services = (profile or {}).get("services")
    if not services:
        return
    compose = pathlib.Path(target) / services.get("compose", "")
    if not compose.is_file():
        raise BootstrapError(f"profile services.compose names {services.get('compose')!r}, which the target "
                             f"doesn't have. Write the test services first (afs-bootstrapper step 4, with "
                             f"docker-compose-orchestration); CI and Copilot setup steps start them")


def check_release(allow_unreleased):
    """Install only what is on the harness's main branch, committed: an installed.json naming a branch commit
    or a dirty tree can't be reproduced, and an unmerged change reaches a target unreviewed."""
    if allow_unreleased:
        return
    _, commit, dirty = harness_identity()
    if dirty:
        raise BootstrapError("the harness checkout has uncommitted changes; commit them (or check out main) "
                             "before installing, or pass --allow-unreleased for a throwaway target")
    try:
        run(["git", "-C", str(ROOT), "fetch", "--quiet", "origin", "main"])
        on_main = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, "FETCH_HEAD"],
                                 capture_output=True).returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        on_main = False
    if not on_main:
        raise BootstrapError(f"harness commit {commit[:7]} isn't on origin/main; check out main (an unmerged "
                             f"branch must not reach a target), or pass --allow-unreleased for a throwaway target")


def check_profile_graph(profile, packs):
    """ADR-0020: a stack pack's graph enrichers and required types must be in the profile, explicitly."""
    graph = profile.get("graph") or {}
    for pack in packs:
        want = pack.get("graph") or {}
        for side, enrichers in (want.get("enrich") or {}).items():
            have = set((graph.get("enrich") or {}).get(side) or [])
            if not set(enrichers) <= have:
                raise BootstrapError(f"profile graph.enrich.{side} must include {enrichers} (stack pack "
                                     f"{pack.get('stack')}, ADR-0020); without them the {side} graph has no "
                                     "tables, routes or data links")
        for side, types in (want.get("require") or {}).items():
            have = (graph.get("require") or {}).get(side) or {}
            for kind in ("nodes", "edges"):
                lacking = sorted(set(types.get(kind) or []) - set(have.get(kind) or []))
                if lacking:
                    raise BootstrapError(f"profile graph.require.{side}.{kind} must include {lacking} (stack pack "
                                         f"{pack.get('stack')}, ADR-0020)")


def check_profile_skills(profile, installed, offline):
    refs = []

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            refs.extend((where, n) for n in node)
    walk(profile.get("skills", {}), "skills")
    missing = [f"{w}: {n}" for w, n in refs if n not in installed]
    if missing and not offline:
        raise BootstrapError("profile references skills that are not installed:\n  " + "\n  ".join(missing))
    return missing


# ---------- main ----------

def bootstrap(target, profile_path, caps_path, pack_paths=(), create_gap_issues=False, offline=False,
              skip_private=False):
    target = pathlib.Path(target)
    if not target.is_dir():
        raise BootstrapError(f"target {target} is not a directory")
    with bootstrap_lock(target):
        recover_interrupted_install(target)
        return _bootstrap_locked(target, profile_path, caps_path, pack_paths, create_gap_issues, offline,
                                 skip_private)


def _bootstrap_locked(target, profile_path, caps_path, pack_paths, create_gap_issues, offline, skip_private):
    profile, caps = load_inputs(profile_path, caps_path)
    check_profile_services(profile, target)
    caps_doc = yaml.safe_load(pathlib.Path(caps_path).read_text(encoding="utf-8"))
    new_gaps = [c["id"] for c in caps_doc["capabilities"] if c["status"] == "gap" and c.get("ticket") == "new"]
    if new_gaps and not create_gap_issues:
        raise BootstrapError(f"gap(s) {', '.join(new_gaps)} have ticket 'new'; rerun with --create-gap-issues "
                             "or give an existing ticket")
    lock = json.loads((ROOT / "skills.lock.json").read_text(encoding="utf-8"))
    packs = [json.loads(pathlib.Path(p).read_text(encoding="utf-8")) for p in pack_paths]
    plan = plan_skills(lock, packs, offline, skip_private)
    check_profile_graph(profile, packs)
    missing = check_profile_skills(profile, {s["name"] for s in plan}, offline)
    version, commit, dirty = harness_identity()
    notes = [f"harness has uncommitted changes; installed.json records {commit[:7]}"] if dirty else []
    if missing:
        notes.append(f"offline: {len(missing)} profile skill reference(s) not installed")

    transaction_dir = pathlib.Path(tempfile.mkdtemp(prefix=TRANSACTION_PREFIX, dir=target))
    staging = transaction_dir / "stage"
    cache = {}
    try:
        (transaction_dir / TRANSACTION_MARKER).write_text(TRANSACTION_MARKER_CONTENT, encoding="utf-8")
        staging.mkdir()
        _seed_staging(target, staging)
    except BaseException:
        shutil.rmtree(transaction_dir, ignore_errors=True)
        raise
    try:
        install_skills(staging, plan, cache, notes)
        install_harness(staging, lock)
        install_agents(staging)
        write_copilot_files(staging, lock, version, commit, profile)
        merge_gitignore(staging)
        write_manifest(staging, version, commit, plan)

        created = []
        if create_gap_issues:
            ensure_labels(profile["target"]["repo"])
            created = open_gap_issues(caps_doc, profile["target"]["repo"])
        caps_doc["checked_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_state(staging, profile, profile_path, caps_doc)

        errors = []
        validate.check(validate.load_schema(ROOT / "schemas", "capabilities.schema.json"),
                       staging / ".migration/capabilities.yaml", errors)
        if errors:
            raise BootstrapError("staged capabilities.yaml is invalid:\n  " + "\n  ".join(errors))
        _, problems = check_installed.check(staging)
        if problems:
            raise BootstrapError("staged install failed its drift check:\n  " + "\n  ".join(problems))

        publish_install(target, transaction_dir)
    except BaseException:
        if transaction_dir.exists() and not (transaction_dir / "transaction.json").exists():
            shutil.rmtree(transaction_dir, ignore_errors=True)
        raise
    finally:
        # fetch() checks each upstream out into its own temp folder; remove them (one run left 13, ~260 MB).
        for d in cache.values():
            if isinstance(d, pathlib.Path) and d.name.startswith("afs-src-"):
                shutil.rmtree(d, ignore_errors=True)
    gaps = [f"{c['id']} → {c.get('ticket')}" for c in caps_doc["capabilities"] if c["status"] == "gap"]
    return {"skills": len(plan), "agents": len(list((target / ".github/agents").glob("afs-*.agent.md"))),
            "gaps": gaps, "issues_created": created, "notes": notes, "harness": f"{version} ({commit[:7]})"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--capabilities", required=True)
    ap.add_argument("--stack-pack", action="append", default=[])
    ap.add_argument("--create-gap-issues", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--skip-private-sources", action="store_true",
                    help="leave out skills from sources the lock marks private (CI without access)")
    ap.add_argument("--allow-unreleased", action="store_true",
                    help="install from a harness commit that isn't on origin/main, or a dirty tree (tests, CI)")
    a = ap.parse_args()
    try:
        check_release(a.allow_unreleased)
        r = bootstrap(a.target, a.profile, a.capabilities, a.stack_pack, a.create_gap_issues, a.offline,
                      a.skip_private_sources)
    except BootstrapError as e:
        print(f"bootstrap: {e}", file=sys.stderr)
        return 2 if isinstance(e, BootstrapLockError) else 1
    print(f"harness {r['harness']}: {r['agents']} agents, {r['skills']} skills installed")
    for g in r["gaps"]:
        print(f"gap: {g}")
    for n in r["notes"]:
        print(f"note: {n}")
    print("operator: repository settings bootstrap cannot make are listed in "
          "https://github.com/martins-vds/ai-factory-swarm/blob/main/docs/operator-setup.md:")
    for line in OPERATOR_CHECKLIST:
        print(f"  [ ] {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
