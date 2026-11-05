"""pr-trace's Codex state and next steps (workflow step 7), on GraphQL-
shaped fixtures, and its conflict and release helpers. Run: python3 -m unittest discover -s tests"""
import atexit
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
loader = importlib.machinery.SourceFileLoader("pr_trace", os.path.join(SCRIPTS, "pr-trace"))
spec = importlib.util.spec_from_loader("pr_trace", loader)
PT = importlib.util.module_from_spec(spec)
loader.exec_module(PT)
import omp_pr  # noqa: E402

CODEX = "chatgpt-codex-connector[bot]"
OLD, NEW = "a" * 40, "b" * 40


def badge(p):
    return f"**<sub><sub>![{p} Badge](https://img.shields.io/badge/{p}-orange?style=flat)</sub></sub>  Finding**"


def review(rid, at, sha, body="### 💡 Codex Review"):
    return {"id": rid, "url": f"https://x/{rid}", "submittedAt": at, "body": body,
            "author": {"login": CODEX}, "commit": {"oid": sha}}


def thread(tid, rid, p, last=CODEX, resolved=False, path="src/a.ts", reply=""):
    opener = {"author": {"login": CODEX}, "body": badge(p), "pullRequestReview": {"id": rid}}
    replies = [] if last == CODEX else [{"author": {"login": last}, "body": reply, "url": f"https://x/{tid}#r"}]
    return {"id": tid, "isResolved": resolved,
            "opener": {"nodes": [opener]},
            "latest": {"nodes": [{"author": {"login": last}, "path": path, "url": f"https://x/{tid}"}]},
            "all": {"nodes": [{**opener, "url": f"https://x/{tid}#o"}] + replies}}


def summary(status, sha, at):
    return {"body": f"{PT.CODEX_SUMMARY}\n\n| Review | Status | Commit | Review trigger |\n| --- | --- | --- | --- |\n"
                    f"| 📝 **Code Review** | ✅ **{status}** <relative-time datetime=\"{at}\">{at}</relative-time> "
                    f"| `{sha[:7]}` | New commits |\n"}


def pr(head, comments=(), author="octo-fork", pushed="2026-10-13T00:00:00Z"):
    return {"headRefOid": head, "comments": list(comments), "isDraft": False, "number": 1,
            "commits": [{"oid": head, "authors": [{"login": author}], "committedDate": pushed}]}


def pull(reviews=(), threads=(), thumbs=(), eyes=()):
    return {"reviews": {"nodes": list(reviews)}, "reviewThreads": {"nodes": list(threads)},
            "reactions": {"nodes": [{"content": kind, "createdAt": at, "user": {"login": CODEX}}
                                    for kind, ats in (("THUMBS_UP", thumbs), ("EYES", eyes)) for at in ats]}}


def rounds(n, sha=OLD, last=CODEX, path="src/a.ts"):
    """n Codex rounds, the last on `sha`, each with one P2 thread; the last one's reply by `last`."""
    reviews = [review(f"R{i}", f"2026-10-13T1{i}:00:00Z", sha if i == n - 1 else "c" * 40) for i in range(n)]
    threads = [thread(f"T{i}", f"R{i}", "P2", last=last if i == n - 1 else "octo-fork", path=path)
               for i in range(n)]
    return pull(reviews, threads)


class CodexSettleTest(unittest.TestCase):
    def test_findings_then_a_clean_pass_is_clean(self):
        data = pull([review("R1", "2026-10-13T10:00:00Z", OLD)], [thread("T1", "R1", "P1", last="octo-fork")])
        clean = summary("Completed", NEW, "2026-10-13T11:00:00.123456Z")
        self.assertEqual(PT.codex_settle(pr(NEW, [clean]), data), "clean")

    def test_open_finding_on_head_needs_a_fix_and_after_the_fix_push_waits(self):
        data = pull([review("R1", "2026-10-13T10:00:00Z", OLD)], [thread("T1", "R1", "P1")])
        on_old = summary("Completed", OLD, "2026-10-13T10:00:02Z")
        self.assertEqual(PT.codex_settle(pr(OLD, [on_old]), data), "fix")
        self.assertEqual(PT.codex_settle(pr(NEW, [on_old]), data), "pushed")

    def test_open_p2_on_head_is_fix_or_decline_not_settled(self):
        data = pull([review("R1", "2026-10-13T10:00:00Z", OLD)], [thread("T1", "R1", "P2")])
        self.assertEqual(PT.codex_settle(pr(OLD), data), "fix")

    def test_every_finding_answered_on_head_settles(self):
        data = pull([review("R1", "2026-10-13T10:00:00Z", OLD)], [thread("T1", "R1", "P2", last="octo-fork")])
        self.assertEqual(PT.codex_settle(pr(OLD), data), "settled")

    def test_thumbs_up_is_clean_and_a_later_finding_reopens(self):
        observed = {**pr(OLD), "observedAt": "2026-10-13T08:00:00Z"}
        self.assertEqual(PT.codex_settle(observed, pull(thumbs=["2026-10-13T09:00:00Z"])), "clean")
        later = pull([review("R2", "2026-10-13T12:00:00Z", NEW)], [thread("T2", "R2", "P2")],
                     thumbs=["2026-10-13T09:00:00Z"])
        self.assertEqual(PT.codex_settle(pr(NEW), later), "fix")

    def test_round_budget(self):
        self.assertEqual(PT.codex_settle(pr(OLD), rounds(PT.CODEX_ROUND_BUDGET - 1)), "fix")
        self.assertEqual(PT.codex_settle(pr(OLD), rounds(PT.CODEX_ROUND_BUDGET)), "budget")

    def test_hand_off_ends_the_budget(self):
        """once the maintainer has the PR, every valid finding is ours."""
        self.assertEqual(PT.codex_settle(pr(OLD), rounds(PT.CODEX_ROUND_BUDGET), handed=True), "fix")
        self.assertEqual(PT.codex_settle(pr(OLD), rounds(PT.CODEX_ROUND_BUDGET, last="octo-fork"), handed=True),
                         "settled")

    def test_maintainer_head_hands_codex_to_him(self):
        """The user's commits from a second account carry another login (`octo-fork-alt`)."""
        data = pull([review("R1", "2026-10-13T10:00:00Z", OLD)], [thread("T1", "R1", "P2")])
        self.assertEqual(PT.codex_settle(pr(OLD, author="H4vC"), data), "maintainer")
        self.assertEqual(PT.codex_settle(pr(OLD, author="octo-fork-alt"), data), "fix")

    def test_no_pass_yet(self):
        self.assertIsNone(PT.codex_settle(pr(OLD), pull()))

    def test_findings_in_the_review_body_are_open_until_a_comment_of_ours_links_it(self):
        """Codex writes some findings in its review body with no thread (`codex-code-review-finding`;
        #15174, #16119 on 2026-10-18). Old code read such a pass on the head as settled."""
        body = body_review("2026-10-13T10:00:00Z", [("P1", "src/t.ts", 1360), ("P2", "src/b.ts", 330)])["body"]
        data = pull([review("R1", "2026-10-13T10:00:00Z", OLD, body)])
        self.assertEqual(PT.codex_settle(pr(OLD), data), "fix")
        waiting, p2, _ = PT.review_threads(data, pr(OLD))
        self.assertEqual((waiting, p2), ([f"{PT.CODEX} on src/t.ts: https://x/R1"], [f"{PT.CODEX} on src/b.ts: https://x/R1"]))
        answer = {"author": {"login": "octo-fork"}, "createdAt": "2026-10-13T11:00:00Z",
                  "body": "Fixed in abc1234: both findings of https://x/R1."}
        self.assertEqual(PT.codex_settle(pr(OLD, [answer]), data), "settled")
        out = PT.codex_outcome(pr(OLD, pushed="2026-10-13T09:50:00Z"), data, PT.stamp("2026-10-13T12:00:00Z"))
        self.assertEqual(out, ("findings", "2 finding(s) on the head: https://x/R1"))


class CodexHeadTest(unittest.TestCase):
    """Codex's 👀 on the PR body is its pass in progress (#15184, #15175, 2026-10-18): up when the pass
    starts, removed when it ends; a dead pass leaves it up (#15418). Each state on a fixed clock."""
    NOW = PT.stamp("2026-10-18T01:00:00Z")

    def ago(self, minutes):
        return (self.NOW - PT.datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def state(self, comments, data, pushed_ago=60, head=NEW):
        p = pr(head, comments, pushed=self.ago(pushed_ago))
        return PT.codex_head(p, data, self.NOW), PT.codex_outcome(p, data, self.NOW)

    def test_eyes_up_is_reviewing_even_after_a_late_start(self):
        """Push 40 min ago, 👀 up 5 min: Codex started past the old 30-min wait and is reviewing."""
        self.assertEqual(self.state([summary("Completed", OLD, self.ago(90))], pull(eyes=[self.ago(5)]), 40),
                         ("running", None))

    def test_running_row_before_eyes_land_is_reviewing(self):
        self.assertEqual(self.state([summary("Running", NEW, self.ago(0.5))], pull()), ("running", None))

    def test_eyes_gone_with_thumbs_up_is_clean(self):
        data = pull(thumbs=[self.ago(10)])
        self.assertEqual(self.state([summary("Completed", NEW, self.ago(10))], data, 25),
                         (None, ("clean", "clean pass on the head (👍)")))

    def test_eyes_gone_with_a_review_on_the_head_is_findings_with_count(self):
        data = pull([review("R1", self.ago(70), OLD), review("R2", self.ago(5), NEW)],
                    [thread("T1", "R1", "P2"), thread("T2", "R2", "P1"), thread("T3", "R2", "P2")])
        head, out = self.state([summary("Completed", NEW, self.ago(5))], data, 20)
        self.assertIsNone(head)
        self.assertEqual(out, ("findings", "2 finding(s) on the head: https://x/R2"))

    def test_running_row_without_eyes_ended_without_a_result(self):
        """Old code read the `Running` row as reviewing for 30 min, and as nothing after."""
        for started in (10, 24 * 60):
            head, out = self.state([summary("Running", NEW, self.ago(started))], pull())
            self.assertEqual(head, "ended")
            self.assertEqual(out[0], "failed")
            self.assertIn("ended without a result", out[1])
        self.assertEqual(PT.CODEX_FLAG["ended"], "Codex pass ended without a result")

    def test_failed_row_on_the_head_is_no_result(self):
        self.assertEqual(self.state([summary("Failed", NEW, self.ago(10))], pull()),
                         ("ended", ("failed", "no result: Codex pass failed")))

    def test_stale_eyes_is_possibly_stuck_not_reviewing_forever(self):
        """#15418: 👀 and the `Running` row up since 2026-10-14 23:31, three days on."""
        head, out = self.state([summary("Running", NEW, self.ago(3 * 24 * 60))], pull(eyes=[self.ago(3 * 24 * 60)]))
        self.assertEqual(head, "stuck")
        self.assertEqual(out[0], "failed")
        self.assertIn("possibly stuck", out[1])
        fresh = self.state([summary("Running", NEW, self.ago(40))], pull(eyes=[self.ago(40)]))
        self.assertEqual(fresh, ("running", None))

    def test_stale_eyes_from_a_dead_pass_does_not_hide_a_new_push(self):
        data = pull(eyes=[self.ago(3 * 24 * 60)])
        self.assertEqual(self.state([summary("Running", OLD, self.ago(3 * 24 * 60))], data, 5), ("due", None))

    def test_no_eyes_after_a_push_is_due_then_never_started(self):
        row = [summary("Completed", OLD, self.ago(90))]
        self.assertEqual(self.state(row, pull(), 5), ("due", None))
        head, out = self.state(row, pull(), 31)
        self.assertIsNone(head)
        self.assertEqual(out[0], "never")
        self.assertIn("no 👀 within 30 min of the push", out[1])

    def test_an_old_thumbs_up_is_not_a_clean_pass_on_a_new_head(self):
        head, out = self.state([summary("Completed", OLD, self.ago(90))], pull(thumbs=[self.ago(90)]), 45)
        self.assertEqual(out[0], "never")

    def test_running_and_due_wait_others_do_not(self):
        step = CodexNextStepTest().step(codex="running")
        self.assertTrue(step.startswith("wait for Codex's pass on the head: `pr-trace --wait-codex 1`"), step)
        for state in ("ended", "stuck"):
            self.assertTrue(CodexNextStepTest().step(codex=state).startswith("nothing to do"))


class WaitCodexTest(unittest.TestCase):
    """`pr-trace --wait-codex`: returns once every pass ended; exit 4 on findings, 3 on timeout."""

    def setUp(self):
        # No fork/ reflog: the host's real checkout must not hold these waits (unseen_push).
        patcher = mock.patch.object(PT, "CHECKOUT", tempfile.mkdtemp(prefix="pr-trace-nogit-"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_wait(self, nodes, minutes=60):
        polls = iter(nodes)
        out = io.StringIO()
        last = nodes[-1]
        with mock.patch.object(PT, "poll_prs", side_effect=lambda *a: ("m1", {1: next(polls, last)}, None)), \
             mock.patch.object(PT.time, "sleep"), mock.patch("sys.stdout", out):
            code = PT.wait_codex([1], minutes)
        return code, out.getvalue()

    def node(self, comments, pushed, reviews=(), threads=(), eyes=()):
        node = gnode(comments=comments, reviews=reviews, threads=threads,
                     reactions=[{"content": "EYES", "createdAt": at, "user": {"login": CODEX}} for at in eyes])
        for c in node["commits"]["nodes"]:
            c["commit"]["committedDate"] = pushed
        return node

    def test_waits_through_the_pass_and_reports_findings(self):
        now = PT.datetime.datetime.now(PT.datetime.timezone.utc)
        at = (now - PT.datetime.timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        running = self.node([summary("Running", NEW, at)], at, eyes=[at])
        done = self.node([summary("Completed", NEW, at)], at,
                         reviews=[{**review("R1", at, NEW), "author": {"__typename": "Bot", "login": CODEX}}],
                         threads=[("T1", [{**note("C1", CODEX, badge("P2"), kind="Bot"),
                                           "pullRequestReview": {"id": "R1"}}])])
        code, text = self.run_wait([running, done])
        self.assertEqual(code, 4)
        self.assertEqual(text, f"#1 {NEW[:10]} findings: 1 finding(s) on the head: https://x/R1\n")

    def test_timeout_lists_the_pass_still_running(self):
        at = PT.datetime.datetime.now(PT.datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        code, text = self.run_wait([self.node([summary("Running", NEW, at)], at, eyes=[at])], minutes=1e-9)
        self.assertEqual(code, 3)
        self.assertIn("timeout: still reviewing (👀 up)", text)

    def test_a_head_committed_long_before_its_push_is_not_never_at_once(self):
        """#15563, 2026-10-18: committed 05:30Z, pushed ~05:37Z after its tests; the wait read `never` early."""
        old = (PT.datetime.datetime.now(PT.datetime.timezone.utc) - PT.datetime.timedelta(minutes=40)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        code, text = self.run_wait([self.node([summary("Completed", OLD, old)], old)], minutes=1e-9)
        self.assertEqual(code, 3)
        self.assertIn("timeout: Codex not started yet", text)

    def test_a_closed_pr_ends_its_wait(self):
        code, text = self.run_wait([gnode(state="CLOSED")])
        self.assertEqual(code, 0)
        self.assertIn("closed: closed: nothing to wait for", text)

    def test_recorded_post_push_wait_refreshes_previous_head(self):
        """#18013 returned 1b44660581 after pushing 189868ab64; #18012 had the same cache risk.
        REST commit/review/reaction fields and GraphQL summary edit bodies recorded 2026-11-03.
        The old code reuses the recent cached node, sees Completed on that old head, and exits."""
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "codex-head-2026-11-03.json")) as f:
            recorded = json.load(f)
        for number, payload in recorded.items():
            with self.subTest(pr=number):
                old_summary = payload["summary_edits"][2]["body"]
                short = PT.CODEX_SUMMARY_ROW.search(old_summary).group(2)
                old_commit = next(c for c in payload["commits"] if c["sha"].startswith(short))
                head_commit = payload["commits"][-1]
                cached = gnode(head=old_commit["sha"], comments=[{"body": old_summary}])
                fresh = gnode(head=head_commit["sha"],
                              comments=[{"body": payload["summary_edits"][0]["body"]}])
                calls = []

                def poll(numbers, max_age):
                    calls.append(max_age)
                    return "main", {int(number): fresh if max_age == 0 else cached}, None

                out = io.StringIO()
                with mock.patch.object(PT, "poll_prs", side_effect=poll), mock.patch("sys.stdout", out):
                    code = PT.wait_codex([int(number)], 0)
                self.assertEqual(code, 0)
                self.assertIn(f"#{number} {head_commit['sha'][:10]} clean:", out.getvalue())
                self.assertEqual(calls, [0, 0])

    def test_terminal_result_is_rechecked_if_head_moves_during_wait(self):
        at = PT.datetime.datetime.now(PT.datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cached = gnode(head=OLD, comments=[summary("Completed", OLD, at)])
        running = gnode(head=NEW, comments=[summary("Running", NEW, at)])
        done = gnode(head=NEW, comments=[summary("Completed", NEW, at)])
        code, text = self.run_wait([cached, running, done])
        self.assertEqual(code, 0)
        self.assertEqual(text, f"#1 {NEW[:10]} clean: clean pass on the head\n")

    def test_clean_summary_on_previous_head_is_not_clean_after_push(self):
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "codex-head-2026-11-03.json")) as f:
            payload = json.load(f)["18013"]
        p = pr(payload["commits"][-1]["sha"], [{"body": payload["summary_edits"][2]["body"]}],
               pushed=payload["commits"][-1]["commit"]["committer"]["date"])
        self.assertEqual(PT.codex_settle(p, pull()), "pushed")
        self.assertIsNone(PT.codex_outcome(p, pull(), PT.stamp("2026-11-03T23:05:11Z")))

    def test_sha_less_reaction_needs_observed_head_boundary(self):
        p = pr(NEW, pushed="2026-10-13T08:00:00Z")
        data = pull(thumbs=["2026-10-13T09:00:00Z"])
        self.assertFalse(PT.codex_clean(p, data))  # commit time cannot establish a push
        p["observedAt"] = "2026-10-13T09:00:00Z"
        self.assertFalse(PT.codex_clean(p, data))  # same-second race is ambiguous
        p["observedAt"] = "2026-10-13T08:59:59Z"
        self.assertTrue(PT.codex_clean(p, data))
        p["comments"] = [summary("Completed", OLD, "2026-10-13T09:00:00Z")]
        self.assertFalse(PT.codex_clean(p, data))  # explicit different-head evidence wins

    def pushed_repo(self):
        """A checkout that pushed octo-fork/x twice to a bare `fork`: (root, git, first sha, second sha)."""
        root, git = git_repo()
        bare = tempfile.mkdtemp(prefix="pr-trace-fork-")
        atexit.register(shutil.rmtree, bare, ignore_errors=True)
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        git("remote", "add", "fork", bare)
        git("checkout", "-q", "-b", "octo-fork/x")
        old = commit(root, git, "src/a.ts", "one\n", "fix: one")
        git("push", "-q", "fork", "octo-fork/x")
        new = commit(root, git, "src/a.ts", "two\n", "fix: two")
        git("push", "-q", "fork", "octo-fork/x")
        return root, git, old, new

    def test_recorded_wait_right_after_a_push_holds_until_github_shows_it(self):
        """#18013 (2026-11-03): after pushing 1b44660581..189868ab64 the wait returned 1b44660581's
        clean pass in 5 s. Until GitHub shows a push, a fresh poll serves the old head and its
        Completed row as well as a cached one does; only this host's fork remote reflog knows."""
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "codex-head-2026-11-03.json")) as f:
            edits = json.load(f)["18013"]["summary_edits"]
        root, _, old, new = self.pushed_repo()

        def body(edit, sha):  # the recorded row, on this repo's commits
            got = re.search(r'"commit_sha":"([0-9a-f]{40})"', edit["body"]).group(1)
            return {"body": edit["body"].replace(got, sha).replace(got[:7], sha[:7])}

        lagging = gnode(head=old, comments=[body(edits[2], old)])
        done = gnode(head=new, commits=[(old, "octo-fork", "fix: one"), (new, "octo-fork", "fix: two")],
                     comments=[body(edits[0], new)])
        with mock.patch.object(PT, "CHECKOUT", root):
            code, text = self.run_wait([lagging, lagging, lagging, done])
        self.assertEqual(code, 0)
        self.assertEqual(text, f"#1 {new[:10]} clean: clean pass on the head\n")

    def test_a_push_github_never_shows_holds_until_the_timeout_and_then_lapses(self):
        root, _, old, new = self.pushed_repo()
        lagging = gnode(head=old, comments=[summary("Completed", old, "2026-11-03T22:52:00Z")])
        with mock.patch.object(PT, "CHECKOUT", root):
            code, text = self.run_wait([lagging], minutes=1e-9)
            self.assertEqual(code, 3)
            self.assertEqual(text, f"#1 {new[:10]} timeout: GitHub does not show this push yet\n")
            later = PT.datetime.datetime.now(PT.datetime.timezone.utc) + PT.PUSH_LAG
            self.assertIsNone(PT.unseen_push(lagging, later))
        self.assertIsNone(PT.unseen_push({**lagging, "headRefName": "octo-fork/other"}, cwd=root))
        shown = gnode(head="c" * 40, commits=[(new, "octo-fork", "fix: two"), ("c" * 40, "H4vC", "fix: theirs")])
        self.assertIsNone(PT.unseen_push(shown, cwd=root))  # a maintainer pushed on top of ours


def gnode(head=NEW, state="OPEN", draft=False, mergeable="MERGEABLE", commits=None, comments=(), reviews=(),
          threads=(), reactions=()):
    """One PR as CHANGE_QUERY returns it; `commits` [(oid, login, headline)], pushed 3 min ago."""
    at = (PT.datetime.datetime.now(PT.datetime.timezone.utc) - PT.datetime.timedelta(minutes=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    commits = commits or [(head, "octo-fork", "fix: ours")]
    return {"state": state, "isDraft": draft, "mergeable": mergeable, "headRefOid": head, "headRefName": "octo-fork/x",
            "mergedAt": "2026-10-18T05:00:00Z" if state == "MERGED" else None,
            "mergedBy": {"login": "H4vC"} if state == "MERGED" else None, "url": "https://x/pr",
            "commits": {"nodes": [{"commit": {"oid": oid, "messageHeadline": line, "committedDate": at,
                                              "authors": {"nodes": [{"user": {"login": login}, "name": login}]}}}
                                  for oid, login, line in commits]},
            "comments": {"nodes": list(comments)}, "reviews": {"nodes": list(reviews)},
            "reviewThreads": {"nodes": [{"id": tid, "isResolved": False, "comments": {"nodes": cs}} for tid, cs in threads]},
            "reactions": {"nodes": list(reactions)}}


def note(cid, login, body="please fix", kind="User", **extra):
    return {"id": cid, "url": f"https://x/{cid}", "body": body, "createdAt": "2026-10-18T05:00:00Z",
            "author": {"__typename": kind, "login": login}, **extra}


class WaitChangeTest(unittest.TestCase):
    """`pr-trace --wait-change`: each kind of change between two polls of one PR, and the wait itself."""

    def setUp(self):
        patches = [mock.patch.object(PT, "run"), mock.patch.object(PT, "conflict_class", return_value="clean")]
        self.conflict = patches[1].start()
        patches[0].start()
        for p in patches:
            self.addCleanup(p.stop)

    def diff(self, before, after, main_before="m1", main_after="m1"):
        prev = PT.change_snapshot(before, main_before)
        return PT.changes(prev, PT.change_snapshot(after, main_after, prev), after)

    def test_nothing_changed_is_no_event(self):
        self.assertEqual(self.diff(gnode(), gnode()), [])

    def test_merge(self):
        self.assertEqual(self.diff(gnode(), gnode(state="MERGED")),
                         [("state", "open -> merged by H4vC at 2026-10-18T05:00:00Z")])

    def test_draft_marked_ready(self):
        self.assertEqual(self.diff(gnode(draft=True), gnode()), [("ready", "draft -> ready")])

    def test_new_head_names_each_maintainer_commit(self):
        """the maintainer merges main into our branch and adds his own commit (#15174, 2026-10-18)."""
        after = gnode(head="d" * 40, commits=[(NEW, "octo-fork", "fix: ours"), ("c" * 40, "H4vC", "Merge main"),
                                              ("d" * 40, "H4vC", "refactor: tidy")])
        found = self.diff(gnode(), after)
        self.assertEqual(found[0], ("head", f"{NEW[:10]} -> {'d' * 10} (2 new commit(s))"))
        self.assertEqual([k for k, _ in found[1:]], ["maintainer-commit", "maintainer-commit"])
        self.assertIn("refactor: tidy by H4vC", found[2][1])

    def test_force_push_of_ours_is_a_head_change_only(self):
        """A second account of the user's writes some of our commits: not a maintainer's."""
        commits = [("f" * 40, "octo-fork-alt", "fix: from a second account"), ("e" * 40, "octo-fork", "fix: ours")]
        found = self.diff(gnode(), gnode(head="e" * 40, commits=commits))
        self.assertEqual(found, [("head", f"{NEW[:10]} -> {'e' * 10} (2 new commit(s), force-pushed)")])

    def test_rebased_head_with_old_commit_times_is_never_only_30_min_after_it_appeared(self):
        """push.sh moved nine drafts to heads committed 40 min earlier (2026-10-18): each read `never` at once."""
        old = (PT.datetime.datetime.now(PT.datetime.timezone.utc) - PT.datetime.timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        before = gnode(comments=[summary("Completed", NEW, old)])
        after = gnode(head="e" * 40, comments=[summary("Completed", NEW, old)])
        for c in after["commits"]["nodes"]:
            c["commit"]["committedDate"] = old
        prev = PT.change_snapshot(before, "m1")
        cur = PT.change_snapshot(after, "m1", prev)
        self.assertEqual([k for k, _ in PT.changes(prev, cur, after)], ["head"])
        later = PT.change_snapshot(after, "m1", cur, PT.datetime.datetime.now(PT.datetime.timezone.utc)
                                   + PT.datetime.timedelta(minutes=31))
        self.assertEqual([k for k, _ in PT.changes(cur, later, after)], ["codex"])
        self.assertIsNone(PT.change_snapshot({**after, "isDraft": True}, "m1", cur)["codex"])

    def test_a_person_comment_review_or_thread_reply_wakes_bots_and_ours_do_not(self):
        quiet = [note("C1", "octo-fork"), note("C3", "chatgpt-codex-connector", kind="Bot")]
        self.assertEqual(self.diff(gnode(), gnode(comments=quiet)), [])
        maint = gnode(comments=[note("C4", "H4vC")], reviews=[note("R1", "H4vC", "Rebase please", state="CHANGES_REQUESTED")],
                     threads=[("T1", [note("C5", "chatgpt-codex-connector", kind="Bot"),
                                      note("C6", "H4vC", "nit", path="src/a.rs")])])
        found = self.diff(gnode(), maint)
        self.assertEqual([k for k, _ in found], ["person"] * 3)
        text = " | ".join(t for _, t in found)
        for part in ("comment by H4vC", "review changes_requested by H4vC", "thread by H4vC 10-18T05:00Z on src/a.rs"):
            self.assertIn(part, text)

    def test_a_roboomp_review_or_comment_wakes_as_roboomp_and_a_person_diff_does_not(self):
        """Three waits slept 40 min past roboomp's reviews (is_person drops it) before this kind existed."""
        before = gnode(comments=[note("C1", "H4vC")])
        reviewed = gnode(comments=[note("C1", "H4vC"), note("C2", "roboomp", "one more thing")],
                         reviews=[note("R1", "roboomp", "lgtm — ready for maintainer merge", state="COMMENTED"),
                                  note("R2", "roboomp", "", state="COMMENTED")],
                         threads=[("T1", [note("C3", "roboomp", "null check here", path="src/a.rs",
                                               pullRequestReview={"id": "R2"})])])
        found = self.diff(before, reviewed)
        self.assertEqual([k for k, _ in found], ["roboomp"] * 3)
        self.assertEqual(found[1][1], "review commented 10-18T05:00Z: lgtm — ready for maintainer merge https://x/R1")
        self.assertIn("review commented 10-18T05:00Z: null check here https://x/R2", found[2][1])
        self.assertIn("comment 10-18T05:00Z: one more thing", found[0][1])
        self.assertEqual([k for k, _ in self.diff(gnode(), gnode(comments=[note("C1", "H4vC")]))], ["person"])

    def test_a_snapshot_saved_before_the_roboomp_key_is_a_baseline(self):
        reviewed = gnode(reviews=[note("R1", "roboomp", "lgtm", state="COMMENTED")])
        old = PT.change_snapshot(gnode(), "m1")
        del old["roboomp"]
        self.assertEqual(PT.changes(old, PT.change_snapshot(reviewed, "m1", old), reviewed), [])

    def test_codex_pass_ending_on_the_head(self):
        at = (PT.datetime.datetime.now(PT.datetime.timezone.utc) - PT.datetime.timedelta(minutes=2)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        eyes = [{"content": "EYES", "createdAt": at, "user": {"login": "chatgpt-codex-connector"}}]
        running = gnode(comments=[summary("Running", NEW, at)], reactions=eyes)
        done = gnode(comments=[summary("Completed", NEW, at)],
                     reviews=[{**review("R1", at, NEW), "author": {"__typename": "Bot", "login": "chatgpt-codex-connector"}}],
                     threads=[("T1", [{**note("C1", "chatgpt-codex-connector", badge("P2"), kind="Bot"),
                                       "pullRequestReview": {"id": "R1"}}])])
        self.assertEqual(self.diff(running, running), [])
        self.assertEqual(self.diff(running, done), [("codex", f"findings on {NEW[:10]}: 1 finding(s) on the head: https://x/R1")])

    def test_github_mergeable_flip_and_unknown_keeps_the_last(self):
        self.assertEqual(self.diff(gnode(), gnode(mergeable="UNKNOWN")), [])
        self.assertEqual(self.diff(gnode(), gnode(mergeable="CONFLICTING")), [("mergeable", "GitHub mergeable -> conflicting")])
        prev = PT.change_snapshot(gnode(), "m1")
        self.conflict.return_value = PT.CHANGELOG_ONLY_CLASS
        after = gnode(mergeable="CONFLICTING")
        self.assertEqual(PT.changes(prev, PT.change_snapshot(after, "m2", prev), after),
                         [("vs-main", f"clean -> {PT.CHANGELOG_ONLY_CLASS}")])

    def test_vs_main_recomputed_when_main_moves_and_drafts_skip_it(self):
        prev = PT.change_snapshot(gnode(), "m1")
        self.conflict.return_value = "REAL: src/a.rs"
        self.assertEqual(PT.changes(prev, PT.change_snapshot(gnode(), "m1", prev), gnode()), [])
        self.assertEqual(PT.changes(prev, PT.change_snapshot(gnode(), "m2", prev), gnode()),
                         [("vs-main", "clean -> REAL: src/a.rs")])
        draft = PT.change_snapshot(gnode(draft=True, mergeable="CONFLICTING"), "m2")
        self.assertEqual((draft["mergeable"], draft["conflict"]), (None, None))

    def run_wait(self, polls, minutes=60, state=None):
        polls = iter(polls)
        out = io.StringIO()
        with mock.patch.object(PT, "poll_prs", side_effect=lambda *a: next(polls)), \
             mock.patch.object(PT.time, "sleep"), mock.patch("sys.stdout", out):
            code = PT.wait_change([1], minutes, state)
        return code, out.getvalue()

    def poll(self, node, main="m1"):
        return main, {1: node}, {"cost": 1, "remaining": 4000, "resetAt": "2026-10-18T06:00:00Z"}

    def test_wait_returns_on_the_first_change(self):
        code, text = self.run_wait([self.poll(gnode(draft=True)), self.poll(gnode(draft=True)), self.poll(gnode())])
        self.assertEqual((code, text), (0, "#1 ready: draft -> ready\n"))

    def test_wait_times_out_with_exit_3(self):
        code, text = self.run_wait([self.poll(gnode())], minutes=1e-9)
        self.assertEqual(code, 3)
        self.assertIn("timeout: no change on #1", text)

    def test_state_file_carries_the_baseline_across_waits(self):
        """A merge that lands between two bounded waits wakes the second one on its first poll."""
        path = os.path.join(tempfile.mkdtemp(), "state.json")
        self.assertEqual(self.run_wait([self.poll(gnode())], minutes=1e-9, state=path)[0], 3)
        self.assertEqual(self.run_wait([self.poll(gnode(state="MERGED"))], state=path)[0], 0)

    def test_a_spent_budget_sleeps_to_the_reset_and_says_so_instead_of_asking_each_interval(self):
        reset = PT.datetime.datetime.now(PT.datetime.timezone.utc) + PT.datetime.timedelta(minutes=30)
        answers = iter([PT.RateLimited(reset), self.poll(gnode()), self.poll(gnode(state="MERGED"))])

        def poll(*a):
            got = next(answers)
            if isinstance(got, Exception):
                raise got
            return got
        err = io.StringIO()
        with mock.patch.object(PT, "poll_prs", side_effect=poll), mock.patch.object(PT.time, "sleep") as sleep, \
                mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", err):
            self.assertEqual(PT.wait_change([1], 60), 0)
        self.assertGreater(sleep.call_args_list[0][0][0], 25 * 60, "slept to the reset, not one poll interval")
        self.assertIn("resets at", err.getvalue())
        self.assertIn("next poll after the reset", err.getvalue())


class ReviewQueryTest(unittest.TestCase):
    """REVIEW_QUERY asks one comments connection per thread (2026-10-18: 1 point instead of 3)."""

    def test_review_data_splits_one_comments_connection_into_opener_latest_all(self):
        c = [{"author": {"login": a}, "body": b, "url": f"u{b}", "path": "p", "line": 1, "pullRequestReview": {"id": "R"}}
             for a, b in (("codex", "1"), ("octo-fork", "2"), ("codex", "3"))]
        data = {"data": {"repository": {"pullRequest": {"reactions": {"nodes": []}, "reviews": {"nodes": []},
                                                        "reviewThreads": {"nodes": [{"id": "T", "isResolved": False,
                                                                                     "comments": {"nodes": c}}]}}}}}
        with mock.patch.object(PT, "gh_json", return_value=data):
            t = PT.review_data(1)["reviewThreads"]["nodes"][0]
        self.assertEqual((t["opener"]["nodes"], t["latest"]["nodes"], t["all"]["nodes"]), ([c[0]], [c[2]], c))
        self.assertNotIn("comments", t)


class MergedCommitsTest(unittest.TestCase):
    def test_merged_commits_come_from_gh_cache_in_by_maintainer_shape(self):
        nodes = [{"commit": {"messageHeadline": h, "authors": {"nodes": [{"user": u}]}}}
                 for h, u in (("fix: ours", {"login": "octo-fork"}), ("refactor: tidy", {"login": "H4vC"}),
                              ("Merge main", {"login": "H4vC"}), ("chore: x", None))]
        listed = [{"number": 7, "title": "t", "url": "u", "mergedAt": "2026-10-18T05:00:00Z",
                   "mergedBy": {"login": "H4vC"}, "mergeCommit": {"oid": "m"}}]
        calls = []

        def gh(*args):
            calls.append(args)
            return listed if args[0] == "pr" else {"data": {"repository": {"pullRequest": {"commits": {"nodes": nodes}}}}}
        with mock.patch.object(omp_pr, "gh_json", gh):
            merges = omp_pr.merged_prs(PT.datetime.date(2026, 10, 17))
        self.assertEqual(merges[0]["maintainer_commits"], ["refactor: tidy"])
        self.assertEqual(calls[1][:4], ("api", "graphql", "--cache", "24h"))



class CodexRepeatsTest(unittest.TestCase):
    def test_third_round_in_one_file_flags_it(self):
        self.assertEqual(PT.codex_repeats(rounds(3)), [("src/a.ts", 3)])
        self.assertEqual(PT.codex_repeats(rounds(2)), [])

    def test_latest_round_elsewhere_does_not(self):
        data = rounds(3)
        data["reviewThreads"]["nodes"][-1]["latest"]["nodes"][0]["path"] = "src/b.ts"
        self.assertEqual(PT.codex_repeats(data), [])


class CodexNextStepTest(unittest.TestCase):
    P2 = ["chatgpt-codex-connector on src/a.ts: https://x/T2"]

    def step(self, **kw):
        args = dict(rank="review:p1", waiting=[], merge="clean", deps=[], asks=[], requests=[], drift=[], notes=[])
        args.update(kw)
        return PT.next_step(pr(OLD), **args)

    def test_p2_threads_of_any_round_are_listed(self):
        data = pull([review(f"R{i}", f"2026-10-13T1{i}:00:00Z", OLD) for i in range(3)],
                    [thread("T2", "R2", "P2"), thread("T1", "R1", "P1")])
        waiting, p2, _ = PT.review_threads(data)
        self.assertEqual(len(p2), 1)
        self.assertEqual(len(waiting), 1)

    def test_open_p2_is_fixed_when_cheap(self):
        step = self.step(settle="fix", p2=self.P2)
        self.assertTrue(step.startswith("fix every cheap Codex finding above in one push, P2s included"), step)
        self.assertIn("decline only one whose fix needs a design change", step)

    def test_third_round_in_one_file_asks_for_another_approach_first(self):
        step = self.step(settle="fix", p2=self.P2, repeats=[("src/a.ts", 3)])
        self.assertTrue(step.startswith("Codex keeps finding problems in src/a.ts (3 rounds)"), step)
        self.assertIn("platform, browser or OS API", step)

    def test_budget_fixes_only_p0_p1(self):
        step = self.step(settle="budget", p2=self.P2)
        self.assertTrue(step.startswith("Codex round budget spent: reply to each P2 `Not fixed yet"), step)
        self.assertNotIn("Left for review", step)
        step = self.step(settle="budget", p2=self.P2, waiting=["chatgpt-codex-connector on src/a.ts: https://x/T1"])
        self.assertIn("fix the P0/P1 findings above in one push", step)

    def test_budget_still_fixes_a_cheap_p2_on_lines_our_latest_push_wrote(self):
        step = self.step(settle="budget", p2=self.P2, regressions=["https://x/T2"])
        self.assertIn("1 P2(s) sit on lines our latest push wrote (https://x/T2): fix each cheap one in one push", step)
        self.assertIn("reply to each other P2 `Not fixed yet", step)
        self.assertNotIn("no push for it", step)

    def test_handed_off_deferred_findings_are_ours_to_fix(self):
        step = self.step(settle="settled", handoff=[("deferred", "https://x/T1#r")])
        self.assertTrue(step.startswith("handed off, so every Codex finding is ours"), step)
        self.assertIn("edit its reply to `Fixed in", step)
        self.assertFalse(step.startswith(PT.PASSIVE_STEPS))

    def test_handed_off_open_findings_take_the_deferred_ones_along(self):
        step = self.step(settle="fix", p2=self.P2, handoff=[("deferred", "https://x/T1#r")])
        self.assertTrue(step.startswith("fix every cheap Codex finding above and the deferred ones under hand-off"),
                        step)

    def test_settled_without_threads_has_no_codex_step(self):
        self.assertTrue(self.step(settle="settled").startswith("nothing to do"))
        self.assertTrue(self.step(settle="clean").startswith("nothing to do"))

    def test_maintainer_pushing_leaves_codex_to_him(self):
        step = self.step(settle="maintainer", p2=self.P2)
        self.assertTrue(step.startswith("waiting on the maintainer"), step)
        self.assertTrue(step.startswith(PT.PASSIVE_STEPS))

    DRIFT = ["packages/ai/CHANGELOG.md: entry lands under ## [1.0.0]"]

    def test_changelog_drift_gets_its_own_push_once_the_bot_rounds_settle(self):
        # the maintainer made 27 CHANGELOG commits on 20 of our 78 merges 10-18..20.
        for settle in ("settled", "clean", None):
            step = self.step(settle=settle, drift=self.DRIFT)
            self.assertTrue(step.startswith("push the CHANGELOG fix now: `pr-queue advance '#1'`"), step)
            self.assertFalse(step.startswith(PT.PASSIVE_STEPS), "it needs us")
        step = self.step(rank="review:p2", settle="settled", drift=self.DRIFT)
        self.assertTrue(step.startswith("push the CHANGELOG fix now"), "a P2 waiting on a decision too")

    def test_changelog_drift_waits_while_a_bot_round_is_open(self):
        self.assertTrue(self.step(codex="running", drift=self.DRIFT).startswith("wait for Codex's pass"))
        self.assertTrue(self.step(settle="fix", p2=self.P2, drift=self.DRIFT).startswith("fix every cheap Codex"))
        self.assertTrue(self.step(rank="", drift=self.DRIFT).startswith("no roboomp rank"))
        self.assertTrue(self.step(settle="maintainer", drift=self.DRIFT).startswith("waiting on the maintainer"),
                        "a head the maintainer pushed is his")

    def test_a_maintainer_head_is_his_before_any_codex_pass(self):
        self.assertEqual(PT.codex_settle(pr(NEW, author="H4vC"), pull()), "maintainer")
        self.assertIsNone(PT.codex_settle(pr(NEW), pull()))


class HandoffTest(unittest.TestCase):
    """At hand-off nothing of ours defers a finding or leaves work to the maintainer."""

    def data(self):
        return pull([review("R1", "2026-10-13T10:00:00Z", OLD)], [
            thread("T1", "R1", "P2", last="octo-fork", resolved=True,
                   reply="Left for review: clear the timer on close; Codex round budget spent."),
            thread("T2", "R1", "P2", last="octo-fork", resolved=True,
                   reply="Not fixed yet: guard the empty list; Codex round budget spent."),
            thread("T3", "R1", "P2", last="octo-fork", resolved=True, reply="Fixed in abc1234: guarded it."),
            thread("T4", "R1", "P2", last="H4vC", resolved=True, reply="Left for review, thanks.")])

    def test_deferred_replies_and_hand_off_wording_are_listed(self):
        top = [{"author": {"login": "octo-fork"}, "url": "https://x/c1", "body": "The P2 is left for you."},
               {"author": {"login": "octo-fork"}, "url": "https://x/c2", "body": "Fixed in abc1234."},
               {"author": {"login": "H4vC"}, "url": "https://x/c3", "body": "for the maintainer"}]
        self.assertEqual(PT.handoff_items(pr(OLD, top), self.data()),
                         [("deferred", "https://x/T1#r"), ("deferred", "https://x/T2#r"), ("wording", "https://x/c1")])

    def test_hand_off_comes_from_a_queue_note_or_the_maintainer(self):
        quiet = pr(OLD)
        self.assertTrue(PT.handoff_reason(quiet, note="Sent to the maintainer 2026-10-15 (with #15574, #15762)."))
        self.assertTrue(PT.handoff_reason(quiet, note="the maintainer review 2026-10-16 answered: reply posted; waiting on the maintainer."))
        self.assertTrue(PT.handoff_reason(pr(OLD, [{"author": {"login": "H4vC"}, "body": "Rebase note"}])))
        self.assertEqual(PT.handoff_reason(quiet, note="HOLD: stays a draft"), "")
        self.assertEqual(PT.handoff_reason(quiet), "")

    def summary(self, data=None, **kw):
        head = pr(OLD)
        head.update(title="t", url="https://x/pr", state="OPEN", labels=[{"name": "review:p1"}], headRefName="octo-fork/x",
                    createdAt="2026-10-13T09:00:00Z", reviews=[], body="")
        with mock.patch.object(PT, "gh_json", return_value=head), \
                mock.patch.object(PT, "review_data", return_value=data or self.data()), \
                mock.patch.object(PT, "conflict", return_value=("clean", [])), \
                mock.patch.object(PT, "shipped_regressions", return_value=[]), \
                mock.patch.object(PT, "review_state", return_value=("approve", "approve")):
            return PT.summary_row(1, {}, {}, **kw)

    @staticmethod
    def made(data):
        """`data` after the final push: our `Not fixed yet` on T3 edited in place to `Fixed in`."""
        data["reviewThreads"]["nodes"][2]["all"]["nodes"][-1]["lastEditedAt"] = "2026-10-13T12:00:00Z"
        return data

    def test_settled_deferred_replies_need_one_final_push_then_wait_for_hand_off(self):
        """The maintainer merges within hours without a hand-off (#17492, e6eba3dc43)."""
        due = self.summary()
        self.assertTrue(due["needs_us"], due)
        self.assertIn("final push x2", due["flags"])
        self.assertEqual(due["next"], "Codex rounds settled")
        self.assertIn("edit each `Not fixed yet` reply in place to `Fixed in <sha>", due["next_full"])
        line = PT.summary_line(due)
        self.assertIn("final-push deferred Codex finding: fix it in the final push", line)
        self.assertIn("https://x/T1#r", line)
        after = self.summary(self.made(self.data()))
        self.assertFalse(after["needs_us"], after)
        self.assertEqual(after["handoff"], [])
        self.assertIn("final push made abc1234", after["flags"])
        self.assertEqual(after["codex"], "budget", "past-budget rules after the final push")
        handed = self.summary(self.made(self.data()), note="Sent to the maintainer 2026-10-15.")
        self.assertTrue(handed["needs_us"])
        self.assertIn("hand-off x2", handed["flags"])
        self.assertTrue(handed["next"].startswith("handed off"), handed["next"])

    def test_no_final_push_while_held_drafted_or_a_pass_is_due(self):
        held = PT.queue_holds({"entries": [
            {"pr": 15128, "state": "open", "hold": "redesign first"},
            {"pr": 15130, "state": "queued", "hold": "waiting on #15128"},
            {"pr": 15131, "state": "open", "note": "Sent to the maintainer; hold the release note"}]})
        self.assertEqual(sorted(held), [15128, 15130])
        row = self.summary(held=held[15128])
        self.assertFalse(row["needs_us"], row)
        self.assertIn("held", row["flags"])
        self.assertNotIn("final push x2", row["flags"])
        args = dict(settle="settled", codex=None, waiting=[], p2=[])
        self.assertEqual(len(PT.final_push_due(pr(OLD), self.data(), **args)), 2)
        self.assertEqual(PT.final_push_due(pr(OLD), self.data(), **{**args, "codex": "due"}), [])
        self.assertEqual(PT.final_push_due({**pr(OLD), "isDraft": True}, self.data(), **args), [])
        self.assertEqual(PT.final_push_due(pr(OLD), self.data(), **{**args, "settle": "fix"}), [])
        self.assertEqual(PT.final_push_due(pr(OLD), self.data(), **{**args, "p2": ["x"]}), [])
        self.assertEqual(len(PT.final_push_due(pr(OLD), self.data(), **{**args, "settle": "budget"})), 2)

    def test_a_named_pr_after_the_final_push_lists_pre_hand_off_items_without_needing_us(self):
        named = self.summary(self.made(self.data()), named=True)
        self.assertFalse(named["handed"])
        self.assertFalse(named["needs_us"], named)
        self.assertIn("pre-hand-off x2", named["flags"])
        self.assertNotIn("hand-off x2", named["flags"])
        self.assertIn("pre-hand-off deferred Codex finding", PT.summary_line(named))
        self.assertIn("https://x/T1#r", PT.summary_line(named))

    def test_the_final_push_is_an_edited_fixed_in_reply_of_ours(self):
        self.assertIsNone(PT.final_push(pr(OLD), self.data()), "a fresh `Fixed in` reply is a normal fix")
        refreshed = self.made(self.data())
        refreshed["reviewThreads"]["nodes"][2]["all"]["nodes"][-1]["body"] = "Fixed in abc1234 (first pushed as 9f9f9f9)."
        self.assertIsNone(PT.final_push(pr(OLD), refreshed), "re-pointing a reply at a rebased sha is no final push")
        sha, at = PT.final_push(pr(OLD), self.made(self.data()))
        self.assertEqual((sha, at), ("abc1234", PT.stamp("2026-10-13T12:00:00Z")))
        head = pr("abc1234" + "0" * 33, pushed="2026-10-13T11:40:00Z")
        self.assertEqual(PT.final_push(head, self.made(self.data()))[1], PT.stamp("2026-10-13T11:40:00Z"),
                         "the pushed commit's time when the PR has it")

    def test_naming_a_pr_keeps_the_round_budget(self):
        data = rounds(PT.CODEX_ROUND_BUDGET)
        named = self.summary(data, named=True)
        self.assertEqual(named["codex"], "budget")
        self.assertTrue(named["next"].startswith("Codex round budget spent"), named["next"])
        self.assertEqual(self.summary(data, note="waiting on the maintainer")["codex"], "fix")


class CodexOwnRegressionTest(unittest.TestCase):
    """Past the budget, a P2 on a line our latest push wrote still gets one push (#15418, 2026-10-14)."""

    def setUp(self):
        self.root, git = git_repo()
        os.makedirs(os.path.join(self.root, "src"))
        for text, when in (("old\nold\n", "2026-10-13T09:00:00Z"), ("old\nnew\n", "2026-10-13T15:30:00Z")):
            with open(os.path.join(self.root, "src/a.ts"), "w") as f:
                f.write(text)
            git("add", "-A")
            git("commit", "-q", "--no-gpg-sign", "--date", when, "-m", when)
        self.head = git("rev-parse", "HEAD")

    def found(self, n, line, final_at=None):
        data = rounds(n, sha=self.head)  # reviews at 10:00, 11:00, ...: the one before the last at 13:00 for n=5
        data["reviewThreads"]["nodes"][-1]["latest"]["nodes"][0]["line"] = line
        return PT.codex_own_regressions(pr(self.head), data, cwd=self.root,
                                        final_at=final_at and PT.stamp(final_at))

    def test_a_line_written_after_the_previous_review_is_ours(self):
        self.assertEqual(self.found(PT.CODEX_ROUND_BUDGET, 2), [f"https://x/T{PT.CODEX_ROUND_BUDGET - 1}"])

    def test_an_older_line_is_not(self):
        self.assertEqual(self.found(PT.CODEX_ROUND_BUDGET, 1), [])

    def test_only_once_the_pass_after_that_push_ends_it(self):
        self.assertEqual(self.found(PT.CODEX_ROUND_BUDGET + 1, 2), [])

    def test_after_the_final_push_the_one_pass_on_it_gets_one_more_push(self):
        """Reviews at 10:00 and 11:00, the final push between them at 10:30; line 2 was written at 15:30."""
        self.assertEqual(self.found(2, 2, "2026-10-13T10:30:00Z"), ["https://x/T1"])
        self.assertEqual(self.found(2, 1, "2026-10-13T10:30:00Z"), [])
        self.assertEqual(self.found(3, 2, "2026-10-13T10:30:00Z"), [], "a second pass after it ends it")


def git_repo():
    """A scratch repo with a test identity; removed at exit."""
    root = tempfile.mkdtemp(prefix="pr-trace-test-")
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "w@example.test",
           "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "w@example.test"}

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, text=True,
                              check=True).stdout.strip()

    git("init", "-q", "-b", "main")
    return root, git


def commit(root, git, path, text, msg):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)
    git("add", "-A")
    git("commit", "-q", "--no-gpg-sign", "-m", msg)
    return git("rev-parse", "HEAD")


class VsMainTest(unittest.TestCase):
    """pr-trace judges a conflict with main as pr-queue does (omp_pr.classify): #15443 and #15445
    conflicted only in the generated catalog files on 2026-10-14 and must not read as conflicts."""

    def setUp(self):
        self.root, git = git_repo()
        for path in ("packages/catalog/src/models.json", "packages/catalog/src/compat/rules.json", "src/a.ts"):
            commit(self.root, git, path, "base\n", f"add {path}")
        git("checkout", "-q", "-b", "octo-fork/x")
        for path in ("packages/catalog/src/models.json", "packages/catalog/src/compat/rules.json"):
            commit(self.root, git, path, "ours\n", "ours")
        git("checkout", "-q", "main")
        for path in ("packages/catalog/src/models.json", "packages/catalog/src/compat/rules.json"):
            commit(self.root, git, path, "theirs\n", "theirs")
        git("update-ref", "refs/remotes/origin/main", "main")
        git("update-ref", "refs/remotes/fork/octo-fork/x", "octo-fork/x")
        self.git = git
        self.saved = PT.has_ref, PT.merge_conflicts, PT.changelog_drift, PT.github_changelog_conflicts
        PT.has_ref = lambda ref: omp_pr.has_ref(ref, cwd=self.root)
        PT.merge_conflicts = lambda a, b: omp_pr.merge_conflicts(a, b, cwd=self.root)
        PT.changelog_drift = lambda ref: []
        PT.github_changelog_conflicts = lambda a, b: omp_pr.github_changelog_conflicts(a, b, cwd=self.root)

    def tearDown(self):
        PT.has_ref, PT.merge_conflicts, PT.changelog_drift, PT.github_changelog_conflicts = self.saved

    def test_generated_only_conflict_is_clean(self):
        merge, _ = PT.conflict("octo-fork/x")
        self.assertTrue(merge.startswith("clean"), merge)
        self.assertIn("packages/catalog/src/models.json", merge)
        step = PT.next_step(pr(OLD), rank="review:p0", waiting=[], merge=merge, deps=[], asks=[], requests=[],
                            drift=[], notes=[])
        self.assertFalse(step.startswith("rebase onto origin/main"), step)

    def test_a_code_conflict_alongside_still_counts(self):
        self.git("checkout", "-q", "octo-fork/x")
        commit(self.root, self.git, "src/a.ts", "ours\n", "ours code")
        self.git("checkout", "-q", "main")
        commit(self.root, self.git, "src/a.ts", "theirs\n", "theirs code")
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("update-ref", "refs/remotes/fork/octo-fork/x", "octo-fork/x")
        self.assertEqual(PT.conflict("octo-fork/x")[0], "REAL: src/a.ts")


class ChangelogDriftTest(unittest.TestCase):
    """A `###` heading the union merge repeats inside Unreleased is left to `fix-changelogs` at release
    (2026-10-29: nine PRs read as drift after main's own `### Added`, and a push for it only restarts
    Codex); an entry a release cut leaves under the released heading is still drift."""
    LOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n\n- Old\n"

    def setUp(self):
        self.root, self.git = git_repo()
        commit(self.root, self.git, ".gitattributes", "packages/*/CHANGELOG.md merge=union\n", "attrs")
        commit(self.root, self.git, "packages/a/CHANGELOG.md", self.LOG, "log")
        self.git("checkout", "-q", "-b", "octo-fork/x")
        self.write(self.LOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- Ours\n", 1), "ours")
        self.git("checkout", "-q", "main")

    def write(self, text, msg):
        commit(self.root, self.git, "packages/a/CHANGELOG.md", text, msg)

    def drift(self):
        return omp_pr.changelog_drift("octo-fork/x", base="main", cwd=self.root)

    def test_a_heading_main_also_adds_is_not_drift(self):
        self.write(self.LOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- Theirs\n", 1), "theirs")
        self.assertEqual(self.drift(), [])

    def test_an_entry_left_under_a_release_cut_is_drift(self):
        self.write(self.LOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n## [1.1.0]\n", 1), "release")
        self.assertEqual([(p, s) for p, _, s in self.drift()], [("packages/a/CHANGELOG.md", "## [1.1.0]")])


class GitHubViewTest(unittest.TestCase):
    """GitHub's mergeability ignores the CHANGELOG `merge=union`: with main at af7b2c50aa (2026-10-18)
    #16119, #15105 and #15184 read CONFLICTING there in packages/coding-agent/CHANGELOG.md alone, while
    merge-tree found them clean. `vs main` names that state apart from a code conflict, as information."""
    LOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n\n- Old\n"

    def setUp(self):
        self.root, self.git = git_repo()
        commit(self.root, self.git, ".gitattributes", "packages/*/CHANGELOG.md merge=union\n", "attrs")
        commit(self.root, self.git, "packages/a/CHANGELOG.md", self.LOG, "log")
        commit(self.root, self.git, "packages/a/src/a.ts", "one\ntwo\nthree\n", "code")
        self.git("checkout", "-q", "-b", "octo-fork/x")
        commit(self.root, self.git, "packages/a/src/a.ts", "ONE\ntwo\nthree\n", "ours")
        self.add_entry("Fixed ours")
        self.git("checkout", "-q", "main")
        self.saved = PT.has_ref, PT.merge_conflicts, PT.changelog_drift, PT.github_changelog_conflicts
        PT.has_ref = lambda ref: omp_pr.has_ref(ref, cwd=self.root)
        PT.merge_conflicts = lambda a, b: omp_pr.merge_conflicts(a, b, cwd=self.root)
        PT.changelog_drift = lambda ref: []
        PT.github_changelog_conflicts = lambda a, b: omp_pr.github_changelog_conflicts(a, b, cwd=self.root)

    def tearDown(self):
        PT.has_ref, PT.merge_conflicts, PT.changelog_drift, PT.github_changelog_conflicts = self.saved

    def add_entry(self, text):
        path = os.path.join(self.root, "packages/a/CHANGELOG.md")
        with open(path) as f:
            log = f.read()
        commit(self.root, self.git, "packages/a/CHANGELOG.md",
               log.replace("## [Unreleased]\n", f"## [Unreleased]\n\n- {text}\n", 1), f"log {text}")

    def vs_main(self):
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("update-ref", "refs/remotes/fork/octo-fork/x", "octo-fork/x")
        return PT.conflict("octo-fork/x")[0]

    def step(self, merge):
        return PT.next_step(pr(OLD), rank="review:p1", waiting=[], merge=merge, deps=[], asks=[], requests=[],
                            drift=[], notes=[])

    def test_mergeable_on_github_too(self):
        commit(self.root, self.git, "packages/a/src/a.ts", "one\ntwo\nTHREE\n", "main code elsewhere")
        merge = self.vs_main()
        self.assertEqual(merge, "clean; GitHub: mergeable")
        self.assertTrue(self.step(merge).startswith("nothing to do"))

    def test_changelog_only_on_github_is_its_own_passive_state(self):
        self.add_entry("Fixed theirs")  # main gains an [Unreleased] line where ours went
        merge = self.vs_main()
        self.assertEqual(merge, "clean; GitHub: conflicting (CHANGELOG only: packages/a/CHANGELOG.md), "
                                "so the next needed push rebases onto main")
        step = self.step(merge)
        self.assertTrue(step.startswith("GitHub's CHANGELOG-only conflict rides with the next push, which rebases "
                                        "onto origin/main"), step)
        self.assertTrue(step.startswith(PT.PASSIVE_STEPS), "no push of its own: it does not need us")
        self.assertFalse(step.startswith("rebase onto origin/main"))

    def test_a_code_conflict_stays_real(self):
        self.add_entry("Fixed theirs")
        commit(self.root, self.git, "packages/a/src/a.ts", "uno\ntwo\nthree\n", "main code on our line")
        self.assertEqual(self.vs_main(), "REAL: packages/a/src/a.ts")

    def test_summary_flags_it_without_needing_us(self):
        self.add_entry("Fixed theirs")
        merge = self.vs_main()
        head = pr(OLD)
        head.update(title="t", url="https://x/pr", state="OPEN", labels=[{"name": "review:p1"}], headRefName="octo-fork/x",
                    createdAt="2026-10-13T09:00:00Z", reviews=[], body="")
        with mock.patch.object(PT, "gh_json", return_value=head), \
                mock.patch.object(PT, "review_data", return_value=pull(thumbs=["2026-10-13T09:00:00Z"])), \
                mock.patch.object(PT, "conflict", return_value=(merge, [])), \
                mock.patch.object(PT, "shipped_regressions", return_value=[]), \
                mock.patch.object(PT, "review_state", return_value=("approve", "approve")):
            row = PT.summary_row(1, {}, {})
        self.assertIn("GitHub: CHANGELOG-only conflict (next push rebases)", row["flags"])
        self.assertFalse(row["needs_us"], row)

    def pair_row(self, merge, prs, manifest):
        head = pr(OLD)
        head.update(title="t", url="https://x/pr", state="OPEN", labels=[{"name": "review:p2"}], headRefName="octo-fork/x",
                    createdAt="2026-10-13T09:00:00Z", reviews=[], body="")
        with mock.patch.object(PT, "gh_json", return_value=head), \
                mock.patch.object(PT, "review_data", return_value=pull(thumbs=["2026-10-13T09:00:00Z"])), \
                mock.patch.object(PT, "conflict", return_value=(merge, [])), \
                mock.patch.object(PT, "shipped_regressions", return_value=[]), \
                mock.patch.object(PT, "review_state", return_value=("approve", "approve")):
            return PT.summary_row(1, prs, {}, pairs=PT.queue_pairs(manifest).get(1, ()))

    def test_a_pair_opened_over_a_p2_shows_and_its_survivor_rebases_now(self):
        # Open-PR rule 3: P1 #2 opened over P2 #1, so #1's entry says it rebases
        # after #2 merges. While both are open the summary names the pair; once #2 merged, #1 conflicts
        # with main and is ours to rebase at once.
        manifest = {"entries": [{"id": "p2", "pr": 1, "state": "open", "rebases_after": [2]},
                                {"id": "p1", "pr": 2, "state": "open"}]}
        self.assertEqual(PT.queue_pairs(manifest), {1: [(2, "after", "open")], 2: [(1, "over", "open")]})
        both = self.pair_row("clean; GitHub: mergeable", {1: {}, 2: {}}, manifest)
        self.assertIn("rebases after #2 merges", both["flags"])
        self.assertFalse(both["needs_us"], both)
        manifest["entries"][1]["state"] = "merged"
        after = self.pair_row("REAL: packages/a/src/a.ts", {1: {}}, manifest)
        self.assertEqual(after["next"], "rebase onto main now")
        self.assertIn("#2 (merged)", after["next_full"])
        self.assertIn("pr-queue advance '#1'", after["next_full"])
        self.assertTrue(after["needs_us"], after)
        self.assertNotIn("rebases after #2 merges", after["flags"])
        # A requeued P2 (entry back to queued, no PR) names no pair.
        self.assertEqual(PT.queue_pairs({"entries": [{"id": "p2", "pr": None, "state": "queued",
                                                      "rebases_after": [2]}]}), {})


class FirstReleaseTest(unittest.TestCase):
    def test_earliest_version_tag_else_unreleased(self):
        root, git = git_repo()
        merged = commit(root, git, "a", "1\n", "merge of our PR")
        commit(root, git, "a", "2\n", "later")
        git("tag", "v1.10.0")
        git("tag", "v1.9.0")  # sorts before v1.10.0 as a version, after it as text
        git("tag", "nightly")
        late = commit(root, git, "a", "3\n", "merged after the last release")
        self.assertEqual(PT.first_release(merged, cwd=root), "v1.9.0")
        self.assertEqual(PT.first_release(late, cwd=root), "unreleased")
        self.assertIsNone(PT.first_release("0" * 40, cwd=root))

    def test_merged_line_names_the_release(self):
        row = {"number": 15443, "merged_at": "2026-10-14T09:20:37Z", "merged_by": "can1357", "title": "fix: x",
               "maintainer_commits": [], "release": "v18.10.4"}
        self.assertIn(" in v18.10.4 ", PT.merge_line(row))
        self.assertIn(" unreleased ", PT.merge_line({**row, "release": "unreleased"}))


class ShippedRegressionTest(unittest.TestCase):
    """#16038 fixed a line 8fbaf75aa2 wrote; precheck let its CHANGELOG entry go while that commit was
    unreleased, v18.11.3 shipped it while the PR was open, and the maintainer added the entry (e2b974e459)."""

    LOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n\n- old\n"

    def setUp(self):
        self.root, self.git = git_repo()
        commit(self.root, self.git, "packages/c/CHANGELOG.md", self.LOG, "init")
        commit(self.root, self.git, "packages/c/src/a.ts", "start = ok;\n", "feat(c): start")
        self.git("tag", "v1.0.0")
        self.regress = commit(self.root, self.git, "packages/c/src/a.ts", "start = broken;\n", "fix(c): regress")
        self.git("checkout", "-q", "-b", "octo-fork/x")
        commit(self.root, self.git, "packages/c/src/a.ts", "start = ok;\n", "fix(c): start again")
        self.git("checkout", "-q", "main")
        self.refs()

    def refs(self):
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("update-ref", "refs/remotes/fork/octo-fork/x", "octo-fork/x")

    def shipped(self, opened="2000-01-01T00:00:00Z"):
        return PT.shipped_regressions({"headRefName": "octo-fork/x", "createdAt": opened,
                                       "commits": [{"messageHeadline": "fix(c): start again"}]}, cwd=self.root)

    def test_a_release_cut_while_open_ships_the_regression(self):
        self.assertEqual(self.shipped(), [])
        commit(self.root, self.git, "packages/c/src/b.ts", "x;\n", "chore: bump version to 1.0.1")
        self.git("tag", "v1.0.1")
        self.refs()
        found = self.shipped()
        self.assertEqual([(pkg, tag) for pkg, tag, _ in found], [("packages/c", "v1.0.1")], found)
        self.assertTrue(found[0][2].startswith(self.regress[:10]), found)
        step = PT.next_step(pr(OLD), rank="review:p1", waiting=[], merge="clean", deps=[], asks=[], requests=[],
                            drift=[], notes=[], shipped=found)
        self.assertTrue(step.startswith("add the CHANGELOG entry (the regression shipped in v1.0.1)"), step)
        self.assertFalse(step.startswith(PT.PASSIVE_STEPS))

    def test_released_before_opening_or_with_an_entry_is_not_flagged(self):
        commit(self.root, self.git, "packages/c/src/b.ts", "x;\n", "chore: bump version to 1.0.1")
        self.git("tag", "v1.0.1")
        self.refs()
        self.assertEqual(self.shipped(opened="2100-01-01T00:00:00Z"), [])
        self.git("checkout", "-q", "octo-fork/x")
        commit(self.root, self.git, "packages/c/CHANGELOG.md",
               self.LOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- Fixed start\n"), "docs(c): entry")
        self.git("checkout", "-q", "main")
        self.refs()
        self.assertEqual(self.shipped(), [])


MERGED_AT = "2026-10-18T11:52:03Z"


def inline(at, p, path, line, sha=NEW, login=CODEX, start=None, resolved=False):
    body = (f"**<sub><sub>![{p} Badge](https://img.shields.io/badge/{p}-orange?style=flat)</sub></sub>  Finding**\n\n"
            "Useful? React with 👍 / 👎.\n\n<!-- codex-code-review-finding:v1 -->")
    return {"isResolved": resolved,
            "comments": {"nodes": [{"url": f"https://x/r{line}", "createdAt": at, "body": body, "author": {"login": login},
                                    "path": path, "originalLine": line, "originalStartLine": start,
                                    "originalCommit": {"oid": sha}}]}}


def body_review(at, findings, login=CODEX):
    """A Codex review whose body carries the findings, no thread (#16119's, 2026-10-18 16:54)."""
    parts = [f"https://github.com/can1357/oh-my-pi/blob/{NEW}/{path}#L{line}\n"
             f"**<sub><sub>![{p} Badge](https://img.shields.io/badge/{p}-orange?style=flat)</sub></sub>  Finding**\n\nWhy."
             for p, path, line in findings]
    return {"url": "https://x/review", "submittedAt": at, "author": {"login": login},
            "body": "<!-- codex-code-review-finding:v1 -->\n\n\n### 💡 Codex Review\n\n" + "\n\n---\n\n".join(parts)}


def merged_node(threads=(), reviews=()):
    return {"reviewThreads": {"nodes": list(threads)}, "reviews": {"nodes": list(reviews)}}


class PostMergeFindingsTest(unittest.TestCase):
    """Codex posted 12 findings (6 P1) on #15562, #15193, #15195 and #16140 after the maintainer merged them on
    2026-10-18, and three on #16119; nothing of ours looked, and the maintainer fixed them himself in 13d09929b7
    and 1a97f79d28. `--summary` lists the ones no later main commit touched as ours to fix."""

    def test_findings_after_the_merge_from_threads_and_review_bodies(self):
        node = merged_node(
            threads=[inline("2026-10-18T11:40:00Z", "P1", "a.rs", 10),  # before the merge: handled while open
                     inline("2026-10-18T11:52:19Z", "P1", "a.rs", 654),
                     inline("2026-10-18T11:52:19Z", "P2", "b.rs", 438, start=436),
                     inline("2026-10-18T12:00:00Z", "P1", "a.rs", 20, login="H4vC"),
                     inline("2026-10-18T12:10:00Z", "P2", "c.rs", 30, resolved=True)],  # disproved and resolved
            reviews=[body_review("2026-10-18T16:54:34Z", [("P1", "src/t.ts", 1360), ("P2", "src/b.ts", 330)]),
                     body_review("2026-10-18T11:00:00Z", [("P1", "src/old.ts", 1)])])
        found = omp_pr.post_merge_findings(node, MERGED_AT)
        self.assertEqual([(f["severity"], f["path"], f["start"], f["end"]) for f in found],
                         [("P1", "a.rs", 654, 654), ("P2", "b.rs", 436, 438), ("P1", "src/t.ts", 1360, 1360),
                          ("P2", "src/b.ts", 330, 330)])
        self.assertEqual({f["commit"] for f in found}, {NEW})

    def test_a_main_commit_on_the_lines_or_naming_the_pr_takes_it_up(self):
        root, git = git_repo()
        commit(root, git, "src/a.rs", "".join(f"line {i}\n" for i in range(1, 41)), "base")
        head = commit(root, git, "src/a.rs", "".join(f"line {i}\n" for i in range(1, 41)).replace("line 5\n", "ours\n"),
                      "ours")
        merge = head
        far = {"commit": head, "path": "src/a.rs", "start": 30, "end": 30}
        near = {**far, "start": 10, "end": 10}
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertIsNone(omp_pr.taken_up(near, 15195, merge, "2000-01-01T00:00:00Z", cwd=root))
        with open(os.path.join(root, "src/a.rs")) as f:
            text = f.read()
        fix = commit(root, git, "src/a.rs", text.replace("line 12\n", "fixed\n"), "fix(natives): the maintainer's fixup")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(omp_pr.taken_up(near, 15195, merge, "2000-01-01T00:00:00Z", cwd=root), fix[:10],
                         "a rewrite within POST_MERGE_SPAN lines of the finding")
        self.assertIsNone(omp_pr.taken_up(far, 15195, merge, "2000-01-01T00:00:00Z", cwd=root))
        named = commit(root, git, "src/b.rs", "x\n", "fix(natives): address post-merge review findings (#15195)")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertEqual(omp_pr.taken_up(far, 15195, merge, "2000-01-01T00:00:00Z", cwd=root), named[:10])
        self.assertIsNone(omp_pr.taken_up(far, 1519, merge, "2000-01-01T00:00:00Z", cwd=root), "#15195 is not #1519")

    def test_summary_lists_open_ones_under_the_merge_and_in_needs_us(self):
        merges = [{"number": 15195, "title": "fix(natives): keep the user's app in front", "url": "https://x/15195",
                   "merged_at": MERGED_AT, "merged_by": "H4vC", "maintainer_commits": [], "merge_commit": "c" * 40},
                  {"number": 15193, "title": "fix(natives): type into Screen Sharing", "url": "https://x/15193",
                   "merged_at": MERGED_AT, "merged_by": "H4vC", "maintainer_commits": [], "merge_commit": "d" * 40}]
        graph = {"data": {"repository": {
            "pr15195": merged_node(threads=[inline("2026-10-18T11:52:19Z", "P1", "a.rs", 654),
                                            inline("2026-10-18T11:52:19Z", "P1", "a.rs", 1031),
                                            inline("2026-10-18T11:52:19Z", "P2", "a.rs", 1045)]),
            "pr15193": merged_node(threads=[inline("2026-10-18T12:30:53Z", "P1", "input.rs", 294)])}}}
        out = io.StringIO()
        with mock.patch.object(PT, "merged_prs", return_value=merges), \
                mock.patch.object(PT, "first_release", return_value="unreleased"), \
                mock.patch.object(PT, "run"), \
                mock.patch.object(omp_pr, "gh_json", side_effect=lambda *a: graph if a[0] == "api" else []), \
                mock.patch.object(omp_pr, "taken_up", side_effect=lambda f, n, *a, **k: "13d09929b7" if n == 15193 else None), \
                mock.patch("sys.stdout", out):
            PT.summarize([], 2, {}, {}, {})
        text = out.getvalue()
        needs = text.split("Needs us (", 1)[1].split("Waiting on others", 1)[0]
        self.assertTrue(needs.startswith("1)"), needs)
        self.assertIn("#15195  merged", needs)
        self.assertIn("[post-merge: Codex P1 x2, Codex P2 x1 open] -> fix as a follow-up off main before the "
                      "maintainer has to", needs)
        self.assertNotIn("#15193", needs)
        merged = text.split("Merged in the last", 1)[1]
        self.assertIn("post-merge: Codex P1 x2, Codex P2 x1 open\n           a.rs:654 https://x/r654", merged)
        self.assertIn("post-merge: Codex P1 x1 taken up on main in 13d09929b7", merged)

    def test_a_follow_up_pr_open_or_merged_addresses_the_finding_and_a_closed_one_does_not(self):
        # 2026-10-22: #16288 and #16300 sat in Needs us while our #16564 ("Follow-up to #16288") and
        # #16552 ("Follow-up to #16300") were open; #16555 ("Follow-up to #16269") had closed unmerged.
        merges = [{"number": n, "title": f"fix: merge {n}", "url": f"https://x/{n}", "merged_at": MERGED_AT,
                   "merged_by": "H4vC", "maintainer_commits": [], "merge_commit": "c" * 40}
                  for n in (16269, 16288, 16300, 16310)]
        graph = {"data": {"repository": {
            "pr16269": merged_node(threads=[inline("2026-10-18T11:52:19Z", "P2", "a.ts", 11)]),
            "pr16288": merged_node(threads=[inline("2026-10-18T11:52:19Z", "P1", "b.ts", 22)]),
            "pr16300": merged_node(threads=[inline("2026-10-18T11:52:19Z", "P2", "c.ts", 33)]),
            "pr16310": merged_node(threads=[inline("2026-10-18T11:52:19Z", "P1", "d.ts", 44),
                                            inline("2026-10-18T11:52:19Z", "P2", "d.ts", 45)])}}}
        ours = [{"number": 16555, "state": "CLOSED", "body": "Follow-up to #16269: closed for a better fix."},
                {"number": 16564, "state": "OPEN", "body": "Follow-up to #16288: the budget counts the copy sent."},
                {"number": 16552, "state": "MERGED", "body": "Follow-up to https://github.com/can1357/oh-my-pi/pull/16300: "
                                                             "kill the process group.\n\nRelated: #16288"},
                # Links one of #16310's two findings, and a URL that only starts like the other's.
                {"number": 16570, "state": "OPEN", "body": "Fixes https://x/r44 and see https://x/r450."}]
        asked = []

        def gh(*args):
            asked.append(args)
            return graph if args[0] == "api" else ours
        out = io.StringIO()
        with mock.patch.object(PT, "merged_prs", return_value=merges), \
                mock.patch.object(PT, "first_release", return_value="unreleased"), \
                mock.patch.object(PT, "run"), mock.patch.object(omp_pr, "gh_json", side_effect=gh), \
                mock.patch.object(omp_pr, "taken_up", return_value=None), mock.patch("sys.stdout", out):
            PT.summarize([], 2, {}, {}, {})
        self.assertIn(f"created:>={MERGED_AT[:10]}", asked[1], "our PRs since the oldest merge with an open finding")
        text = out.getvalue()
        needs = text.split("Needs us (", 1)[1].split("Waiting on others", 1)[0]
        self.assertTrue(needs.startswith("2)"), needs)
        self.assertIn("#16269  merged", needs, "a follow-up closed without merging addresses nothing")
        self.assertIn("#16310  merged  fix: merge 16310", needs)
        self.assertIn("[post-merge: Codex P2 x1 open]", needs.split("#16310", 1)[1])
        self.assertNotIn("#16288", needs)
        self.assertNotIn("#16300", needs)
        merged = text.split("Merged in the last", 1)[1]
        self.assertIn("post-merge: Codex P1 x1 addressed by #16564", merged.split("#16288", 1)[1].split("#16300")[0])
        self.assertIn("post-merge: Codex P2 x1 addressed by #16552", merged.split("#16300", 1)[1].split("#16310")[0])
        self.assertIn("post-merge: Codex P2 x1 open\n           d.ts:45 https://x/r45\n"
                      "         post-merge: Codex P1 x1 addressed by #16570", merged)

    def test_no_pr_list_when_every_finding_is_taken_up(self):
        merges = [{"number": 15193, "merged_at": MERGED_AT, "merge_commit": "d" * 40}]
        graph = {"data": {"repository": {"pr15193": merged_node(threads=[inline("2026-10-18T12:30:53Z", "P1", "a.rs", 9)])}}}
        with mock.patch.object(omp_pr, "gh_json", return_value=graph) as gh, \
                mock.patch.object(omp_pr, "taken_up", return_value="13d09929b7"):
            omp_pr.post_merge_review(merges)
        self.assertEqual(gh.call_count, 1)
        self.assertIsNone(merges[0]["post_merge"][0]["addressed_by"])

    def test_needs_us_keeps_the_watchers_open_findings_on_merges_past_the_window(self):
        # #16288 merged 3 days before this summary; its Codex P1 is still open in the watcher's record.
        record = {"checked": "2026-10-20T19:38:20Z", "host": "linux-box", "openable": {}, "conflicts": {}, "events": [],
                  "post_merge": {"16288": {"title": "fix(catalog,coding-agent): keep Factory Droid requests under",
                                           "merge_commit": "e" * 40, "merged_at": "2026-10-17T17:36:00Z",
                                           "findings": [{"bot": "chatgpt-codex-connector", "severity": "P1",
                                                         "path": "a.ts", "end": 9, "url": "https://x/r9"}]}}}
        out = io.StringIO()
        with mock.patch.object(PT, "merged_prs", return_value=[]), mock.patch("sys.stdout", out):
            PT.summarize([], 2, {}, {}, {"watch": record})
        text = out.getvalue()
        self.assertIn("Post-merge findings open (fix each as a follow-up off main, workflow step 10): "
                      "#16288 Codex P1 x1", text.split("\n\n", 1)[0])
        needs = text.split("Needs us (", 1)[1].split("Waiting on others", 1)[0]
        self.assertIn("#16288  merged  fix(catalog,coding-agent): keep Factory Droid requests under", needs)
        self.assertIn("[post-merge: Codex P1 x1 open] -> fix as a follow-up off main", needs)

    def test_the_summary_starts_with_the_opening_pause(self):
        # A pause relayed in one session's note; another session opened #101/#102 during it.
        pause = "user, 2026-01-02: pause for maintainer round"
        out = io.StringIO()
        with mock.patch.object(PT, "merged_prs", return_value=[]), mock.patch("sys.stdout", out):
            PT.summarize([], 2, {}, {}, {"config": {"pause": pause}})
        self.assertTrue(out.getvalue().startswith(f"OPENING PAUSED ({pause}): "), out.getvalue()[:200])


class RoboompNotesTest(unittest.TestCase):
    def test_an_lgtm_verdict_is_no_note_but_a_maintainer_question_is(self):
        # #16231 (2026-10-20): the whole body was the verdict plus roboomp's own verification note.
        body = ("lgtm — P0: scoped prompt guidance fixes the serial-tool contradiction without changing the "
                "parallel path; ready for maintainer merge. Thanks @octo-fork.\nVerified `init` activates the "
                "first task. Focused tests could not load because this checkout lacks `tool-views.generated.js`.\n")
        self.assertEqual(PT.note_sentences(body), [])
        for kept in ("lgtm — P1: ready for maintainer merge once the maintainer makes the call on the default.\n",
                     "Ready for maintainer merge after a live check of cancellation on Linux.\n"):
            self.assertEqual(len(PT.note_sentences(kept)), 1, kept)


if __name__ == "__main__":
    unittest.main()
