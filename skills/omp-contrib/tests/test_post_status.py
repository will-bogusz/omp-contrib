"""post-status against fixture posts, a local queue manifest and a fake GitHub.
Run: python3 -m unittest discover -s tests"""
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
from unittest import mock

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
loader = importlib.machinery.SourceFileLoader("post_status", os.path.join(SCRIPTS, "post-status"))
spec = importlib.util.spec_from_loader("post_status", loader)
PS = importlib.util.module_from_spec(spec)
loader.exec_module(PS)

BEFORE = "# My series\r\n\r\nIntro written by hand, with a | pipe and <!-- a comment -->.\r\n\r\n## Where it stands\r\n\r\n"
AFTER = "\r\n## Real tasks while I type\r\n\r\nMore hand-written text.\r\n"


def post(rows, prs=None, headline="**Merged 0 of 3** `□□□` · 3 waiting their turn · updated Oct 1", nl="\r\n"):
    """A post whose block lists `rows` [(status, "#N" or "", what)]; `prs` defaults to the rows' PRs."""
    numbers = prs if prs is not None else [int(c[1:]) for _, c, _ in rows if c]
    lines = [f"<!-- series-status prs={','.join(map(str, numbers))} -->", headline, "",
             "| status | PR | what it does |", "|---|---|---|"]
    lines += [f"| {s} | {c} | {w} |" for s, c, w in rows] + ["<!-- /series-status -->"]
    return BEFORE + nl.join(lines) + nl + AFTER


def pr(state="OPEN", draft=False, merged=None, body="", commit=None):
    return {"state": state, "isDraft": draft, "mergedAt": merged, "body": body,
            "mergeCommit": {"oid": commit} if commit else None}


class FakeGitHub:
    def __init__(self, body, prs):
        self.body, self.prs_data, self.updates, self.reads, self.on_read = body, prs, [], 0, None
        self.readback = None

    def discussion(self, number):
        self.reads += 1
        if self.on_read:
            self.on_read(self)
        return {"id": "D_x", "body": self.body}

    def prs(self, numbers, body):
        return {n: dict(self.prs_data[n]) for n in numbers if n in self.prs_data}

    def states(self, numbers):
        return {n: self.prs_data[n]["state"] for n in numbers if n in self.prs_data}

    def update(self, ident, body):
        self.updates.append((ident, body))
        self.body = self.readback(body) if self.readback else body


class PostStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="post-status-test-")
        self.manifest = os.path.join(self.tmp, "queue.json")
        self.entries([])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def entries(self, entries):
        with open(self.manifest, "w") as f:
            json.dump({"version": 1, "config": {}, "entries": [{"branch": f"octo-fork/{e['id']}", **e} for e in entries]}, f)

    def run_ps(self, gh, *args, today="Oct 18", releases=None):
        """`releases` {number: first tag} stands in for the checkout's tags; None reads the real checkout
        (`--repo`)."""
        out, err = io.StringIO(), io.StringIO()
        fake = mock.patch.object(PS, "releases_of", lambda prs, repo: dict(releases), create=True)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                (fake if releases is not None else contextlib.nullcontext()):
            code = PS.main(["16124", "--manifest", self.manifest, *args], github=gh, today=today)
        return code, out.getvalue(), err.getvalue()

    def block(self, body):
        return "".join(PS.split(body)[1]).replace("\r\n", "\n")

    # --- statuses -------------------------------------------------------------------------------

    def test_ready_pr_with_unmerged_needs_is_in_review_after_them(self):
        """A ready PR waits like a draft while its needs are open; once they merge it is plainly in review."""
        self.entries([{"id": "a", "pr": 2, "state": "open", "needs": ["#3"]},
                      {"id": "b", "pr": 4, "state": "open", "needs": ["#5"]}])
        gh = FakeGitHub(post([("x", "#2", "two"), ("x", "#4", "four")]), {
            2: pr(), 3: pr(draft=True), 4: pr(), 5: pr("MERGED", merged="2026-10-17T00:00:00Z")})
        self.run_ps(gh)
        new = self.block(gh.body)
        self.assertIn("| in review, after #3 | #2 | two |", new)
        self.assertIn("| in review | #4 | four |", new)

    def test_headline_counts_in_review_only_when_nothing_is_pending(self):
        """Ready PRs still waiting on needs count as waiting, not in review, in the headline."""
        self.entries([{"id": "a", "pr": 2, "state": "open", "needs": ["#3"]}])
        gh = FakeGitHub(post([("x", "#1", "one"), ("x", "#2", "two"), ("x", "#3", "three")]), {
            1: pr(), 2: pr(), 3: pr(draft=True)})
        self.run_ps(gh)
        self.assertIn("**Merged 0 of 3** `□□□` · 1 in review · 2 waiting their turn · updated Oct 18", self.block(gh.body))

    def test_each_status_kind(self):
        """merged with its UTC date, in review, after (recorded needs not merged yet, an entry id
        without a PR), the body's Builds-on line when no needs are recorded, up next, closed."""
        self.entries([
            {"id": "a", "pr": 2, "state": "open", "needs": ["#1", "#3", "b"]},
            {"id": "b", "pr": None, "state": "queued", "needs": []},
            {"id": "c", "pr": 6, "state": "open", "needs": ["#1"]},
        ])
        rows = [(s, f"#{n}", f"what {n}") for n, s in
                [(1, "x"), (2, "x"), (3, "x"), (4, "x"), (5, "x"), (6, "x")]]
        gh = FakeGitHub(post(rows), {
            1: pr("MERGED", merged="2026-10-17T23:49:51Z"), 2: pr(draft=True), 3: pr(),
            4: pr(draft=True, body="## What\r\n\r\nBuilds on #3 and #1.\r\n"), 5: pr("CLOSED"), 6: pr(draft=True)})
        code, out, _ = self.run_ps(gh)
        self.assertEqual(code, 0)
        new = self.block(gh.body)
        for line in ("| merged Oct 17 | #1 | what 1 |", "| in review | #3 | what 3 |", "| after #3, b | #2 | what 2 |",
                     "| after #3 | #4 | what 4 |", "| up next | #6 | what 6 |", "| closed | #5 | what 5 |"):
            self.assertIn(line, new)
        self.assertIn("**Merged 1 of 6** `■□□□□□` · 1 in review · 3 waiting their turn · 1 closed · updated Oct 18", new)

    def test_merge_date_is_utc(self):
        gh = FakeGitHub(post([("x", "#1", "w")]), {1: pr("MERGED", merged="2026-10-18T02:33:52Z")})
        self.run_ps(gh)
        self.assertIn("| merged Oct 18 | #1 | w |", self.block(gh.body))

    def test_queued_entry_row_until_it_opens(self):
        """A queue entry id in `prs=` with `<!-- id -->` as its PR cell: while it has no PR the row says
        `queued, after #N` (no link) and a PR waiting on it says `after the queued PR`; once `pr-queue open`
        records its number the cell becomes `#N` and the row a PR's status. The marker line stays as written."""
        self.entries([{"id": "quiet", "pr": None, "state": "queued", "needs": ["#7"]},
                      {"id": "report", "pr": 2, "state": "open", "needs": ["quiet"]}])
        rows = [("x", "<!-- quiet -->", "quiet wait"), ("x", "#3", "lines"), ("x", "#2", "report")]
        body = post(rows, prs=["quiet", 3, 2])
        gh = FakeGitHub(body, {2: pr(draft=True), 3: pr(draft=True), 7: pr()})
        code, _, err = self.run_ps(gh)
        self.assertEqual(code, 0, err)
        new = self.block(gh.body)
        for line in ("| queued, after #7 | <!-- quiet --> | quiet wait |", "| up next | #3 | lines |",
                     "| after the queued PR | #2 | report |"):
            self.assertIn(line, new)
        self.assertIn("**Merged 0 of 3** `□□□` · 3 waiting their turn · updated Oct 18", new)
        self.assertTrue(gh.body.startswith(PS.split(body)[0]))

        self.entries([{"id": "quiet", "pr": 9, "state": "open", "needs": ["#7"]},
                      {"id": "report", "pr": 2, "state": "open", "needs": ["quiet"]}])
        gh.prs_data[9] = pr()
        gh.prs_data[7] = pr("MERGED", merged="2026-10-19T00:00:00Z")
        code, _, err = self.run_ps(gh, today="Oct 20")
        self.assertEqual(code, 0, err)
        new = self.block(gh.body)
        for line in ("| in review | #9 | quiet wait |", "| after #9 | #2 | report |", "| up next | #3 | lines |"):
            self.assertIn(line, new)
        self.assertIn("<!-- series-status prs=quiet,3,2 -->", gh.body)

    def test_refuses_unknown_entry_id(self):
        gh = FakeGitHub(post([("x", "<!-- nope -->", "w")], prs=["nope"]), {})
        code, _, err = self.run_ps(gh)
        self.assertEqual(code, 1)
        self.assertIn("nope", err)
        self.assertEqual(gh.updates, [])

    def test_order_merged_by_time_then_review_waiting_closed(self):
        """Merged by merge time, then in review, waiting, closed, each keeping the written order; a row
        without a PR keeps its slot, and every row keeps its own `what` cell."""
        rows = [("x", "#10", "ten"), ("x", "#11", "eleven"), ("note", "", "hand row"), ("x", "#12", "twelve"),
                ("x", "#13", "thirteen"), ("x", "#14", "fourteen"), ("later", "", "last row")]
        gh = FakeGitHub(post(rows), {
            10: pr("CLOSED"), 11: pr(draft=True), 12: pr("MERGED", merged="2026-10-18T03:00:00Z"),
            13: pr(), 14: pr("MERGED", merged="2026-10-17T03:00:00Z")})
        self.run_ps(gh)
        table = [line for line in self.block(gh.body).splitlines() if line.startswith("| ")][1:]
        self.assertEqual(table, ["| merged Oct 17 | #14 | fourteen |", "| merged Oct 18 | #12 | twelve |",
                                 "| note |  | hand row |", "| in review | #13 | thirteen |",
                                 "| up next | #11 | eleven |", "| closed | #10 | ten |", "| later |  | last row |"])

    def test_all_merged_headline_drops_empty_counts(self):
        gh = FakeGitHub(post([("x", "#1", "w")]), {1: pr("MERGED", merged="2026-10-17T00:00:00Z")})
        self.run_ps(gh)
        self.assertIn("**Merged 1 of 1** `■` · updated Oct 18\r\n", gh.body)

    # --- releases -------------------------------------------------------------------------------

    def test_all_merged_in_one_release_names_it(self):
        gh = FakeGitHub(post([("x", "#1", "one"), ("x", "#2", "two")]), {
            1: pr("MERGED", merged="2026-10-17T00:00:00Z"), 2: pr("MERGED", merged="2026-10-18T00:00:00Z")})
        self.run_ps(gh, releases={1: "v18.12.2", 2: "v18.12.2"})
        new = self.block(gh.body)
        self.assertIn("**Merged 2 of 2** `■■` · in omp 18.12.2 · updated Oct 18\n", new)
        self.assertIn("| merged Oct 17 | #1 | one |", new)

    def test_mixed_releases_name_the_latest_and_count_the_released(self):
        """Spread across releases with one unreleased: the latest by version (18.12 after 18.9), and how
        many of the merged PRs have shipped; open PRs count in neither."""
        gh = FakeGitHub(post([("x", "#1", "a"), ("x", "#2", "b"), ("x", "#3", "c"), ("x", "#4", "d")]), {
            1: pr("MERGED", merged="2026-10-15T00:00:00Z"), 2: pr("MERGED", merged="2026-10-16T00:00:00Z"),
            3: pr("MERGED", merged="2026-10-17T00:00:00Z"), 4: pr()})
        self.run_ps(gh, releases={1: "v18.9.0", 2: "v18.12.2", 3: "unreleased"})
        self.assertIn("**Merged 3 of 4** `■■■□` · 2 of 3 released (omp 18.12.2) · 1 in review · updated Oct 18",
                      self.block(gh.body))

    def test_nothing_released_yet_then_a_release_ships(self):
        """pr-trace's first release, read from a real checkout: an untagged merge commit adds nothing to
        the headline and leaves the post alone; once a `v*` tag holds it, the headline names it."""
        repo = os.path.join(self.tmp, "checkout")

        def git(*a):
            return subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, text=True).stdout

        os.makedirs(repo)
        git("init", "-q")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "merge #1")
        sha = git("rev-parse", "HEAD").strip()
        body = post([("merged Oct 17", "#1", "w")], headline="**Merged 1 of 1** `■` · updated Oct 17")
        gh = FakeGitHub(body, {1: pr("MERGED", merged="2026-10-17T00:00:00Z", commit=sha)})
        code, out, _ = self.run_ps(gh, "--repo", repo)
        self.assertEqual((code, gh.updates), (0, []))
        self.assertIn("unchanged", out)
        git("tag", "v18.12.2")
        self.run_ps(gh, "--repo", repo)
        self.assertIn("**Merged 1 of 1** `■` · in omp 18.12.2 · updated Oct 18\r\n", gh.body)

    # --- the rest of the post -------------------------------------------------------------------

    def test_outside_markers_and_line_endings_untouched(self):
        body = post([("x", "#1", "w `code` | not a cell")])
        gh = FakeGitHub(body, {1: pr()})
        self.run_ps(gh)
        self.assertEqual(len(gh.updates), 1)
        start = body.index("<!-- series-status")
        end = body.index("<!-- /series-status -->")
        self.assertEqual(gh.body[:start], body[:start])
        self.assertEqual(gh.body[gh.body.index("<!-- /series-status -->"):], body[end:])
        self.assertIn("| in review | #1 | w `code` | not a cell |\r\n", gh.body)
        self.assertNotIn("\n", gh.body.replace("\r\n", ""))

    def test_no_write_when_only_the_date_would_change(self):
        body = post([("in review", "#1", "w")], headline="**Merged 0 of 1** `□` · 1 in review · updated Oct 1")
        gh = FakeGitHub(body, {1: pr()})
        code, out, _ = self.run_ps(gh)
        self.assertEqual((code, gh.updates), (0, []))
        self.assertIn("unchanged", out)

    def test_dry_run_prints_block_and_diff_and_writes_nothing(self):
        gh = FakeGitHub(post([("x", "#1", "w")]), {1: pr()})
        code, out, _ = self.run_ps(gh, "--dry-run")
        self.assertEqual((code, gh.updates), (0, []))
        self.assertIn("| in review | #1 | w |\n", out)
        self.assertIn("-| x | #1 | w |", out)
        self.assertIn("+| in review | #1 | w |", out)

    def test_body_file_is_a_dry_run(self):
        path = os.path.join(self.tmp, "post.md")
        with open(path, "w", newline="") as f:
            f.write(post([("x", "#1", "w")]))
        gh = FakeGitHub("unused", {1: pr()})
        code, out, _ = self.run_ps(gh, "--body", path)
        self.assertEqual((code, gh.updates, gh.reads), (0, [], 0))
        self.assertIn("+| in review | #1 | w |", out)

    def test_if_touched_skips_posts_not_listing_them(self):
        gh = FakeGitHub(post([("x", "#1", "w")]), {1: pr()})
        self.assertEqual(self.run_ps(gh, "--if-touched", "7,8")[0], 0)
        self.assertEqual(gh.updates, [])
        self.run_ps(gh, "--if-touched", "8,1")
        self.assertEqual(len(gh.updates), 1)

    # --- refusals -------------------------------------------------------------------------------

    def refused(self, body, prs=None, gh=None):
        gh = gh or FakeGitHub(body, prs or {1: pr()})
        code, _, err = self.run_ps(gh)
        self.assertEqual((code, gh.updates), (1, []))
        return err

    def test_refuses_missing_markers(self):
        self.assertIn("found 0 and 0", self.refused(BEFORE + AFTER))
        self.assertIn("found 1 and 0", self.refused(post([("x", "#1", "w")]).replace("<!-- /series-status -->", "")))

    def test_refuses_duplicated_markers(self):
        body = post([("x", "#1", "w")])
        self.assertIn("found 2 and 2", self.refused(body + body))

    def test_refuses_table_differing_from_marker_list(self):
        self.assertIn("differ", self.refused(post([("x", "#1", "w")], prs=[1, 2]), {1: pr(), 2: pr()}))
        self.assertIn("differ", self.refused(post([("x", "#1", "w"), ("x", "#1", "v")], prs=[1])))

    def test_refuses_when_the_post_changes_before_the_write(self):
        gh = FakeGitHub(post([("x", "#1", "w")]), {1: pr()})

        def edit(g):
            if g.reads == 2:
                g.body = g.body.replace("More hand-written", "Edited")
        gh.on_read = edit
        self.assertIn("changed while", self.refused(None, gh=gh))

    def test_read_back_mismatch_is_reported(self):
        gh = FakeGitHub(post([("x", "#1", "w")]), {1: pr()})
        gh.readback = lambda body: body.replace("Intro", "intro")
        code, _, err = self.run_ps(gh)
        self.assertEqual((code, len(gh.updates)), (2, 1))
        self.assertIn("WRITTEN, but", err)


if __name__ == "__main__":
    unittest.main()
