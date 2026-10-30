"""PR references in our commit messages written as `PR N` (omp_queue.quiet_refs): the rewrite itself,
the replay rewrite `advance` and `quiet-refs` use, and the commit-msg hook with its installer, each on a
scratch repo. Run: python3 -m unittest discover -s tests"""
import os
import subprocess
import sys
import tempfile
import unittest

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
import omp_queue  # noqa: E402

ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.test",
       "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.test"}


def sh(cwd, *args, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=ENV)
    if check and p.returncode:
        raise AssertionError(f"{' '.join(args)}: {p.stderr}{p.stdout}")
    return p.stdout.strip()


class QuietRefsTest(unittest.TestCase):
    def test_each_github_reference_form_is_written_without_a_link(self):
        cases = {
            "fix: take #15191's mode": "fix: take PR 15191's mode",
            "see can1357/oh-my-pi#15193 and trycua/cua#88": "see PR 15193 and trycua/cua PR 88",
            "per https://github.com/can1357/oh-my-pi/pull/15920#discussion_r1 now": "per PR 15920 now",
            "https://github.com/can1357/oh-my-pi/issues/12 and GH-9": "issue 12 and PR 9",
            "after PR #5, issue #6 and pull request #7": "after PR 5, issue 6 and pull request 7",
            "(#15000)": "(PR 15000)",
        }
        for text, want in cases.items():
            self.assertEqual(omp_queue.quiet_refs(text), want, text)
            self.assertEqual(omp_queue.quiet_refs(want), want, "a rewritten message stays as it is")

    def test_text_that_links_nothing_is_left_alone(self):
        for text in ("entity &#123; stays", "a#12 is no reference", "url /x#12 anchor", "## heading", "PR 15920"):
            self.assertEqual(omp_queue.quiet_refs(text), text)


class Repo:
    def __init__(self, tmp):
        self.dir = os.path.join(tmp, "repo")
        os.makedirs(self.dir)
        sh(self.dir, "git", "init", "-q", "-b", "main")
        sh(self.dir, "git", "config", "commit.gpgsign", "false")
        self.n = 0

    def commit(self, message, *extra, path="f.txt"):
        self.n += 1
        with open(os.path.join(self.dir, path), "a") as f:
            f.write(f"{self.n}\n")
        sh(self.dir, "git", "add", "-A")
        sh(self.dir, "git", "commit", "-q", "-m", message, *extra)
        return sh(self.dir, "git", "rev-parse", "HEAD")

    def message(self, ref="HEAD"):
        return sh(self.dir, "git", "log", "-1", "--format=%B", ref)


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.tmp.name)
        self.base = self.repo.commit("base, see #1")
        sh(self.repo.dir, "git", "checkout", "-q", "-b", "octo-fork/x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_commits_the_rebase_created_are_reworded_and_trees_stay(self):
        kept = self.repo.commit("fix: kept, names #2")
        self.repo.commit("fix: replayed, no reference")
        self.repo.commit("fix: replayed, names #3\n\nBody: can1357/oh-my-pi#4.")
        before = sh(self.repo.dir, "git", "rev-parse", "HEAD^{tree}")
        self.assertEqual(omp_queue.quiet_replayed(self.repo.dir, self.base, [kept]), 1)
        log = sh(self.repo.dir, "git", "log", "--format=%H %s", f"{self.base}..HEAD").splitlines()
        self.assertEqual([line.split(" ", 1)[1] for line in log],
                         ["fix: replayed, names PR 3", "fix: replayed, no reference", "fix: kept, names #2"])
        self.assertEqual(log[2].split()[0], kept, "a commit already pushed keeps its SHA: no push of its own")
        self.assertEqual(self.repo.message(), "fix: replayed, names PR 3\n\nBody: PR 4.")
        self.assertEqual(sh(self.repo.dir, "git", "rev-parse", "HEAD^{tree}"), before)
        self.assertEqual(self.repo.message(self.base), "base, see #1", "upstream's commits are not ours to reword")
        self.assertEqual(sh(self.repo.dir, "git", "symbolic-ref", "--short", "HEAD"), "octo-fork/x")
        self.assertEqual(sh(self.repo.dir, "git", "status", "--porcelain"), "")

    def test_authors_and_dates_are_kept(self):
        self.repo.commit("fix: names #5", "--date", "2026-10-01T10:00:00+0200")
        old = sh(self.repo.dir, "git", "log", "-1", "--format=%an|%ae|%ad|%cn|%ce|%cd")
        omp_queue.quiet_replayed(self.repo.dir, self.base, [])
        self.assertEqual(sh(self.repo.dir, "git", "log", "-1", "--format=%an|%ae|%ad|%cn|%ce|%cd"), old)

    def test_the_cli_keeps_the_pushed_copy(self):
        pushed = self.repo.commit("fix: pushed, names #6")
        sh(self.repo.dir, "git", "update-ref", "refs/remotes/fork/octo-fork/x", pushed)
        self.repo.commit("fix: new, names #7")
        out = sh(self.repo.dir, sys.executable, os.path.join(SCRIPTS, "quiet-refs"), "--onto", self.base)
        self.assertEqual(out, "1 commit message(s) reworded")
        self.assertEqual(self.repo.message(), "fix: new, names PR 7")
        self.assertEqual(sh(self.repo.dir, "git", "rev-parse", "HEAD^"), pushed)

    def test_detached_head_requests_an_explicit_kept_ref_without_traceback(self):
        sh(self.repo.dir, "git", "checkout", "--detach", "-q")
        result = subprocess.run([sys.executable, os.path.join(SCRIPTS, "quiet-refs"), "--onto", self.base],
                                cwd=self.repo.dir, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("detached HEAD: pass --kept", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        out = sh(self.repo.dir, sys.executable, os.path.join(SCRIPTS, "quiet-refs"),
                 "--onto", self.base, "--kept")
        self.assertEqual(out, "no replayed commit names a PR as #N")


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.tmp.name)
        self.repo.commit("base")
        self.hooks = os.path.join(self.repo.dir, ".git", "hooks")
        os.makedirs(self.hooks, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        return sh(self.repo.dir, sys.executable, os.path.join(SCRIPTS, "hooks", "install"), self.repo.dir)

    def test_a_will_branch_commit_names_prs_without_linking_them(self):
        self.install()
        sh(self.repo.dir, "git", "checkout", "-q", "-b", "octo-fork/x")
        self.repo.commit("fix: take #15191's mode\n\nAs can1357/oh-my-pi#15193 asked.")
        self.assertEqual(self.repo.message(), "fix: take PR 15191's mode\n\nAs PR 15193 asked.")

    def test_other_branches_and_merges_keep_their_message(self):
        self.install()
        self.repo.commit("chore: on main, #1")
        self.assertEqual(self.repo.message(), "chore: on main, #1")
        sh(self.repo.dir, "git", "checkout", "-q", "-b", "side")
        self.repo.commit("side work", path="side.txt")
        sh(self.repo.dir, "git", "checkout", "-q", "-b", "octo-fork/y", "main")
        self.repo.commit("fix: ours")
        sh(self.repo.dir, "git", "merge", "-q", "--no-ff", "side", "-m", "Merge PR #9 from upstream")
        self.assertEqual(self.repo.message(), "Merge PR #9 from upstream")

    def test_install_chains_an_existing_hook_and_reruns_as_a_no_op(self):
        old = os.path.join(self.hooks, "commit-msg")
        with open(old, "w") as f:
            f.write("#!/bin/sh\nprintf '\\nChained: #3\\n' >> \"$1\"\n")
        os.chmod(old, 0o755)
        self.assertIn("kept the existing hook", self.install())
        self.assertIn("already installed", self.install())
        sh(self.repo.dir, "git", "checkout", "-q", "-b", "octo-fork/z")
        self.repo.commit("fix: z")
        self.assertEqual(self.repo.message(), "fix: z\n\nChained: PR 3", "the old hook ran first, then ours")
        os.remove(old)
        os.symlink("/bin/false", old)
        with self.assertRaises(AssertionError, msg="a second foreign hook beside the chained one is refused"):
            self.install()


if __name__ == "__main__":
    unittest.main()
