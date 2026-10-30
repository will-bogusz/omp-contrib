"""charts/run.mjs --help (and -h) prints usage and writes nothing, and a flag where DIR belongs is a usage error
that also writes nothing: no DIR/out, no DIR/node_modules, no browser. Needs bun.
Run: python3 -m unittest discover -s tests"""
import contrib_env  # noqa: F401  (a hermetic config for run.mjs)
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RUN = os.path.join(ROOT, "charts", "run.mjs")


@unittest.skipUnless(shutil.which("bun"), "needs bun")
class RunMjsHelpTest(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp(prefix="run-mjs-help-")
        self.addCleanup(shutil.rmtree, self.cwd, True)

    def run_mjs(self, *args):
        return subprocess.run(["bun", RUN, *args], cwd=self.cwd, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "OMP_REPO": os.path.join(self.cwd, "no-checkout")})

    def test_help_prints_usage_and_writes_nothing(self):
        for flag in ("--help", "-h"):
            r = self.run_mjs(flag)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("usage: bun run.mjs DIR", r.stdout)
            self.assertIn("--verify", r.stdout)
            self.assertEqual(os.listdir(self.cwd), [], flag)

    def test_help_after_a_dir_still_writes_nothing(self):
        r = self.run_mjs("chart-dir", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(self.cwd), [])

    def test_a_flag_where_dir_belongs_is_a_usage_error_and_writes_nothing(self):
        for flag in ("--upload", "--verify", "--body"):
            r = self.run_mjs(flag)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("DIR is a flag, not a directory: nothing was written", r.stderr)
            self.assertEqual(os.listdir(self.cwd), [], flag)


if __name__ == "__main__":
    unittest.main()
