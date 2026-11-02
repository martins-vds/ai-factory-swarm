"""tools/crap.py: the gate prints its AFS-RESULT line (ADR-0017)."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

CRAP = pathlib.Path(__file__).resolve().parent.parent / "tools/crap.py"
LIZARD = ('NLOC,CCN,token,PARAM,length,location,file,function,long_name,start,end\n'
          '4,3,20,1,4,"f@1-4@src/a.py","src/a.py","f","f( x )",1,4\n'
          '9,9,60,1,9,"g@6-14@src/a.py","src/a.py","g","g( x )",6,14\n')


class CrapResultTest(unittest.TestCase):
    def run_crap(self, limit):
        with tempfile.TemporaryDirectory() as t:
            csv = pathlib.Path(t) / "lizard.csv"
            csv.write_text(LIZARD)
            return subprocess.run([sys.executable, str(CRAP), str(csv), "--max", limit], capture_output=True, text=True)

    def test_pass_and_fail_both_report_the_worst_method(self):
        ok = self.run_crap("100")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("AFS-RESULT gate=crap max=90.0 threshold=100 over=0 methods=2", ok.stdout)
        bad = self.run_crap("30")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("AFS-RESULT gate=crap max=90.0 threshold=30 over=1 methods=2", bad.stdout)


if __name__ == "__main__":
    unittest.main()
