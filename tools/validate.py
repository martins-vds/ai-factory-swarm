#!/usr/bin/env python3
"""Validate a migration state folder against the harness schemas.

Usage: validate.py <folder> [--schemas <dir>]

<folder> is a target repo's `.migration/` (or the harness's `templates/migration/`). Checks, when present:
  profile.yaml       → schemas/profile.schema.json
  capabilities.yaml  → schemas/capabilities.schema.json
  ledger/*.yaml      → schemas/ledger-entry.schema.json, plus: file name == `<id>.yaml`, ids unique
  returns/*.yaml     → schemas/return.schema.json, plus: file name == `<ticket>.<role>.yaml`; and (ADR-0017)
                       a finished return has no null gates, and each score equals the last mutation
                       gate run's AFS-RESULT in evidence/runs/<ticket>.md (returns in
                       harness/legacy-returns.json are exempt)
  handoffs/*.md      → every `## Handoff — <role> · <UTC>` section has its required subsections
  quirks/*.md        → quirk drafts have Question, Evidence, Impact and Options sections
Exits 1 if anything is invalid. Requires: jsonschema, pyyaml.
"""
import argparse
import json
import pathlib
import re
import shlex
import sys

import yaml
from jsonschema import Draft202012Validator, FormatChecker

HERE = pathlib.Path(__file__).resolve().parent


def load_schema(schemas, name):
    schema = json.loads((schemas / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        # YAML 1.1 turns bare dates into datetimes; validate them as the strings they are on disk.
        return json.loads(json.dumps(yaml.safe_load(fh), default=str))


def check(validator, path, errors):
    try:
        doc = load_yaml(path)
    except yaml.YAMLError as exc:
        errors.append(f"{path}: invalid YAML: {exc}")
        return None
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {where}: {err.message}")
    return doc


HANDOFF_PARTS = ["**State:**", "### Done", "### Remaining", "### Blockers / questions", "### Next step for the next session"]
QUIRK_PARTS = ["## Question", "## Evidence", "## Impact", "## Options"]


def check_markdown(folder, errors):
    """Structure checks for agent-written Markdown outputs (afs-handoff, afs-quirk-ticket)."""
    checked = 0
    for path in sorted((folder / "handoffs").glob("*.md")) if (folder / "handoffs").is_dir() else []:
        checked += 1
        text = path.read_text(encoding="utf-8")
        sections = re.split(r"(?m)^## Handoff\b", text)[1:]
        if not sections:
            errors.append(f"{path}: no '## Handoff — <role> · <UTC timestamp>' section")
        for i, sec in enumerate(sections, 1):
            for part in HANDOFF_PARTS:
                if part not in sec:
                    errors.append(f"{path}: handoff section {i} is missing '{part}'")
    for path in sorted((folder / "quirks").glob("*.md")) if (folder / "quirks").is_dir() else []:
        checked += 1
        text = path.read_text(encoding="utf-8")
        for part in QUIRK_PARTS:
            if not re.search(r"(?m)^" + re.escape(part) + r"\s*$", text):
                errors.append(f"{path}: quirk draft is missing '{part}'")
    return checked


SCORE_KEYS = {"mutation_changed", "mutation_full", "mutation_score"}
NOT_RUN = re.compile(r"^n/a: \S")


def cell(text, limit=400):
    """Same escaping afs-run uses for the journal's Command cell."""
    return text.replace("|", "\\|").replace("`", "'").strip()[:limit]


def read_journal(path):
    """Rows of an afs-run journal as dicts, and whether it has the ADR-0017 Result column."""
    rows, has_result = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| UTC |"):
            has_result = line.rstrip().endswith("| Result |")
            continue
        if not line.startswith("| 2"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if len(cells) < 8:
            continue
        rows.append({"gate": cells[1], "exit": cells[2], "command": cells[4].strip("`"),
                     "result": dict(kv.split("=", 1) for kv in cells[7].split() if "=" in kv)})
    return rows, has_result


def gate_commands(profile):
    """Journal Command cells that count as a real gate run: each profile gate command, as run or via bash -c."""
    trusted = set()
    for cmds in (profile.get("gates") or {}).values():
        for cmd in cmds or []:
            trusted.add(cell(cmd))
            trusted.add(cell(shlex.join(["bash", "-c", cmd])))
    return trusted


def scores_in(node, where=""):
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{where}.{k}" if where else k
            if k in SCORE_KEYS and not isinstance(v, (dict, list)):
                yield path, v
            else:
                yield from scores_in(v, path)


def check_return_evidence(folder, path, doc, profile, errors):
    """ADR-0017: a finished return reports every gate, and every score matches a gate run's AFS-RESULT."""
    ticket = doc.get("ticket")
    journal = folder / "evidence" / "runs" / f"{ticket}.md"
    rows, _ = read_journal(journal) if journal.is_file() else ([], True)
    finished = doc.get("handoff") in (None, "", "none")
    if finished:
        for key, value in (doc.get("gates") or {}).items():
            if value is None:
                errors.append(f"{path}: gates.{key} is null in a finished return; give the value, or "
                              f"'n/a: <reason>' if the gate does not apply (null only with a handoff)")
    trusted = gate_commands(profile or {})
    runs = [r for r in rows if r["command"] in trusted and r["result"].get("gate") == "mutation"]
    for key, value in scores_in(doc):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not runs:
            errors.append(f"{path}: {key}={value} but {journal} has no mutation gate run with a result; run the "
                          f"profile's mutation gate through afs-run")
            continue
        last = runs[-1]["result"].get("score", "")
        try:
            ok = abs(float(last) - float(value)) < 0.0005
        except ValueError:
            ok = False
        if not ok:
            errors.append(f"{path}: {key}={value} does not match the last mutation gate run in {journal} "
                          f"(score={last}); report the score afs-mutation printed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--schemas", default=str(HERE.parent / "schemas"))
    a = ap.parse_args()
    folder, schemas = pathlib.Path(a.folder), pathlib.Path(a.schemas)
    errors, checked = [], 0

    for name, schema in (("profile.yaml", "profile.schema.json"), ("capabilities.yaml", "capabilities.schema.json")):
        if (folder / name).exists():
            check(load_schema(schemas, schema), folder / name, errors)
            checked += 1

    ledger = folder / "ledger"
    if ledger.is_dir():
        validator = load_schema(schemas, "ledger-entry.schema.json")
        seen = {}
        for path in sorted(ledger.glob("*.y*ml")):
            doc = check(validator, path, errors)
            checked += 1
            if isinstance(doc, dict) and "id" in doc:
                if path.stem != doc["id"]:
                    errors.append(f"{path}: file name must be '{doc['id']}.yaml'")
                if doc["id"] in seen:
                    errors.append(f"{path}: duplicate id '{doc['id']}' (also in {seen[doc['id']]})")
                seen[doc["id"]] = path.name

    returns = folder / "returns"
    if returns.is_dir():
        validator = load_schema(schemas, "return.schema.json")
        profile = load_yaml(folder / "profile.yaml") if (folder / "profile.yaml").exists() else {}
        # Returns committed before ADR-0017, listed once by bootstrap; CI keeps the list unchanged.
        legacy_file = folder / "harness" / "legacy-returns.json"
        legacy = set(json.loads(legacy_file.read_text(encoding="utf-8"))["returns"]) if legacy_file.exists() else set()
        for path in sorted(returns.glob("*.y*ml")):
            doc = check(validator, path, errors)
            checked += 1
            if isinstance(doc, dict) and doc.get("ticket") and path.name not in legacy:
                check_return_evidence(folder, path, doc, profile, errors)
            if isinstance(doc, dict) and "ticket" in doc and "role" in doc:
                want = f"{doc['ticket']}.{doc['role']}"
                if path.stem != want:
                    errors.append(f"{path}: file name must be '{want}.yaml'")

    checked += check_markdown(folder, errors)

    if checked == 0:
        errors.append(f"{folder}: nothing to validate (no profile.yaml, capabilities.yaml or ledger/)")
    for e in errors:
        print(e, file=sys.stderr)
    print(f"{checked} file(s) checked, {len(errors)} error(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
