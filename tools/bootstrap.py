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
  .github/copilot-instructions.md                                      harness block, then RTK block (upserted)
  .github/workflows/copilot-setup-steps.yml, afs-harness-check.yml,
                    afs-understand.yml                                 generated workflows
  .gitignore                                                           .source/, .migration/runs/

Gap capabilities whose `ticket` is `new` become operator issues on the target repo
(`--create-gap-issues`, uses the `gh api` REST calls; set AFS_GH to use another executable). Without the flag, bootstrap
refuses to write a `new` ticket. Labels for the tracker are created with the same flag.

`--skip-private-sources` leaves out skills from sources the lock marks `private` (for CI without access).
`--offline` skips skills fetched from upstream (harness and vendored skills only); use it for local
dry runs, never for the setup PR. Needs git, network access to GitHub, jsonschema and pyyaml.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import validate  # noqa: E402

HARNESS_TOOLS = ["afs-run", "validate.py", "crap.py", "check_installed.py", "extract_slice.py", "check_graph.py",
                 "understand.py", "check_return_contract.py"]
COPILOT_CLI_VERSION = "1.0.105"   # spike M1-1
COPILOT_SDK_VERSION = "1.0.28"
PIP_PACKAGES = "jsonschema pyyaml lizard"
PYTHON_VERSION = "3.12"
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
    ("ready-for-agent", "0e8a16", "Slice ticket an agent can claim"),
    ("afs:capability-gap", "d93f0b", "Capability gap found by bootstrap; blocks Phase 2"),
]


class BootstrapError(Exception):
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
    return {str(p.relative_to(root)): sha256(p) for p in sorted(base.rglob("*")) if p.is_file()}


def write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode:
        path.chmod(mode)


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


def install_harness(target, lock):
    h = target / ".migration/harness"
    if h.exists():
        shutil.rmtree(h)
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


def write_copilot_files(target, lock, version, commit):
    rtk = lock["tools"][0]
    ua_src = lock["sources"]["understand-anything"]
    patches = [p for pl in lock.get("plugins", []) for p in pl.get("patches", [])]
    ua_patch_steps = "\n".join(
        f'          git -C "$ua" apply "$GITHUB_WORKSPACE/.migration/harness/patches/{p}"' for p in patches)
    fmt = dict(harness_version=version, harness_commit_short=commit[:7], rtk_version=rtk["version"],
               rtk_repo=rtk["repo"], rtk_asset=rtk["asset"], python_version=PYTHON_VERSION,
               pip_packages=PIP_PACKAGES, ua_repo=ua_src["repo"], ua_commit=ua_src["commit"],
               ua_commit_short=ua_src["commit"][:7], ua_patch_steps=ua_patch_steps,
               project_marker="manage.py", copilot_cli_version=COPILOT_CLI_VERSION,
               copilot_sdk_version=COPILOT_SDK_VERSION)
    tpl = ROOT / "templates/target"
    for name in ("copilot-setup-steps.yml", "afs-harness-check.yml", "afs-understand.yml"):
        write(target / ".github/workflows" / name, (tpl / name).read_text(encoding="utf-8").format(**fmt))
    (target / ".github/hooks").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "templates/rtk/rtk-rewrite.json", target / ".github/hooks/rtk-rewrite.json")
    ci = target / ".github/copilot-instructions.md"
    text = ci.read_text(encoding="utf-8") if ci.exists() else ""
    text = upsert_block(text, "afs", (tpl / "afs-instructions.md").read_text(encoding="utf-8"))
    text = upsert_block(text, "rtk", (ROOT / "templates/rtk/copilot-instructions-block.md").read_text(encoding="utf-8"))
    write(ci, text)


def merge_gitignore(target):
    gi = target / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    for entry in (".source/", ".migration/runs/"):
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
                {"path": ".migration/harness/tools", "kind": "tools"},
                {"path": ".migration/harness/schemas", "kind": "schemas"}]
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
    profile, caps = load_inputs(profile_path, caps_path)
    caps_doc = yaml.safe_load(pathlib.Path(caps_path).read_text(encoding="utf-8"))
    new_gaps = [c["id"] for c in caps_doc["capabilities"] if c["status"] == "gap" and c.get("ticket") == "new"]
    if new_gaps and not create_gap_issues:
        raise BootstrapError(f"gap(s) {', '.join(new_gaps)} have ticket 'new'; rerun with --create-gap-issues "
                             "or give an existing ticket")
    lock = json.loads((ROOT / "skills.lock.json").read_text(encoding="utf-8"))
    packs = [json.loads(pathlib.Path(p).read_text(encoding="utf-8")) for p in pack_paths]
    plan = plan_skills(lock, packs, offline, skip_private)
    missing = check_profile_skills(profile, {s["name"] for s in plan}, offline)
    version, commit, dirty = harness_identity()
    notes = [f"harness has uncommitted changes; installed.json records {commit[:7]}"] if dirty else []
    if missing:
        notes.append(f"offline: {len(missing)} profile skill reference(s) not installed")

    install_skills(target, plan, {}, notes)
    install_harness(target, lock)
    install_agents(target)
    write_copilot_files(target, lock, version, commit)
    merge_gitignore(target)
    write_manifest(target, version, commit, plan)

    created = []
    if create_gap_issues:
        ensure_labels(profile["target"]["repo"])
        created = open_gap_issues(caps_doc, profile["target"]["repo"])
    caps_doc["checked_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_state(target, profile, profile_path, caps_doc)

    errors = []
    validate.check(validate.load_schema(ROOT / "schemas", "capabilities.schema.json"),
                   target / ".migration/capabilities.yaml", errors)
    if errors:
        raise BootstrapError("written capabilities.yaml is invalid:\n  " + "\n  ".join(errors))
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
    a = ap.parse_args()
    try:
        r = bootstrap(a.target, a.profile, a.capabilities, a.stack_pack, a.create_gap_issues, a.offline,
                      a.skip_private_sources)
    except BootstrapError as e:
        print(f"bootstrap: {e}", file=sys.stderr)
        return 1
    print(f"harness {r['harness']}: {r['agents']} agents, {r['skills']} skills installed")
    for g in r["gaps"]:
        print(f"gap: {g}")
    for n in r["notes"]:
        print(f"note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
