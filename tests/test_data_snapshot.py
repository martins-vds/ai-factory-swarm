"""tools/data_snapshot.py and java/JdbcSnapshot.java (ADR-0032): making, describing and fetching snapshots."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import data_reconcile  # noqa: E402
import data_snapshot as ds  # noqa: E402


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_describes_csvs_and_passes_the_check(self):
        snap = self.d / "snap"
        snap.mkdir()
        (snap / "CARGO.csv").write_text('ID,NOTE\n1,"two\nlines"\n2,\\N\n', encoding="utf-8")
        doc = ds.write_manifest(snap, "derby", "ops")
        self.assertEqual(doc["tables"]["CARGO"]["rows"], 2, "a quoted newline is one row")
        self.assertEqual(data_reconcile.check_snapshot(snap)[1], [])

    def test_manifest_refuses_an_empty_folder(self):
        with self.assertRaises(ds.SnapshotError):
            ds.write_manifest(self.d, "derby", "ops")

    def test_driver_is_checked_against_its_pin(self):
        repo = self.d / "m2" / "org" / "example" / "drv" / "1.0"
        repo.mkdir(parents=True)
        (repo / "drv-1.0.jar").write_bytes(b"jar bytes")
        good = hashlib.sha256(b"jar bytes").hexdigest()
        orig, ds.MAVEN = ds.MAVEN, (self.d / "m2").as_uri()
        try:
            cache = self.d / "cache"
            cache.mkdir()
            self.assertTrue(ds.driver_jar(f"org.example:drv:1.0@{good}", cache).exists())
            (cache / "drv-1.0.jar").unlink()
            with self.assertRaises(ds.SnapshotError):
                ds.driver_jar("org.example:drv:1.0@" + "0" * 64, cache)
        finally:
            ds.MAVEN = orig

    def test_export_refuses_a_folder_with_files(self):
        out = self.d / "out"
        out.mkdir()
        (out / "old.csv").write_text("x\n")
        self.assertEqual(ds.main(["export", "--jdbc-url", "jdbc:x", "--driver-jar", "x.jar", "--out", str(out)]), 1)

    def test_fetch_downloads_the_newest_successful_run(self):
        calls = []

        def gh(*args):
            calls.append(args)
            if args[:2] == ("run", "list"):
                return "4242"
            dest = pathlib.Path(args[args.index("--dir") + 1])
            (dest / "manifest.json").write_text(json.dumps({"tables": {"A": {}}, "taken_at": "t", "taken_by": "ops"}))
            return ""
        orig, ds.gh = ds.gh, gh
        try:
            self.assertEqual(ds.main(["fetch", "--repo", "o/r", "--dir", str(self.d / "snap")]), 0)
        finally:
            ds.gh = orig
        self.assertIn("--status", calls[0])
        self.assertEqual(calls[1][:2], ("run", "download"))

    def test_fetch_without_any_snapshot_run_says_who_makes_one(self):
        orig, ds.gh = ds.gh, lambda *a: ""
        try:
            self.assertEqual(ds.main(["fetch", "--repo", "o/r", "--dir", str(self.d / "s")]), 1)
        finally:
            ds.gh = orig


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "needs a JDK")
class JdbcSnapshotJavaTest(unittest.TestCase):
    def test_csv_encoding_selftest(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["javac", "-d", tmp, str(ROOT / "tools/java/JdbcSnapshot.java")], check=True,
                           capture_output=True)
            r = subprocess.run(["java", "-cp", tmp, "JdbcSnapshot", "--selftest"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("selftest ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
