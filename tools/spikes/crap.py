#!/usr/bin/env python3
"""Language-agnostic CRAP calculator.

CRAP(m) = comp(m)^2 * (1 - cov(m))^3 + comp(m)
  comp = cyclomatic complexity, cov = line coverage of the method (0..1).

Inputs
  * Complexity: a `lizard --csv` report (lizard supports ~20 languages, incl. Java, C#, C/C++,
    Python, JavaScript/TypeScript, Go, Kotlin, Swift, Ruby, PHP, Scala).
  * Coverage (optional): LCOV (`--lcov`, emitted by coverage.py, c8/istanbul, coverlet, gcov…)
    and/or JaCoCo XML (`--jacoco`). Method coverage = covered / instrumented lines within the
    method's line range. With no coverage input, cov = 0 and CRAP reduces to a complexity ranking
    (the "no source tests" case, ADR-0013).

Outputs
  * CSV (`--csv`) with every method.
  * Markdown risk map on stdout: summary + top N.
  * `--max N`: exit 1 if any method exceeds N (gate mode, ADR-0011). Without --max, exit 0
    (risk-map mode: never blocks).

Standard library only.

Examples
  lizard --csv src > lizard.csv
  python3 crap.py lizard.csv --top 25 > risk-map.md                      # source, no tests
  python3 crap.py lizard.csv --jacoco target/site/jacoco/jacoco.xml --csv crap.csv
  python3 crap.py lizard.csv --lcov coverage.lcov --max 30               # target gate
"""
import argparse
import collections
import csv
import os
import sys
import xml.etree.ElementTree as ET

# lizard --csv columns (no header): NLOC, CCN, token, PARAM, length, location, file, function,
# long_name, start, end
LIZARD_COLS = ["nloc", "ccn", "tokens", "params", "length", "location", "file", "function",
               "long_name", "start", "end"]


def norm(path):
    return os.path.normpath(path).replace(os.sep, "/").lstrip("./")


def read_lizard(path):
    methods = []
    with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
        for row in csv.reader(fh):
            if not row or row[0] == "NLOC" or len(row) < len(LIZARD_COLS):
                continue
            r = dict(zip(LIZARD_COLS, row))
            try:
                methods.append({"file": norm(r["file"]), "function": r["long_name"] or r["function"],
                                "ccn": int(r["ccn"]), "start": int(r["start"]), "end": int(r["end"])})
            except ValueError:
                continue
    return methods


def read_lcov(path, cov):
    current = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("SF:"):
                current = cov[norm(line[3:])]
            elif line.startswith("DA:") and current is not None:
                ln, hits = line[3:].split(",")[:2]
                current[int(ln)] = current.get(int(ln), 0) + int(float(hits))
            elif line == "end_of_record":
                current = None


def read_jacoco(path, cov):
    root = ET.parse(path).getroot()
    for pkg in root.iter("package"):
        pname = pkg.get("name", "")
        for sf in pkg.iter("sourcefile"):
            lines = cov[norm(f"{pname}/{sf.get('name')}")]
            for ln in sf.iter("line"):
                covered = int(ln.get("ci", 0)) > 0
                lines[int(ln.get("nr"))] = lines.get(int(ln.get("nr")), 0) + (1 if covered else 0)


def match_cov(file, cov):
    """Coverage paths are often relative to a different root; match by longest common suffix."""
    if file in cov:
        return cov[file]
    best, best_len = None, 0
    for k in cov:
        if file.endswith(k) or k.endswith(file):
            n = min(len(k), len(file))
            if n > best_len:
                best, best_len = cov[k], n
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lizard_csv")
    ap.add_argument("--lcov", action="append", default=[])
    ap.add_argument("--jacoco", action="append", default=[])
    ap.add_argument("--csv", help="write all methods to this CSV")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--max", type=float, help="gate: fail if any method's CRAP exceeds this")
    a = ap.parse_args()

    methods = read_lizard(a.lizard_csv)
    if not methods:
        sys.exit("no methods read from lizard CSV")
    cov = collections.defaultdict(dict)
    for p in a.lcov:
        read_lcov(p, cov)
    for p in a.jacoco:
        read_jacoco(p, cov)
    have_cov = bool(cov)

    unmatched_files = set()
    for m in methods:
        lines = match_cov(m["file"], cov) if have_cov else None
        if lines is None:
            m["cov"] = 0.0
            if have_cov:
                unmatched_files.add(m["file"])
        else:
            rng = [h for ln, h in lines.items() if m["start"] <= ln <= m["end"]]
            m["cov"] = (sum(1 for h in rng if h > 0) / len(rng)) if rng else 0.0
        m["crap"] = m["ccn"] ** 2 * (1 - m["cov"]) ** 3 + m["ccn"]
    methods.sort(key=lambda m: m["crap"], reverse=True)

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["crap", "ccn", "coverage", "file", "function", "start", "end"])
            for m in methods:
                w.writerow([f"{m['crap']:.1f}", m["ccn"], f"{m['cov']:.2f}", m["file"], m["function"], m["start"], m["end"]])

    limit = a.max if a.max is not None else 30
    over = [m for m in methods if m["crap"] > limit]
    print("# CRAP risk map\n")
    print(f"- Methods: {len(methods)} · coverage input: {'yes' if have_cov else 'none (CRAP = complexity ranking)'}")
    print(f"- Above {limit:g}: **{len(over)}** ({100 * len(over) / len(methods):.1f}%)")
    if unmatched_files:
        print(f"- Files with no coverage data (treated as 0%): {len(unmatched_files)}")
    print(f"\n## Top {min(a.top, len(methods))}\n\n| CRAP | CCN | Cov | Method | File:lines |\n|---:|---:|---:|---|---|")
    for m in methods[: a.top]:
        print(f"| {m['crap']:.0f} | {m['ccn']} | {m['cov']:.0%} | `{m['function'][:80]}` | {m['file']}:{m['start']}-{m['end']} |")
    by_file = collections.Counter()
    for m in over:
        by_file[m["file"]] += 1
    if by_file:
        print("\n## Hot files (methods above threshold)\n\n| Methods | File |\n|---:|---|")
        for f, c in by_file.most_common(a.top):
            print(f"| {c} | {f} |")

    if a.max is not None and over:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:  # e.g. piped into `head`
        sys.stderr.close()
