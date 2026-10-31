#!/usr/bin/env python3
"""Vendor the model-invocable `afs-` copies of user-invoked upstream skills (ADR-0003).

For every skill in skills.lock.json with `"install": "vendored"`:
  * fetch its upstream folder at the pinned commit,
  * copy it to skills/<name>/,
  * rewrite SKILL.md frontmatter: `name: <name>`, drop `disable-model-invocation`,
  * add a one-line provenance note under the frontmatter, PROVENANCE.md, and the upstream LICENSE.

Usage:
  vendor_skills.py            write/refresh skills/<name>/ for all vendored skills
  vendor_skills.py --check    regenerate in a temp folder and fail if the committed copies differ (CI drift check)
Needs git and network access to GitHub.
"""
import argparse
import filecmp
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def fetch(repo, commit, cache):
    if repo not in cache:
        d = pathlib.Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "fetch", "-q", "--depth", "1", f"https://github.com/{repo}", commit],
                       check=True)
        subprocess.run(["git", "-C", str(d), "checkout", "-q", "FETCH_HEAD"], check=True)
        cache[repo] = d
    return cache[repo]


def transform(skill_md, name, repo, commit, path):
    m = re.match(r"^---\n(.*?)\n---\n", skill_md, re.S)
    if not m:
        raise ValueError(f"{repo}/{path}/SKILL.md has no frontmatter")
    fm = [l for l in m.group(1).splitlines() if not l.startswith("disable-model-invocation:")]
    fm = [f"name: {name}" if l.startswith("name:") else l for l in fm]
    note = (f"\n> Vendored by AI Factory Swarm from [{repo}](https://github.com/{repo}/tree/{commit}/{path}) "
            f"at `{commit[:7]}` (see PROVENANCE.md). Changes: renamed to `{name}`; model invocation enabled "
            f"so unattended role agents can run it.\n")
    return "---\n" + "\n".join(fm) + "\n---\n" + note + skill_md[m.end():]


def build(lock, out_root, cache):
    sources = lock["sources"]
    built = []
    for s in lock["skills"]:
        if s.get("install") != "vendored":
            continue
        src = sources[s["source"]]
        repo_dir = fetch(src["repo"], src["commit"], cache)
        upstream = repo_dir / s["path"]
        dest = out_root / s["name"]
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(upstream, dest)
        md = dest / "SKILL.md"
        md.write_text(transform(md.read_text(encoding="utf-8"), s["name"], src["repo"], src["commit"], s["path"]),
                      encoding="utf-8")
        shutil.copyfile(repo_dir / "LICENSE", dest / "LICENSE")
        (dest / "PROVENANCE.md").write_text(
            f"# Provenance: {s['name']}\n\n"
            f"- Upstream: [{src['repo']}](https://github.com/{src['repo']}) — `{s['path']}`\n"
            f"- Commit: `{src['commit']}`\n"
            f"- License: {src['license']} (copied to `LICENSE`)\n"
            f"- Changes: frontmatter `name` set to `{s['name']}`; `disable-model-invocation` removed; a provenance "
            f"note added under the frontmatter. Everything else is byte-identical to upstream.\n"
            f"- Regenerate with `tools/vendor_skills.py`; CI runs `--check` to detect drift.\n",
            encoding="utf-8")
        built.append(s["name"])
    return built


def same_tree(a, b):
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(same_tree(a / d, b / d) for d in cmp.common_dirs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    lock = json.loads((ROOT / "skills.lock.json").read_text(encoding="utf-8"))
    cache = {}
    if not a.check:
        print("vendored:", ", ".join(build(lock, ROOT / "skills", cache)))
        return 0
    tmp = pathlib.Path(tempfile.mkdtemp())
    drift = [n for n in build(lock, tmp, cache) if not (ROOT / "skills" / n).exists() or not same_tree(tmp / n, ROOT / "skills" / n)]
    if drift:
        print("drift in vendored skills (run tools/vendor_skills.py):", ", ".join(drift), file=sys.stderr)
        return 1
    print("vendored skills match their pinned upstream")
    return 0


if __name__ == "__main__":
    sys.exit(main())
