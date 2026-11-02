"""contrib (step records, `next`) and the gate `pr-queue add` takes from it, on a real git clone of a
bare upstream. Run: python3 -m unittest discover -s tests"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
import omp_config  # noqa: E402
import omp_flow  # noqa: E402

loader = importlib.machinery.SourceFileLoader("pr_queue_contrib", os.path.join(SCRIPTS, "pr-queue"))
spec = importlib.util.spec_from_loader("pr_queue_contrib", loader)
PQ = importlib.util.module_from_spec(spec)
loader.exec_module(PQ)

CHECK = "sh packages/a/test/check.sh"
SENTENCE = "Binary output turning into garbage in the job widget makes long pipes unreadable; show bytes safely."


def sh(cwd, *args, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise AssertionError(f"{' '.join(args)} in {cwd}: {p.stderr}{p.stdout}")
    return p


def write(root, path, text):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


class FakeGitHub:
    def open_prs(self):
        return {}


class ContribTest(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="contrib-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        env = os.environ.copy()
        self.addCleanup(os.environ.update, env)
        self.addCleanup(lambda: [os.environ.pop(k) for k in set(os.environ) - set(env)])
        os.environ.update(GIT_CONFIG_GLOBAL=os.path.join(self.dir, "gitconfig"), GIT_CONFIG_NOSYSTEM="1")
        write(self.dir, "gitconfig", "[user]\n\tname = T\n\temail = t@example.test\n[init]\n\tdefaultBranch = main\n"
                                     "[commit]\n\tgpgsign = false\n")
        upstream, self.repo = os.path.join(self.dir, "upstream.git"), os.path.join(self.dir, "oh-my-pi")
        self.wts = os.path.join(self.dir, "wt")
        sh(self.dir, "git", "init", "-q", "--bare", upstream)
        sh(self.dir, "git", "clone", "-q", upstream, self.repo)
        write(self.repo, "packages/a/src/widget.sh", "echo garbage\n")
        write(self.repo, "packages/coding-agent/package.json", "{}\n")  # what marks a clone as oh-my-pi
        write(self.repo, "packages/a/CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-10-01\n")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-q", "-m", "base")
        sh(self.repo, "git", "push", "-q", "origin", "main")
        sh(self.repo, "git", "fetch", "-q", "origin")
        os.environ["OMP_CONTRIB_CONFIG"] = contrib_env.write_config(
            os.path.join(self.dir, "config.toml"),
            f'[github]\nfork_owner = "me"\nfork_remote = "fork"\nbranch_prefix = "me/"\n\n'
            f'[paths]\ncheckout = "{self.repo}"\nworktrees = "{self.wts}"\n\n'
            '[autonomy]\nsupervised_opens = 0\n')
        omp_config.load(reload=True)
        self.manifest = os.path.join(self.dir, "queue.json")

    def contrib(self, *args, cwd=None, ok=True):
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "contrib"), *args], cwd=cwd or self.repo,
                           capture_output=True, text=True)
        if ok and p.returncode:
            raise AssertionError(f"contrib {' '.join(args)}: {p.stderr}{p.stdout}")
        return p

    def next(self, cwd=None):
        return json.loads(self.contrib("next", "--json", cwd=cwd).stdout)

    def pq(self, *argv):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                PQ.main(["--repo", self.repo, "--manifest", self.manifest, *argv], github=FakeGitHub())
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue()

    def worktree(self, branch="me/job-widget"):
        wt = os.path.join(self.wts, branch.split("/", 1)[1])
        sh(self.repo, "git", "worktree", "add", "-q", wt, "-b", branch, "origin/main")
        return wt

    def fix(self, wt):
        write(wt, "packages/a/src/widget.sh", "echo bytes\n")
        write(wt, "packages/a/test/check.sh", "grep -q bytes packages/a/src/widget.sh\n")
        write(wt, "packages/a/CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- Fixed the job widget\n\n"
                                             "## [1.0.0] - 2026-10-01\n")
        sh(wt, "git", "add", "-A")
        sh(wt, "git", "commit", "-q", "-m", "fix(a): show binary job output safely")

    def stamp(self, wt, verdict="ready"):
        sh(wt, sys.executable, os.path.join(SCRIPTS, "review-stamp"), verdict, "--by", "Rev1")

    def body(self, text):
        path = os.path.join(self.dir, "body.md")
        write(self.dir, "body.md", f"## What\n\n{text}\n\n## Why\n\nPipes.\n\n## Testing\n\n{CHECK}\n")
        return path

    def test_next_walks_the_fix_chain_to_a_dry_run_queue(self):
        self.contrib("start", "binary pipe output turns the job widget into mojibake", "--topic", "job-widget")
        self.assertEqual(self.next()["step"], "dup-scan")
        self.contrib("record", "dup-scan", "--queries", "job widget binary", "mojibake", "--checked", "#12,#40",
                     "--verdict", "related:#40")
        nxt = self.next()
        self.assertEqual((nxt["step"], nxt["actor"]), ("worktree", "agent"))
        sh(self.repo, "sh", "-c", nxt["command"])  # the exact command `next` prints makes the worktree
        wt = os.path.join(self.wts, "job-widget")
        self.assertEqual(self.next(cwd=wt)["step"], "fix")
        self.fix(wt)
        self.assertEqual(self.next(cwd=wt)["step"], "repro")
        self.contrib("record", "repro", "--before", CHECK, cwd=wt)
        repro = json.loads(self.contrib("status", "--json", cwd=wt).stdout)[0]["repro"]
        self.assertEqual((repro["kind"], repro["before_exit"], repro["after_exit"]), ("verified", 1, 0))
        self.assertEqual(sh(wt, "git", "status", "--porcelain").stdout, "", "the revert is undone")
        self.assertEqual(self.next(cwd=wt)["step"], "review")
        self.stamp(wt)
        self.assertEqual(self.next(cwd=wt)["step"], "precheck", "the code is checked before waiting on the user")
        code_check = sh(wt, sys.executable, os.path.join(SCRIPTS, "precheck"), "--no-siblings", check=False)
        self.assertNotIn("FIX", code_check.stdout, code_check.stdout)
        nxt = self.next(cwd=wt)
        self.assertEqual((nxt["step"], nxt["actor"]), ("own-words", "user"))
        self.assertIn(omp_flow.OWN_WORDS_QUESTION, nxt["command"])
        self.contrib("record", "own-words", f"  {SENTENCE}\n", cwd=wt)
        nxt = self.next(cwd=wt)
        self.assertEqual(nxt["step"], "body")
        self.contrib("body", cwd=wt)
        with open(nxt["body"]) as f:
            self.assertEqual(omp_flow.what_paragraph(f.read()), SENTENCE)
        precheck = (sys.executable, os.path.join(SCRIPTS, "precheck"), "--body", nxt["body"], "--no-siblings")
        check = sh(wt, *precheck, check=False)
        self.assertIn("## Why  section is empty", check.stdout, "the skeleton alone is no body")
        self.assertEqual(self.next(cwd=wt)["step"], "body")
        with open(nxt["body"]) as f:
            text = f.read().replace("## Why\n", "## Why\n\nThe widget printed raw bytes.\n").replace(
                "## Testing\n", f"## Testing\n\n{CHECK} fails on main, passes here.\n")
        with open(nxt["body"], "w") as f:
            f.write(text)
        check = sh(wt, *precheck, check=False)
        self.assertNotIn("FIX", check.stdout, check.stdout)
        nxt = self.next(cwd=wt)
        self.assertEqual(nxt["step"], "queue")
        code, out = self.pq("add", "me/job-widget", "--title", "fix(a): show binary job output safely",
                            "--body", nxt["body"])
        self.assertEqual(code, 0, out)
        nxt = self.next(cwd=wt)
        self.assertEqual((nxt["step"], nxt["actor"]), ("done", "done"))

    def test_add_refuses_with_the_next_step_until_the_chain_is_done(self):
        wt = self.worktree()
        self.contrib("start", "job widget mojibake", cwd=wt)
        self.contrib("record", "dup-scan", "--queries", "job widget", "--verdict", "none", cwd=wt)
        self.fix(wt)
        self.contrib("record", "repro", "--before", CHECK, cwd=wt)
        code, out = self.pq("add", "me/job-widget", "--title", "fix(a): x")
        self.assertEqual(code, 1, out)
        self.assertIn("next: review (agent)", out)
        self.assertIn("review-stamp", out)
        with open(self.manifest) if os.path.exists(self.manifest) else io.StringIO("{}") as f:
            self.assertNotIn("job-widget", f.read(), "nothing queued")

    def test_add_refuses_a_body_whose_own_words_are_not_the_users(self):
        wt = self.worktree()
        self.contrib("start", "job widget mojibake", cwd=wt)
        self.contrib("record", "dup-scan", "--queries", "job widget", "--verdict", "none", cwd=wt)
        self.fix(wt)
        self.contrib("record", "repro", "--before", CHECK, cwd=wt)
        self.stamp(wt)
        self.contrib("record", "own-words", SENTENCE, cwd=wt)
        body = self.body("I made the job widget show binary output safely.")
        check = sh(wt, sys.executable, os.path.join(SCRIPTS, "precheck"), "--body", body, "--no-siblings", check=False)
        self.assertIn("FIX   own-words", check.stdout)
        self.assertEqual(self.next(cwd=wt)["step"], "body", "a FIX is not a pass")
        omp_flow.note_precheck(wt, "me/job-widget", omp_flow.rev(wt, "HEAD"), True, omp_flow.read_text(body), body)
        code, out = self.pq("add", "me/job-widget", "--title", "fix(a): x", "--body", body)
        self.assertEqual(code, 1, out)
        self.assertIn("not the user's recorded own-words sentence", out)

    def test_a_test_that_passes_without_the_fix_is_no_repro(self):
        wt = self.worktree()
        self.contrib("start", "job widget mojibake", cwd=wt)
        self.contrib("record", "dup-scan", "--queries", "job widget", "--verdict", "none", cwd=wt)
        self.fix(wt)
        p = self.contrib("record", "repro", "--before", "true", cwd=wt, ok=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("passes with the fix reverted", p.stderr)
        self.assertEqual(sh(wt, "git", "status", "--porcelain").stdout, "")
        self.assertEqual(self.next(cwd=wt)["step"], "repro")

    def test_duplicate_verdict_and_stop_end_the_contribution(self):
        self.contrib("start", "job widget mojibake")
        self.contrib("record", "dup-scan", "--queries", "job widget", "--verdict", "duplicate:#77")
        nxt = self.next()
        self.assertEqual((nxt["step"], nxt["actor"]), ("stopped", "stopped"))
        self.assertIn("#77", nxt["why"])
        self.contrib("start", "another thing", "--topic", "other")
        p = self.contrib("stop", "not-omp", "--evidence", "", ok=False)
        self.assertNotEqual(p.returncode, 0, "stopping needs evidence")
        self.contrib("stop", "not-omp", "--evidence", "the bug is in tar")
        self.assertEqual(self.next()["actor"], "stopped")

    def test_the_active_contribution_follows_a_worktree_named_differently(self):
        self.contrib("start", "binary pipe output mojibake")
        wt = self.worktree("me/pipe-bytes")
        nxt = self.next()  # from the checkout, not the worktree
        self.assertEqual((nxt["branch"], nxt["step"]), ("me/pipe-bytes", "dup-scan"))
        self.assertEqual(self.next(cwd=wt)["id"], nxt["id"])

    def test_an_unrecorded_worktree_is_pointed_at_contrib_start(self):
        self.worktree("me/quiet-fix")
        nxt = self.next()
        self.assertEqual((nxt["step"], nxt["actor"]), ("start", "agent"))
        self.assertIn("--branch me/quiet-fix", nxt["command"])
        code, out = self.pq("add", "me/quiet-fix", "--title", "fix(a): x")
        self.assertEqual(code, 1, out)
        self.assertIn("contrib start", out)

    def test_pause_hands_next_to_the_user_until_a_record_or_resume(self):
        self.contrib("start", "job widget mojibake")
        self.contrib("pause", "user will look later")
        nxt = self.next()
        self.assertEqual((nxt["step"], nxt["actor"]), ("paused", "user"))
        self.assertIn("user will look later", nxt["why"])
        self.assertIn("next: paused (user)", omp_flow.gate(self.repo, "me/job-widget-mojibake"))
        self.contrib("resume")
        self.assertEqual(self.next()["step"], "dup-scan")
        self.contrib("pause")
        self.contrib("record", "dup-scan", "--queries", "job widget", "--verdict", "none")
        self.assertEqual(self.next()["actor"], "agent", "a later record lifts the pause")

    def test_run_from_another_repository_it_records_in_the_configured_checkout(self):
        other = os.path.join(self.dir, "plugin")
        sh(self.dir, "git", "init", "-q", other)
        self.contrib("start", "job widget mojibake", "--topic", "job-widget", cwd=other)
        self.assertFalse(os.path.exists(os.path.join(other, ".git", "omp-contrib")))
        nxt = self.next(cwd=other)
        self.assertEqual(nxt["id"], "job-widget")
        self.contrib("record", "dup-scan", "--queries", "job widget", "--verdict", "none", cwd=other)
        self.assertIn(f"git -C {self.repo} ", self.next(cwd=other)["command"])


if __name__ == "__main__":
    unittest.main()
