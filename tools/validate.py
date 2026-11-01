#!/usr/bin/env python3
"""Validate a migration state folder against the harness schemas.

Usage: validate.py <folder> [--schemas <dir>]

<folder> is a target repo's `.migration/` (or the harness's `templates/migration/`). Checks, when present:
  profile.yaml       → schemas/profile.schema.json
  capabilities.yaml  → schemas/capabilities.schema.json
  ledger/*.yaml      → schemas/ledger-entry.schema.json, plus: file name == `<id>.yaml`, ids unique
  returns/*.yaml     → schemas/return.schema.json, plus: file name == `<ticket>.<role>.yaml`
Exits 1 if anything is invalid. Requires: jsonschema, pyyaml.
"""
import argparse
import json
import pathlib
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
        for path in sorted(returns.glob("*.y*ml")):
            doc = check(validator, path, errors)
            checked += 1
            if isinstance(doc, dict) and "ticket" in doc and "role" in doc:
                want = f"{doc['ticket']}.{doc['role']}"
                if path.stem != want:
                    errors.append(f"{path}: file name must be '{want}.yaml'")

    if checked == 0:
        errors.append(f"{folder}: nothing to validate (no profile.yaml, capabilities.yaml or ledger/)")
    for e in errors:
        print(e, file=sys.stderr)
    print(f"{checked} file(s) checked, {len(errors)} error(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
