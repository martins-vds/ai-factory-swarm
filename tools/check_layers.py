#!/usr/bin/env python3
"""The layering gate: check imports against the layer contracts the target's architecture ADRs state (phase 3e).

The contracts live in the profile, under `layering:` (schemas/profile.schema.json):

    layering:
      source_root: src       # module names are paths under this folder; "." (the default) is the repo root
      contracts:
        - name: use cases stay free of web and persistence
          adr: ADR-0001
          files: ["src/cargotracker/*/application/**/*.py"]
          forbid: ["django.http", "django.shortcuts", "cargotracker.*.infrastructure"]
          allow: []          # optional: modules that are exempt, though a forbid pattern matches them
          except_files: []   # optional: files the contract doesn't cover (a composition module)
      known:                 # optional: violations that predate the contract, each with what will remove it
        - file: src/cargotracker/booking/application/routing.py
          module: django.http
          reason: pilot BK-05F verify finding; fix ticket to be planned

A file that a contract's `files` globs match may not import a module that a `forbid` pattern matches.
- A pattern matches a module or any module under it: `django.http` matches `django.http.response`.
- Patterns use shell wildcards on dotted names.
- `from x import y` counts as importing both `x` and `x.y`, so `from django import http` is caught.
- Relative imports resolve against the file's package: a file's module name is its path under `source_root`.
- A `known` violation is reported but doesn't fail, so a contract can start strict on new code while old debt
  stays named. A known entry that no longer occurs is reported, to be removed.
- Imports guarded by `if TYPE_CHECKING:` are skipped. They are type-only and never run.

Why a tool: in eval baseline b3c the Verifier missed every import-level layering defect it was shown (a use case
raising Http404; a use case calling the framework clock and the ORM; a view calling the repository). A tool
finds these every time, so the Migrator can't commit one and the Verifier's review covers what a tool can't see.

Usage: check_layers.py [--root <repo>] [--profile <.migration/profile.yaml>]
Runs in the idiom gate. Exits 1 on a violation that isn't known, 2 on a bad contract; with no `layering:`, it passes.
"""
import argparse
import ast
import fnmatch
import pathlib
import re

import yaml


def module_name(path, source_root):
    """Dotted module name of a .py file under the source root (None outside it)."""
    try:
        rel = path.relative_to(source_root)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def is_package(path):
    return path.name == "__init__.py"


def resolve(level, module, own, package):
    """Absolute name of `from <.. level><module> import ...` in module `own`."""
    if not level:
        return module or ""
    base = own.split(".") if package else own.split(".")[:-1]
    base = base[: len(base) - (level - 1)] if level > 1 else base
    return ".".join([*base, module] if module else base)


def type_checking_nodes(tree):
    """Ids of import nodes inside `if TYPE_CHECKING:` (or `typing.TYPE_CHECKING`) blocks."""
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = test.id if isinstance(test, ast.Name) else test.attr if isinstance(test, ast.Attribute) else None
            if name == "TYPE_CHECKING":
                for inner in node.body:
                    for sub in ast.walk(inner):
                        if isinstance(sub, (ast.Import, ast.ImportFrom)):
                            skip.add(id(sub))
    return skip


def imports(path, own):
    """[(line, module)] for every import in a file, `from x import y` giving both x and x.y."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = type_checking_nodes(tree)
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Import):
            out += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = resolve(node.level, node.module, own, is_package(path))
            out.append((node.lineno, base))
            out += [(node.lineno, f"{base}.{alias.name}" if base else alias.name)
                    for alias in node.names if alias.name != "*"]
    return out


def matches(module, pattern):
    return fnmatch.fnmatchcase(module, pattern) or fnmatch.fnmatchcase(module, pattern + ".*")


def glob_regex(pattern):
    """A path glob as a regex: `**/` spans any folders (or none), `*` stays within one folder."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def glob_match(rel, pattern):
    return bool(glob_regex(pattern).match(rel))


def config_errors(layering):
    if not isinstance(layering, dict):
        return ["`layering` must be a mapping with `contracts` (and optionally `source_root` and `known`)"]
    errs = []
    contracts = layering.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        errs.append("`layering.contracts` must list at least one contract")
    for i, c in enumerate(contracts or []):
        if not isinstance(c, dict) or not c.get("name") or not c.get("files") or not c.get("forbid"):
            errs.append(f"layering.contracts[{i}]: a contract needs `name`, `files` and `forbid`")
    for i, k in enumerate(layering.get("known") or []):
        if not isinstance(k, dict) or not k.get("file") or not k.get("module") or not k.get("reason"):
            errs.append(f"layering.known[{i}]: a known violation needs `file`, `module` and `reason` "
                        "(the ticket or ruling that will remove it)")
    return errs


def check(root, contracts, source_root="."):
    """[(path, line, module, message)] for every forbidden import."""
    root = pathlib.Path(root).resolve()
    src_root = (root / source_root).resolve()
    files = sorted(p for p in root.rglob("*.py")
                   if not {".git", ".venv", "venv", "node_modules", ".migration", "__pycache__"} & set(
                       p.relative_to(root).parts))
    found = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        mine = [c for c in contracts
                if any(glob_match(rel, g) for g in c["files"])
                and not any(glob_match(rel, g) for g in c.get("except_files") or [])]
        if not mine:
            continue
        own = module_name(path, src_root) or ""
        try:
            imported = imports(path, own)
        except SyntaxError as exc:
            found.append((rel, exc.lineno or 0, "", f"can't parse: {exc.msg}"))
            continue
        for c in mine:
            worst = {}                   # (line, pattern) -> the most specific module it matched
            for line, module in imported:
                if any(matches(module, a) for a in c.get("allow") or []):
                    continue
                hit = next((p for p in c["forbid"] if matches(module, p)), None)
                if hit and len(module) > len(worst.get((line, hit), "")):
                    worst[(line, hit)] = module
            adr = f" ({c['adr']})" if c.get("adr") else ""
            for (line, hit), module in sorted(worst.items()):
                found.append((rel, line, module, f"{c['name']}{adr}: imports `{module}`, which `{hit}` forbids"))
    return found


def split_known(found, known):
    """(new violations, known ones, known entries that matched nothing)."""
    hit = set()
    new, old = [], []
    for v in found:
        rel, _, module, _ = v
        k = next((i for i, k in enumerate(known) if k["file"] == rel and module and matches(module, k["module"])),
                 None)
        (new if k is None else old).append(v)
        if k is not None:
            hit.add(k)
    return new, old, [k for i, k in enumerate(known) if i not in hit]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--profile", default=None, help="default: <root>/.migration/profile.yaml")
    a = ap.parse_args(argv)
    root = pathlib.Path(a.root)
    profile = pathlib.Path(a.profile) if a.profile else root / ".migration/profile.yaml"
    doc = (yaml.safe_load(profile.read_text(encoding="utf-8")) or {}) if profile.exists() else {}
    layering = doc.get("layering")
    if layering is None:
        print("AFS-RESULT gate=layering contracts=0 violations=0 (the profile has no `layering`)")
        return 0
    errs = config_errors(layering)
    if errs:
        print("\n".join(errs))
        print("AFS-RESULT gate=layering error=bad-contract")
        return 2
    contracts = layering["contracts"]
    found = check(root, contracts, layering.get("source_root", "."))
    new, old, stale = split_known(found, layering.get("known") or [])
    for rel, line, _, msg in new:
        print(f"{rel}:{line}: {msg}")
    for rel, line, module, msg in old:
        reason = next(k["reason"] for k in layering["known"] if k["file"] == rel and matches(module, k["module"]))
        print(f"{rel}:{line}: known, not failing: {msg}. Still to fix: {reason}")
    for k in stale:
        print(f"note: the known violation {k['file']} -> {k['module']} no longer occurs: remove it from "
              "`layering.known`")
    if new:
        print("\nMove the code to the layer the contract allows (a use case raises a domain error and the view "
              "maps it to a response; a view calls a use case, not a repository), or, if the architecture changed, "
              "change the ADR and the profile's `layering` together.")
    print(f"AFS-RESULT gate=layering contracts={len(contracts)} violations={len(new)} known={len(old)}")
    return 1 if new else 0


if __name__ == "__main__":
    import afs_trace
    afs_trace.run(main)
