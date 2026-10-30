#!/usr/bin/env python3
"""Extract a vertical slice of a Java codebase into its own folder, for a targeted graph run.

Starting from seed classes, follows `import` statements and same-package references up to
--depth hops, copies those files (original paths preserved), plus any --extra files, and
optionally a trimmed JSF faces-config containing only managed beans whose name starts with
--bean-prefix. Writes MANIFEST.txt listing everything copied.

Spike helper (M1): Java-only by design. Standard library only.

Example:
  python3 extract_slice.py --root java --out /tmp/currency-slice --depth 2 \
    --seed Currency --seed CurrencyTableModel --seed CurrencyTableBean \
    --seed CurrencyBean --seed CurrencyFormBean \
    --extra toolkit-web/src/main/webapp/admin/currency.jspx \
    --faces-config toolkit-web/src/main/webapp/WEB-INF/admin-config.xml --bean-prefix currency
"""
import argparse
import os
import re
import shutil
import sys


def index_java(root):
    idx = {}
    for dirpath, _, files in os.walk(root):
        if "/src/main/" not in dirpath.replace(os.sep, "/") + "/":
            continue
        for f in files:
            if not f.endswith(".java"):
                continue
            path = os.path.join(dirpath, f)
            with open(path, encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
            m = re.search(r"^package\s+([\w.]+);", src, re.M)
            if m:
                idx[f"{m.group(1)}.{f[:-5]}"] = (os.path.relpath(path, root), src)
    return idx


def deps(fqcn, idx, by_pkg):
    _, src = idx[fqcn]
    pkg = fqcn.rsplit(".", 1)[0]
    out = {i for i in re.findall(r"^import\s+([\w.]+);", src, re.M) if i in idx}
    for other in by_pkg.get(pkg, ()):
        if other != fqcn and re.search(r"\b" + re.escape(other.rsplit(".", 1)[1]) + r"\b", src):
            out.add(other)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="source root to scan")
    ap.add_argument("--out", required=True, help="output folder (must not exist)")
    ap.add_argument("--seed", action="append", required=True, help="simple class name; repeatable")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--extra", action="append", default=[], help="extra file (relative to root)")
    ap.add_argument("--faces-config", help="JSF faces-config to trim (relative to root)")
    ap.add_argument("--bean-prefix", help="keep managed beans whose name starts with this")
    a = ap.parse_args()

    if os.path.exists(a.out):
        sys.exit(f"{a.out} already exists")
    idx = index_java(a.root)
    by_pkg = {}
    for k in idx:
        by_pkg.setdefault(k.rsplit(".", 1)[0], []).append(k)

    seeds = [k for k in idx if k.rsplit(".", 1)[1] in set(a.seed)]
    missing = set(a.seed) - {k.rsplit(".", 1)[1] for k in seeds}
    if missing:
        print(f"warning: seeds not found: {sorted(missing)}", file=sys.stderr)
    depth = {s: 0 for s in seeds}
    frontier = list(seeds)
    while frontier:
        k = frontier.pop()
        if depth[k] >= a.depth:
            continue
        for d in deps(k, idx, by_pkg):
            if d not in depth:
                depth[d] = depth[k] + 1
                frontier.append(d)

    copied = []
    for k in sorted(depth):
        rel = idx[k][0]
        dst = os.path.join(a.out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(a.root, rel), dst)
        copied.append(f"{rel}\t(depth {depth[k]})")
    for rel in a.extra:
        dst = os.path.join(a.out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(a.root, rel), dst)
        copied.append(f"{rel}\t(extra)")
    if a.faces_config and a.bean_prefix:
        with open(os.path.join(a.root, a.faces_config), encoding="utf-8", errors="ignore") as fh:
            src = fh.read()
        beans = re.findall(r"<managed-bean>.*?</managed-bean>", src, re.S)
        keep = [b for b in beans if re.search(r"<managed-bean-name>" + re.escape(a.bean_prefix), b)]
        head = src[: src.find("<managed-bean>")] if beans else src
        dst = os.path.join(a.out, a.faces_config)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(head + "\n".join(keep) + "\n</faces-config>\n")
        copied.append(f"{a.faces_config}\t(trimmed: {len(keep)} of {len(beans)} managed beans)")

    with open(os.path.join(a.out, "MANIFEST.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(copied) + "\n")
    print(f"{len(copied)} files → {a.out} (see MANIFEST.txt)")


if __name__ == "__main__":
    main()
