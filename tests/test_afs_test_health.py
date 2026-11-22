"""afs-test-health (test-trust plan, step 0.1): mocks, internals and coupling, counted the same way on every target."""
import importlib.machinery
import importlib.util
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("afs_test_health", str(ROOT / "tools/afs-test-health"))
spec = importlib.util.spec_from_loader("afs_test_health", loader)
th = importlib.util.module_from_spec(spec)
loader.exec_module(th)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._d.name)
        (self.root / "src/shop/billing").mkdir(parents=True)
        (self.root / "tests/characterization").mkdir(parents=True)

    def tearDown(self):
        self._d.cleanup()

    def scan(self, code):
        path = self.root / "tests/test_x.py"
        path.write_text(textwrap.dedent(code))
        return th.scan_file(path, th.own_packages(self.root, "src"))

    def test_own_code_patches_are_told_from_boundaries(self):
        counts, findings = self.scan("""
            from unittest import mock
            from shop.billing import service
            def test_a(monkeypatch):
                monkeypatch.setattr("django.utils.timezone.localdate", lambda: 1)       # boundary: clock
                monkeypatch.setattr(service, "sleep", lambda s: None)                   # boundary: sleeping
                monkeypatch.setattr(service, "charge_customer", lambda: 1)              # own code
                with mock.patch("shop.billing.gateway._open"):                          # boundary: adapter
                    pass
                with mock.patch.object(service.Repo, "save"):                           # own code
                    pass
        """)
        self.assertEqual((counts["patch_own"], counts["patch_boundary"]), (2, 3))
        self.assertEqual(sorted(w for _, k, w in findings if k == "own-code patch"),
                         ["shop.billing.service.Repo.save", "shop.billing.service.charge_customer"])

    def test_private_access_skips_the_tests_own_doubles_and_framework_names(self):
        counts, findings = self.scan("""
            from shop.billing.service import _round, total
            class FakeRepo:
                def __init__(self):
                    self._rows = []
            def test_b(order):
                assert order._meta.label
                assert total._cache == {}
                assert _round(1.005) == 1.0
        """)
        self.assertEqual(counts["private_access"], 2)
        self.assertEqual(sorted(w for _, k, w in findings), ["shop.billing.service._round", "total._cache"])

    def test_interaction_assertions_and_entry_points_are_counted(self):
        counts, _ = self.scan("""
            def test_c(client, notifier):
                client.post("/orders/", {})
                notifier.send.assert_called_once_with("x")
                assert notifier.send.call_count == 1
        """)
        self.assertEqual(counts["interaction_asserts"], 2)
        self.assertEqual(counts["public_entry_files"], 1)
        self.assertEqual(counts["tests"], 1)

    def test_characterization_tests_are_left_out(self):
        (self.root / "tests/characterization/test_golden.py").write_text("def test_g(m):\n    m._x\n")
        (self.root / "tests/test_y.py").write_text("def test_y():\n    pass\n")
        rep = th.report(self.root)
        self.assertEqual(rep["totals"]["files"], 1)
        self.assertEqual(rep["totals"].get("private_access", 0), 0)


class CouplingTest(unittest.TestCase):
    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.root, check=True,
                       capture_output=True)

    def commit(self, files, msg):
        for name, text in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.git("add", ".")
        self.git("commit", "-qm", msg)

    def test_a_production_change_that_edits_an_existing_test_counts(self):
        with tempfile.TemporaryDirectory() as d:
            self.root = pathlib.Path(d)
            self.git("init", "-q", "-b", "main")
            self.commit({"src/a.py": "A = 1\n", "tests/test_a.py": "def test_a(): pass\n"}, "new code, new test")
            self.commit({"src/a.py": "A = 2\n", "tests/test_a.py": "def test_a(): assert 1\n"}, "edits a test")
            self.commit({"src/a.py": "A = 3\n"}, "refactor, tests untouched")
            self.commit({"tests/characterization/test_g.py": "x\n", "src/b.py": "B = 1\n"}, "new file")
            got = th.coupling(self.root, "src", "tests")
        self.assertEqual((got["production_commits"], got["modified_existing_tests"]), (4, 1))
        self.assertEqual(got["ratio"], 0.25)


if __name__ == "__main__":
    unittest.main()
