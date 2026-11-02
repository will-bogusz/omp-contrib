"""pr-trace --learn: maintainer work on a merged PR of ours before the merge, inside the merge commit
and on main after it (2026-11-02: 8 of 13 instructive maintainer commits that week landed after the
merge). Each case runs on a real scratch repo. Run: python3 -m unittest discover -s tests"""
import atexit
import datetime
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
loader = importlib.machinery.SourceFileLoader("pr_trace_learn", os.path.join(SCRIPTS, "pr-trace"))
spec = importlib.util.spec_from_loader("pr_trace_learn", loader)
PT = importlib.util.module_from_spec(spec)
loader.exec_module(PT)
import omp_pr  # noqa: E402

# Ours is the test fork owner; H4vC commits under a display name with his noreply address, so --learn
# labels him by login; can1357 commits under his login.
OURS = ("Octo Fork", "octo-fork@example.com")
MAINT = ("Maintainer Name", "10531428+H4vC@users.noreply.github.com")
CAN = ("can1357", "can@example.com")
ROBO = ("roboomp", "omp@can.ac")
A = "".join(f"line{i}\n" for i in range(1, 11))


class Repo:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="pr-learn-test-")
        atexit.register(shutil.rmtree, self.root, ignore_errors=True)
        self.clock = datetime.datetime(2026, 10, 29, 10, 0, tzinfo=datetime.timezone.utc)
        self.git("init", "-q", "-b", "main")

    def git(self, *args, who=OURS, check=True):
        self.clock += datetime.timedelta(minutes=1)
        at = self.clock.isoformat()
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1], "GIT_COMMITTER_NAME": who[0],
               "GIT_COMMITTER_EMAIL": who[1], "GIT_AUTHOR_DATE": at, "GIT_COMMITTER_DATE": at}
        p = subprocess.run(["git", *args], cwd=self.root, env=env, capture_output=True, text=True)
        if check and p.returncode:
            raise AssertionError(p.stderr)
        return p.stdout.strip()

    def write(self, files):
        for path, text in files.items():
            full = os.path.join(self.root, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(text)

    def commit(self, msg, files, who=OURS):
        self.write(files)
        self.git("add", "-A", who=who)
        self.git("commit", "-q", "--no-gpg-sign", "-m", msg, who=who)
        return self.git("rev-parse", "HEAD")

    def edit(self, path, old, new):
        with open(os.path.join(self.root, path)) as f:
            return {path: f.read().replace(old, new)}


class LearnTest(unittest.TestCase):
    """PR #500: we rewrote a.ts lines 2-6 and b.ts; H4vC pushed one commit to our branch, resolved
    b.ts's conflict toward main and edited c.ts inside the merge, then worked on main after it."""

    @classmethod
    def setUpClass(cls):
        r = cls.repo = Repo()
        r.commit("init", {"src/a.ts": A, "src/b.ts": "b1\nb2\n", "src/c.ts": "c1\nc2\n", "src/d.ts": "d\n",
                          **{f"src/sweep/{i}.ts": "x\n" for i in range(51)}})
        r.git("checkout", "-q", "-b", "octo-fork/x")
        ours = A
        for i in range(2, 7):
            ours = ours.replace(f"line{i}\n", f"ours{i}\n")
        r.commit("fix(a): ours", {"src/a.ts": ours, "src/b.ts": "ours-b\nb2\n"})
        cls.maint_before = r.commit("fixup: tidy on the branch", r.edit("src/a.ts", "line9", "m9"), who=MAINT)
        r.git("checkout", "-q", "main")
        r.commit("feat(b): main's b", {"src/b.ts": "main-b\nb2\n"}, who=MAINT)
        r.git("merge", "--no-ff", "-q", "-m", "Merge PR #500", "octo-fork/x", who=MAINT, check=False)
        r.write({"src/b.ts": "main-b\nb2\n", "src/c.ts": "edit-c\nc2\n"})
        r.git("add", "-A", who=MAINT)
        r.git("commit", "-q", "--no-gpg-sign", "--no-edit", who=MAINT)
        cls.merge = r.git("rev-parse", "HEAD")
        cls.cleanup = r.commit("chore: post-merge cleanup for #500",
                               r.edit("src/a.ts", "ours2\nours3\n", "new2\nnew3\n"), who=MAINT)
        cls.tidy = r.commit("refactor: tidy", r.edit("src/a.ts", "ours4", "new4"), who=CAN)
        r.commit("fix: main's own line", r.edit("src/a.ts", "line10", "new10"), who=MAINT)
        r.commit("fix: ours again", r.edit("src/a.ts", "ours5", "again5"), who=OURS)
        cls.bot = r.commit("chore: note for #500", {"src/d.ts": "e\n"}, who=ROBO)
        sweep = {f"src/sweep/{i}.ts": "y\n" for i in range(51)}
        cls.sweep = r.commit("style: reformat", {**sweep, **r.edit("src/a.ts", "ours6", "new6")}, who=MAINT)
        r.commit("fix: #5000's thing", {"src/d.ts": "f\n"}, who=MAINT)
        r.git("update-ref", "refs/remotes/origin/main", "main")
        cls.cache = tempfile.mkdtemp(prefix="pr-learn-cache-")
        atexit.register(shutil.rmtree, cls.cache, ignore_errors=True)
        cls.now = r.clock + datetime.timedelta(days=1)
        cls.got = omp_pr.merge_learning(500, cls.merge, cwd=r.root, cache=cls.cache, now=cls.now)

    def test_before_inside_and_after_the_merge(self):
        got = self.got
        self.assertEqual([c["sha"] for c in got["before"]], [self.maint_before])
        self.assertEqual(got["in_merge"], [{"path": "src/b.ts", "kind": "resolved", "new": 0},
                                           {"path": "src/c.ts", "kind": "edited", "new": 1}])
        after = [(c["sha"], c["author"], c["lines"], c["named"], c["sweep"]) for c in got["after"]]
        self.assertEqual(after, [(self.cleanup, "H4vC", 2, True, False), (self.tidy, "can1357", 1, False, False),
                                 (self.bot, "roboomp", 0, True, False), (self.sweep, "H4vC", 1, False, True)])
        self.assertFalse(got["final"])
        self.assertEqual(omp_pr.learn_line(got), "post-merge: H4vC 1 commit(s) rewrote 2 of our lines; can1357 1 "
                                                 "commit(s) rewrote 1 of our lines; roboomp 1 commit(s) rewrote 0 of "
                                                 "our lines; 1 sweep(s); edited in merge")

    def test_report_labels(self):
        pr = {"number": 500, "title": "fix(a): ours", "mergedBy": {"login": "H4vC"}}
        text = PT.learn_report(pr, self.got)
        self.assertIn(f"#500 merged ", text)
        self.assertIn(f"  before merge  {self.maint_before[:10]} H4vC     fixup: tidy on the branch", text)
        self.assertIn("  in merge      maintainer edits: resolved src/b.ts; edited src/c.ts (1 new line(s))  "
                      f"(git show --remerge-diff {self.merge[:10]})", text)
        self.assertIn(f"  post-merge    {self.cleanup[:10]} H4vC     rewrote 2 of our lines, names #500: "
                      "chore: post-merge cleanup for #500", text)
        self.assertIn(f"  sweep         {self.sweep[:10]} H4vC     rewrote 1 of our lines, 52 files: style: reformat", text)
        self.assertLess(text.index("post-merge"), text.index("  sweep"))

    def test_cache_is_incremental_then_final(self):
        r = self.repo
        cache = tempfile.mkdtemp(prefix="pr-learn-cache-")
        self.addCleanup(shutil.rmtree, cache, ignore_errors=True)
        first = omp_pr.merge_learning(500, self.merge, cwd=r.root, cache=cache, now=self.now)
        self.assertEqual(omp_pr.merge_learning(500, self.merge, cwd=r.root, cache=cache, scan=False), first)
        with mock.patch.object(omp_pr, "rewritten_lines", side_effect=AssertionError("rescanned")):
            again = omp_pr.merge_learning(500, self.merge, cwd=r.root, cache=cache, now=self.now)
        self.assertEqual(again["after"], first["after"], "nothing new on main: nothing blamed again")
        late = omp_pr.merge_learning(500, self.merge, cwd=r.root, cache=cache, now=self.now + datetime.timedelta(days=8))
        self.assertTrue(late["final"])
        with mock.patch.object(omp_pr, "run", side_effect=AssertionError("touched git")):
            self.assertEqual(omp_pr.merge_learning(500, self.merge, cwd=r.root, cache=cache), late)

    def test_a_squash_landed_closed_pr_counts_through_the_maintainers_commit(self):
        r = Repo()
        r.commit("init", {"src/a.ts": A})
        r.commit("fix(a): ours (#600)", r.edit("src/a.ts", "line1", "will1"), who=OURS)
        landed = r.commit("fix(a): theirs (#600)", r.edit("src/a.ts", "line2", "m2"), who=MAINT)
        later = r.commit("chore: post-merge cleanup for #600", r.edit("src/a.ts", "m2", "new2"), who=MAINT)
        r.git("update-ref", "refs/remotes/origin/main", "main")
        self.assertEqual(omp_pr.landed_commit(600, "2026-10-29T00:00:00Z", cwd=r.root), landed)
        self.assertIsNone(omp_pr.landed_commit(601, "2026-10-29T00:00:00Z", cwd=r.root))
        cache = tempfile.mkdtemp(prefix="pr-learn-cache-")
        self.addCleanup(shutil.rmtree, cache, ignore_errors=True)
        got = omp_pr.merge_learning(600, landed, landed=True, cwd=r.root, cache=cache, now=r.clock)
        self.assertEqual([(c["sha"], c["lines"], c["named"]) for c in got["after"]], [(later, 1, True)])
        text = PT.learn_report({"number": 600, "title": "t", "headRefOid": "f" * 40}, got)
        self.assertIn(f"#600 closed, squash-landed by H4vC as {landed[:10]}", text)
        self.assertIn(f"git diff ffffffffff {landed[:10]}", text)


class LearnSummaryTest(unittest.TestCase):
    def test_summary_scans_a_capped_number_of_new_merges_and_reuses_the_cache(self):
        merges = [{"number": n, "merge_commit": f"{n}" * 8} for n in (1, 2, 3)]
        cached = {"after": [{"author": "H4vC", "lines": 30, "sweep": False}] * 2, "in_merge": [], "final": True}

        def learning(number, merge, scan=True, **_):
            if number == 3:
                return cached
            return None if not scan else {"after": [], "in_merge": [{"kind": "edited"}], "final": False}

        with mock.patch.object(PT, "merge_learning", side_effect=learning) as ml:
            PT.learn_counts(merges, cap=1)
        self.assertEqual([m["learn"] for m in merges], ["post-merge: edited in merge",
                                                        "post-merge: not scanned yet (pr-trace --learn 2)",
                                                        "post-merge: H4vC 2 commit(s) rewrote 60 of our lines"])
        self.assertEqual(sum(1 for c in ml.call_args_list if c.kwargs.get("scan", True)), 1, "the final cache is reused")
        line = PT.merge_line({"number": 3, "merged_at": "2026-11-02T12:00:00Z", "merged_by": "H4vC",
                              "release": "unreleased", "title": "t", "maintainer_commits": [], **merges[2]})
        self.assertIn("\n         post-merge: H4vC 2 commit(s) rewrote 60 of our lines", line)


if __name__ == "__main__":
    unittest.main()
