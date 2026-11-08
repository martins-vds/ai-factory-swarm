"""ADR-0037: every return-file, ledger and label value path is targeted by a synthetic scenario or was
exercised by the pilot; the synthetic legacy app builds; coverage unions across targets."""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import harness_coverage as hc  # noqa: E402

CATALOG = yaml.safe_load((ROOT / "synthetic/scenarios.yaml").read_text())
LABELS = ["wayfinder:prototype"]   # labels whose path only real work produces


def value_paths():
    ret = json.loads((ROOT / "schemas/return.schema.json").read_text())
    led = json.loads((ROOT / "schemas/ledger-entry.schema.json").read_text())
    roles = next(v for p, v in hc.enums(ret) if p and p[-1] == "role")
    keys = {f"role:{r}" for r in roles}
    for role, fields in hc.role_fields(ret).items():
        keys |= {f"value:{role}:{f}:{v}" for f, vs in fields.items() for v in vs}
    for field, spec in led.get("properties", {}).items():
        if isinstance(spec, dict) and "enum" in spec:
            keys |= {f"ledger:{field}:{v}" for v in spec["enum"] if v is not None}
    return keys


class CatalogTest(unittest.TestCase):
    def test_every_value_path_has_a_scenario_or_pilot_evidence(self):
        targeted = {t for s in CATALOG["scenarios"] for t in s["targets"]}
        known = targeted | set(CATALOG["pilot_exercised"])
        missing = sorted(value_paths() - known)
        self.assertEqual(missing, [], "add a scenario to synthetic/scenarios.yaml for each (ADR-0037)")
        for label in LABELS:
            self.assertIn(f"label:{label}", known)

    def test_each_scenario_points_at_real_legacy_and_a_known_path(self):
        universe = value_paths() | {f"label:{lb}" for lb in LABELS}
        for s in CATALOG["scenarios"]:
            with self.subTest(s["id"]):
                self.assertTrue((ROOT / "synthetic/legacy" / s["legacy"]).exists(), s["legacy"])
                self.assertTrue(s["how"].strip())
                self.assertTrue(set(s["targets"]) <= universe, set(s["targets"]) - universe)

    @unittest.skipUnless(shutil.which("javac"), "no JDK")
    def test_the_legacy_app_builds(self):
        with tempfile.TemporaryDirectory() as d:
            src = sorted(str(p) for p in (ROOT / "synthetic/legacy/src/main/java").rglob("*.java"))
            r = subprocess.run(["javac", "-d", d, *src], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class UnionTest(unittest.TestCase):
    def test_a_path_counts_once_any_target_exercised_it(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = pathlib.Path(d) / "a.json", pathlib.Path(d) / "b.json"
            a.write_text(json.dumps({"repo": "o/pilot", "paths": {
                "tool:x": {"ok": True, "text": ""}, "ledger:status:deferred": {"ok": False, "text": ""}}}))
            b.write_text(json.dumps({"repo": "o/synthetic", "paths": {
                "ledger:status:deferred": {"ok": True, "text": ""}, "label:wayfinder:prototype": {"ok": None, "text": ""}}}))
            out = pathlib.Path(d) / "u.md"
            hc.union([str(a), str(b)], str(out))
            text = out.read_text()
        self.assertIn("✅ `ledger:status:deferred` (by o/synthetic)", text)
        self.assertIn("⚠️ `label:wayfinder:prototype`", text)
        self.assertIn("2 of 3 paths exercised across 2 target(s)", text)


if __name__ == "__main__":
    unittest.main()
