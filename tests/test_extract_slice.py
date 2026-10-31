"""tools/extract_slice.py: seeds, depth, extras and a spec file."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def java(root, pkg, name, body=""):
    d = root / "app/src/main/java" / pkg.replace(".", "/")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.java").write_text(f"package {pkg};\n{body}\npublic class {name} {{}}\n")


class ExtractSliceTest(unittest.TestCase):
    def test_spec_follows_imports_to_depth(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            src = t / "src/java"
            java(src, "a.ui", "CurrencyBean", "import a.svc.CurrencyService;")
            java(src, "a.svc", "CurrencyService", "import a.data.Dao;")
            java(src, "a.data", "Dao", "import a.data.Deep;")
            java(src, "a.data", "Deep")
            java(src, "a.other", "Unrelated")
            (src / "app/page.jspx").write_text("<page/>")
            spec = t / "s.yaml"
            spec.write_text("root: java\nseeds: [CurrencyBean]\ndepth: 2\nextra: [app/page.jspx]\n")
            out = t / "out"
            r = subprocess.run([sys.executable, str(ROOT / "tools/extract_slice.py"), "--root", str(t / "src"),
                                "--spec", str(spec), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = sorted(p.name for p in out.rglob("*") if p.is_file())
            self.assertEqual(got, ["CurrencyBean.java", "CurrencyService.java", "Dao.java", "MANIFEST.txt", "page.jspx"])


if __name__ == "__main__":
    unittest.main()
