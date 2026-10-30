"""pr-body against a fake gh and a fake pr-queue, in a scratch copy of scripts/: the queued-entry refusal and its
fail-closed check, the dry run that sends nothing, the PATCH with `-F body=@FILE` and its read-back, the real diff
when GitHub keeps another body, an empty file, a failed gh call, --repo, and --help creating nothing.
Run: python3 -m unittest discover -s tests"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(ROOT, "scripts")

# GitHub's side: "strip" stores the body without trailing newlines (as observed), "keep" stores it exactly,
# "ignore" accepts the PATCH and keeps the old body, "fail" rejects the PATCH.
FAKE_GH = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
state, mode = os.environ["FAKE_GH_STATE"], os.environ.get("FAKE_GH_MODE", "strip")
if args[:1] != ["api"]:
    sys.exit("FAKE-GH: unexpected " + " ".join(args))
if "PATCH" in args:
    if mode == "fail":
        sys.exit("HTTP 422: Validation Failed")
    if mode != "ignore":
        field = args[args.index("-F") + 1]
        assert field.startswith("body=@"), field
        with open(field[len("body=@"):], encoding="utf-8") as f:
            body = f.read()
        with open(state, "w", encoding="utf-8") as f:
            f.write(body.rstrip("\\n") if mode == "strip" else body)
    sys.exit(0)
if "--jq" in args:
    with open(state, encoding="utf-8") as f:
        print(f.read())  # gh --jq prints the string and a newline
    sys.exit(0)
sys.exit("FAKE-GH: unexpected api call " + " ".join(args))
'''

FAKE_QUEUE = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_QUEUE_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:2] != ["body-home"]:
    sys.exit("FAKE-QUEUE: unexpected " + " ".join(sys.argv[1:]))
mode, number = os.environ.get("FAKE_BODY_HOME", ""), int(sys.argv[2])
if mode == "fail":
    sys.exit("pr-queue: manifest unreadable")
entry = mode[len("entry:"):] if mode.startswith("entry:") else None
message = (f"#{number} is closed, queued as {entry}; edit its stored body (pr-queue show / set --body), "
           "not GitHub's") if entry else None
print(json.dumps({"number": number, "entry": entry, "message": message}))
'''


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class PrBodyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr-body-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.scripts = os.path.join(self.tmp, "scripts")
        shutil.copytree(SCRIPTS, self.scripts, ignore=shutil.ignore_patterns("__pycache__", "cli-port", "hooks"))
        write_exec(os.path.join(self.scripts, "pr-queue"), FAKE_QUEUE)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        write_exec(os.path.join(self.bin, "gh"), FAKE_GH)
        self.state = os.path.join(self.tmp, "github-body.md")
        self.gh_log = os.path.join(self.tmp, "gh.log")
        self.queue_log = os.path.join(self.tmp, "queue.log")
        self.body = os.path.join(self.tmp, "body-final.md")
        self.write_state("## What\nold body\n")
        self.write_body("## What\nnew body\n")
        self.cwd = os.path.join(self.tmp, "work")
        os.makedirs(self.cwd)

    def write_state(self, text):
        with open(self.state, "w", encoding="utf-8") as f:
            f.write(text)

    def write_body(self, text, path=None):
        with open(path or self.body, "w", encoding="utf-8") as f:
            f.write(text)

    def run_pr_body(self, *args, queue="", mode="strip"):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_GH_STATE": self.state,
               "FAKE_GH_LOG": self.gh_log, "FAKE_GH_MODE": mode, "FAKE_BODY_HOME": queue,
               "FAKE_QUEUE_LOG": self.queue_log}
        return subprocess.run([sys.executable, os.path.join(self.scripts, "pr-body"), *args], cwd=self.cwd,
                              capture_output=True, text=True, env=env, timeout=60)

    def gh_calls(self):
        return Path(self.gh_log).read_text().splitlines() if os.path.exists(self.gh_log) else []

    def patches(self):
        return [c for c in self.gh_calls() if "-X PATCH" in c]

    def test_queued_entry_refuses_before_any_gh_call(self):
        r = self.run_pr_body("15569", self.body, queue="entry:relay-turn-end-detach")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("queued as relay-turn-end-detach", r.stderr)
        self.assertIn("pr-queue set relay-turn-end-detach --body FILE", r.stderr)
        self.assertEqual(self.gh_calls(), [])
        self.assertEqual(Path(self.state).read_text(), "## What\nold body\n")

    def test_queued_repo_guard_is_case_insensitive_like_github(self):
        r = self.run_pr_body("--repo", "Can1357/Oh-My-Pi", "15569", self.body, queue="entry:queued")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(self.gh_calls(), [])

    def test_failed_queue_check_fails_closed(self):
        r = self.run_pr_body("15601", self.body, queue="fail")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("pr-queue body-home 15601 failed", r.stderr)
        self.assertEqual(self.gh_calls(), [])

    def test_other_repo_skips_the_queue_guard(self):
        r = self.run_pr_body("--repo", "hermes/agent", "7", self.body, queue="fail")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.queue_log))
        self.assertTrue(any("repos/hermes/agent/pulls/7" in c for c in self.patches()), self.gh_calls())

    def test_dry_run_reads_shows_the_diff_and_sends_nothing(self):
        r = self.run_pr_body("--dry-run", "15601", self.body)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would PATCH", r.stdout)
        self.assertIn("-old body", r.stdout)
        self.assertIn("+new body", r.stdout)
        self.assertEqual(self.patches(), [])
        self.assertEqual(Path(self.state).read_text(), "## What\nold body\n")

    def test_patch_sends_the_file_and_reads_back_matching_without_trailing_newlines(self):
        r = self.run_pr_body("15601", self.body)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("read back: matches", r.stdout)
        patches = self.patches()
        self.assertEqual(len(patches), 1, patches)
        self.assertIn("repos/can1357/oh-my-pi/pulls/15601", patches[0])
        self.assertIn(f"-F body=@{os.path.abspath(self.body)}", patches[0])
        self.assertEqual(Path(self.state).read_text(), "## What\nnew body")

    def test_a_body_already_on_github_is_not_sent_again(self):
        self.write_state("## What\nnew body\n")
        r = self.run_pr_body("15601", self.body)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already matches", r.stdout)
        self.assertEqual(self.patches(), [])

    def test_a_body_github_keeps_differently_prints_the_real_diff_and_fails(self):
        r = self.run_pr_body("15601", self.body, mode="ignore")
        self.assertEqual(r.returncode, 1)
        self.assertIn("-old body", r.stdout)
        self.assertIn("+new body", r.stdout)
        self.assertIn("read back a body that differs", r.stderr)

    def test_gh_failure_is_reported_and_exits_1(self):
        r = self.run_pr_body("15601", self.body, mode="fail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("HTTP 422", r.stderr)

    def test_empty_file_is_refused_before_any_call(self):
        self.write_body("\n\n")
        r = self.run_pr_body("15601", self.body)
        self.assertEqual(r.returncode, 1)
        self.assertIn("is empty", r.stderr)
        self.assertEqual(self.gh_calls(), [])
        self.assertFalse(os.path.exists(self.queue_log))

    def test_help_creates_nothing_and_calls_nothing(self):
        r = self.run_pr_body("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("usage: pr-body", r.stdout)
        self.assertEqual(os.listdir(self.cwd), [])
        self.assertEqual(self.gh_calls(), [])

    def test_a_non_number_is_a_usage_error(self):
        r = self.run_pr_body("abc", self.body)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.gh_calls(), [])


if __name__ == "__main__":
    unittest.main()
