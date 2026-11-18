"""ADR-0037: every return-file, ledger and label value path is targeted by a synthetic scenario or was
exercised by the pilot; the synthetic legacy app builds; coverage unions across targets."""
import json
import re
import pathlib
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
SOURCES = ("legacy", "legacy-billing", "legacy-reports")   # one Bootstrapper tier per source


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
                source = s.get("source", "legacy")
                self.assertIn(source, SOURCES)
                self.assertTrue((ROOT / "synthetic" / source / s["legacy"]).exists(), (source, s["legacy"]))
                self.assertTrue(s["how"].strip())
                self.assertTrue(set(s["targets"]) <= universe, set(s["targets"]) - universe)

    def test_the_legacy_app_is_a_java_ee_source_the_enricher_reads(self):
        legacy = ROOT / "synthetic/legacy"
        java = "\n".join(p.read_text() for p in (legacy / "src/main/java").rglob("*.java"))
        self.assertIn("@Entity", java)
        self.assertIn("@Path(", java)
        self.assertTrue((legacy / "pom.xml").exists())
        self.assertIn("legacy smoke test passed", (ROOT / "synthetic/legacy-smoke.yml").read_text())


class SourcesTest(unittest.TestCase):
    def test_each_bootstrapper_tier_has_its_own_source(self):
        # one source has one tier: A, B and C need three sources (ADR-0037 amendment)
        by_tier = {t.rsplit(":", 1)[1]: s.get("source", "legacy") for s in CATALOG["scenarios"] for t in s["targets"]
                   if t.startswith("value:afs-bootstrapper:characterization_tier:")}
        by_tier.setdefault("A", "legacy")
        self.assertEqual(sorted(by_tier), ["A", "B", "C"])
        self.assertEqual(len(set(by_tier.values())), 3, by_tier)

    def test_the_billing_source_cannot_build_but_its_arithmetic_compiles_alone(self):
        billing = ROOT / "synthetic/legacy-billing"
        pom = (billing / "pom.xml").read_text()
        self.assertIn("<artifactId>vault-client</artifactId>", pom)
        self.assertNotIn("repo.maven.apache.org", pom)
        java = {p.name: p.read_text() for p in (billing / "src/main/java").rglob("*.java")}
        vendor = {n for n, src in java.items() if "com.northgate" in src}
        self.assertTrue(vendor and set(java) - vendor, "some classes need the vendor jar, some don't")
        for name in ("InvoiceCalculator.java", "InvoiceLine.java"):
            self.assertNotIn("com.northgate", java[name])
            self.assertNotIn("CardVault", java[name])
        self.assertTrue(list((billing / "src/test/java").rglob("*Test.java")))

    def test_the_reports_source_has_no_code(self):
        reports = ROOT / "synthetic/legacy-reports"
        files = [p for p in reports.rglob("*") if p.is_file()]
        self.assertTrue(files)
        self.assertFalse([p for p in files if p.suffix in {".java", ".py", ".sql", ".xml", ".sh", ".rpt"}])


class BlindTest(unittest.TestCase):
    def test_the_legacy_app_names_no_scenario_or_expected_outcome(self):
        # the first Bootstrapper cited a copied catalog as its evidence: the target must stay blind (ADR-0037)
        words = re.compile(r"scenario|ADR-|tier\b|characteri[sz]|misplaced|review-only|coverage|harness", re.I)
        for p in (q for src in SOURCES for q in (ROOT / "synthetic" / src).rglob("*")):
            if p.is_file():
                with self.subTest(p.name):
                    self.assertIsNone(words.search(p.read_text(errors="ignore")), p)


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
