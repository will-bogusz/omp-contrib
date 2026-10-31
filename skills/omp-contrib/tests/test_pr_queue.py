"""pr-queue against a bare-repo upstream/fork simulation: upstream.git (can1357), fork.git
(octo-fork), `work` (our checkout, remotes origin and fork) and `maint` (the maintainer's clone).
GitHub is a fake; git is real. Run: python3 -m unittest discover -s tests"""
import contextlib
import datetime
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
ROOT = tempfile.mkdtemp(prefix="pr-queue-test-")
GITCONFIG = os.path.join(ROOT, "gitconfig")
with open(GITCONFIG, "w") as f:
    f.write("[user]\n\tname = Tester\n\temail = tester@example.test\n[init]\n\tdefaultBranch = main\n"
            "[commit]\n\tgpgsign = false\n[advice]\n\tdetachedHead = false\n")
os.environ.update(GIT_CONFIG_GLOBAL=GITCONFIG, GIT_CONFIG_NOSYSTEM="1")

import omp_config  # noqa: E402
import omp_pr  # noqa: E402
import omp_queue  # noqa: E402
import omp_watch  # noqa: E402

loader = importlib.machinery.SourceFileLoader("pr_queue", os.path.join(SCRIPTS, "pr-queue"))
spec = importlib.util.spec_from_loader("pr_queue", loader)
PQ = importlib.util.module_from_spec(spec)
loader.exec_module(PQ)
loader = importlib.machinery.SourceFileLoader("precheck", os.path.join(SCRIPTS, "precheck"))
spec = importlib.util.spec_from_loader("precheck", loader)
PC = importlib.util.module_from_spec(spec)
loader.exec_module(PC)
loader = importlib.machinery.SourceFileLoader("rust_check", os.path.join(SCRIPTS, "rust-check"))
spec = importlib.util.spec_from_loader("rust_check", loader)
RC = importlib.util.module_from_spec(spec)
loader.exec_module(RC)

CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-10-01\n\n### Fixed\n\n- Old fix\n"
BODY = ("## What\n\nI fixed the thing users hit.\n\n## Why\n\nIt broke.\n\n## Testing\n\nRan it; it works.\n")


def tearDownModule():
    shutil.rmtree(ROOT, ignore_errors=True)


def sh(cwd, *args, env=None, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and p.returncode:
        raise AssertionError(f"{' '.join(args)} in {cwd}: {p.stderr}{p.stdout}")
    return p


def ago(days):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGitHub:
    def __init__(self, sim):
        self.sim, self.prs, self.events, self.active_set, self.next = sim, {}, 0, set(), 900
        self.closed, self.readied = [], []
        self.left = 5000
        self.post_merge, self.asked_post_merge = {}, []

    def post_merge_open(self, merges, cwd):
        self.asked_post_merge.append([m["number"] for m in merges])
        return {m["number"]: self.post_merge.get(m["number"], []) for m in merges}

    def budget(self):
        return self.left, datetime.datetime(2026, 10, 19, 0, 3, tzinfo=datetime.timezone.utc)

    def add_pr(self, number, branch, title, body=BODY, draft=False, rank=None, created=None, base="main"):
        self.prs[number] = {"branch": branch, "base": base, "title": title, "body": body, "draft": draft,
                            "rank": rank, "created": created or ago(0), "url": f"https://example.test/pull/{number}",
                            "state": "OPEN"}
        sh(self.sim.work, "git", "push", "-q", "origin", f"refs/remotes/fork/{branch}:refs/pull/{number}/head")

    def open_prs(self):
        return {n: dict(p) for n, p in self.prs.items() if p["state"] == "OPEN"}

    def states(self, numbers):
        return {n: self.prs[n]["state"] for n in numbers if n in self.prs}

    def merged_since(self, since, after=""):
        return [{"number": n, "title": p["title"], "url": p["url"], "merged_at": p["merged_at"], "merged_by": "the maintainer",
                 "merge_commit": p["merge_commit"], "maintainer_commits": p["maintainer_commits"]}
                for n, p in sorted(self.prs.items()) if p["state"] == "MERGED" and p["merged_at"] > after]

    def active(self, numbers, days):
        return set(numbers) & self.active_set

    def ready_events_since(self, since):
        return self.events

    def tier(self):
        return "contributor", 10  # roboomp's cap 10: a ready budget of 8

    def create_draft(self, branch, title, body_file):
        self.next += 1
        with open(body_file) as f:
            self.add_pr(self.next, branch, title, f.read(), draft=True)
        return self.next

    def ready(self, number):
        self.prs[number]["draft"] = False
        self.readied.append(number)
        self.events += 1

    def close(self, number):
        self.prs[number]["state"] = "CLOSED"
        self.closed.append(number)

    def body(self, number):
        return self.prs[number]["body"]


class Sim:
    def __init__(self, root):
        self.root = root
        self.upstream, self.fork = os.path.join(root, "upstream.git"), os.path.join(root, "fork.git")
        sh(root, "git", "init", "-q", "--bare", self.upstream)
        sh(root, "git", "init", "-q", "--bare", self.fork)
        seed = os.path.join(root, "seed")
        sh(root, "git", "clone", "-q", self.upstream, seed)
        self.write(seed, ".gitattributes", "packages/*/CHANGELOG.md merge=union\n")
        for pkg, letter in (("a", "x"), ("b", "y")):
            self.write(seed, f"packages/{pkg}/src/{letter}.txt", "".join(f"{letter}{i}\n" for i in range(1, 21)))
            self.write(seed, f"packages/{pkg}/CHANGELOG.md", CHANGELOG)
        sh(seed, "git", "add", "-A")
        sh(seed, "git", "commit", "-q", "-m", "base")
        sh(seed, "git", "push", "-q", "origin", "main")
        sh(seed, "git", "push", "-q", self.fork, "main")
        self.work, self.maint = os.path.join(root, "work"), os.path.join(root, "maint")
        sh(root, "git", "clone", "-q", self.upstream, self.work)
        sh(self.work, "git", "remote", "add", "fork", self.fork)
        sh(self.work, "git", "fetch", "-q", "fork")
        sh(root, "git", "clone", "-q", self.upstream, self.maint)
        sh(self.maint, "git", "remote", "add", "fork", self.fork)
        sh(self.maint, "git", "config", "user.name", "the maintainer")
        sh(self.maint, "git", "config", "user.email", "maintainer@example.test")

    @staticmethod
    def write(repo, path, text):
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)

    @staticmethod
    def read(repo, path):
        with open(os.path.join(repo, path)) as f:
            return f.read()

    def edit(self, repo, path, line, text):
        lines = self.read(repo, path).split("\n")
        lines[line - 1] = text
        self.write(repo, path, "\n".join(lines))

    def add_entry(self, repo, pkg, entry):
        lines = self.read(repo, f"packages/{pkg}/CHANGELOG.md").split("\n")
        start = lines.index("## [Unreleased]")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## ["))
        fixed = next((i for i in range(start, end) if lines[i] == "### Fixed"), None)
        if fixed is None:
            lines[start + 1:start + 1] = ["", "### Fixed", "", f"- {entry}"]
        else:
            lines.insert(fixed + 2, f"- {entry}")
        self.write(repo, f"packages/{pkg}/CHANGELOG.md", "\n".join(lines))

    def change(self, repo, line, text, msg, pkg="a", entry=None):
        letter = {"a": "x", "b": "y"}[pkg]
        self.edit(repo, f"packages/{pkg}/src/{letter}.txt", line, text)
        if entry:
            self.add_entry(repo, pkg, entry)
        sh(repo, "git", "commit", "-q", "-am", msg)
        return sh(repo, "git", "rev-parse", "HEAD").stdout.strip()

    def branch(self, name, start="origin/main", line=None, text=None, pkg="a", entry=None, push=True):
        sh(self.work, "git", "checkout", "-q", "-b", name, start)
        if line:
            self.change(self.work, line, text, f"fix(a): {name}", pkg, entry or f"Fixed {name}")
        sh(self.work, "git", "checkout", "-q", "--detach")
        if push:
            sh(self.work, "git", "push", "-q", "fork", name)
        return sh(self.work, "git", "rev-parse", name).stdout.strip()

    def maint_sync(self):
        sh(self.maint, "git", "checkout", "-q", "main")
        sh(self.maint, "git", "pull", "-q", "--ff-only", "origin", "main")
        sh(self.maint, "git", "fetch", "-q", "fork")

    def upstream_change(self, line, text, pkg="b"):
        self.maint_sync()
        self.change(self.maint, line, text, "chore: unrelated upstream work", pkg)
        sh(self.maint, "git", "push", "-q", "origin", "main")

    def merge(self, gh, number, fixup=None):
        """Merge PR `number` with a merge commit; with `fixup` (line, text), first rebase it onto main
        and fold that edit into its last commit, as the maintainer did on 2026-10-12."""
        self.maint_sync()
        branch = gh.prs[number]["branch"]
        head = f"fork/{branch}"
        if fixup:
            sh(self.maint, "git", "checkout", "-q", "-b", f"pr-{number}", head)
            sh(self.maint, "git", "rebase", "-q", "origin/main")
            self.edit(self.maint, "packages/a/src/x.txt", *fixup)
            sh(self.maint, "git", "commit", "-q", "-a", "--amend", "--no-edit")
            sh(self.maint, "git", "checkout", "-q", "main")
            head = f"pr-{number}"
        sh(self.maint, "git", "merge", "-q", "--no-ff", head, "-m", f"Merge PR #{number}")
        sh(self.maint, "git", "push", "-q", "origin", "main")
        gh.prs[number].update(state="MERGED", merged_at=omp_queue.stamp(),
                              merge_commit=sh(self.maint, "git", "rev-parse", "HEAD").stdout.strip(),
                              maintainer_commits=["fix: review nits"] if fixup else [])

    def cherry_pick(self, sha):
        self.maint_sync()
        sh(self.maint, "git", "fetch", "-q", self.fork, "+refs/heads/*:refs/remotes/fork/*")
        sh(self.maint, "git", "cherry-pick", sha)
        sh(self.maint, "git", "push", "-q", "origin", "main")

    def release(self, tag=None):
        self.maint_sync()
        for pkg in ("a", "b"):
            path = f"packages/{pkg}/CHANGELOG.md"
            self.write(self.maint, path, self.read(self.maint, path).replace(
                "## [Unreleased]\n", "## [Unreleased]\n\n## [1.1.0] - 2026-10-13\n", 1))
        sh(self.maint, "git", "commit", "-q", "-am", "chore: release 1.1.0")
        sh(self.maint, "git", "push", "-q", "origin", "main")
        if tag:
            sh(self.maint, "git", "tag", tag)
            sh(self.maint, "git", "push", "-q", "origin", tag)

    def show(self, ref, path):
        return sh(self.work, "git", "show", f"{ref}:{path}").stdout


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=ROOT)
        self.sim = Sim(self.dir)
        self.gh = FakeGitHub(self.sim)
        PQ.WORKTREES = os.path.join(self.dir, "worktrees")
        # The live series-posts list would send watch tests to GitHub; each test names its own.
        PQ.SERIES_POSTS = os.path.join(self.dir, "series-posts")
        self.body = os.path.join(self.dir, "body.md")
        with open(self.body, "w") as f:
            f.write(BODY)

    def run_pq(self, *argv, repo=None):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                PQ.main(["--repo", repo or self.sim.work, *argv], github=self.gh)
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue() + err.getvalue()

    def plan(self):
        code, out = self.run_pq("plan", "--json")
        self.assertEqual(code, 0, out)
        return {r["label"]: r for r in json.loads(out)["rows"]}

    def manifest(self, repo=None):
        code, out = self.run_pq("show", "--json", repo=repo)
        self.assertEqual(code, 0, out)
        return {e["id"]: e for e in json.loads(out)["entries"]}

    def open_parent_and_queue_child(self):
        self.sim.branch("octo-fork/p", line=3, text="P3")
        self.gh.add_pr(101, "octo-fork/p", "fix(a): parent", rank="P1")
        self.sim.branch("octo-fork/c", start="octo-fork/p", line=12, text="C12", entry="Fixed the child")
        code, out = self.run_pq("add", "octo-fork/c", "--title", "fix(a): child", "--needs", "#101", "--priority", "P1",
                                "--body", self.body)
        self.assertEqual(code, 0, out)
        p_tip = sh(self.sim.work, "git", "rev-parse", "octo-fork/p").stdout.strip()
        self.assertEqual(self.manifest()["c"]["base"], p_tip, "base is the parent's tip")

    def test_a_local_manifest_is_a_dry_run(self):
        # A verification run's `add … --manifest F` (flag after the command) pushed its branch to the
        # fork, and it offered `open … --manifest F`, which would open a real PR from a dry run.
        self.sim.branch("octo-fork/dry", line=3, text="D3", push=False)
        manifest = os.path.join(self.dir, "dry.json")
        code, out = self.run_pq("add", "octo-fork/dry", "--title", "fix(a): dry", "--body", self.body,
                                "--manifest", manifest)
        self.assertEqual(code, 0, out)
        with open(manifest) as f:
            self.assertIn("dry", {e["id"] for e in json.load(f)["entries"]})
        pushed = sh(self.sim.work, "git", "ls-remote", "fork", "refs/heads/octo-fork/dry").stdout
        self.assertEqual(pushed, "", "a dry run never pushes its branch")
        for argv in (["open", "dry", "--user-approved"], ["requeue", "101"]):
            code, out = self.run_pq("--manifest", manifest, *argv)
            self.assertEqual(code, 1, out)
            self.assertIn("refused with --manifest", out)

    def test_a_child_is_judged_against_main_with_its_open_need_merged_in(self):
        # inflight-epoch (2026-10-14) sits on open #15762 and edits next to it: against main alone
        # its own commits "conflicted" with #15762's lines, though main + #15762 + it merges clean.
        self.sim.branch("octo-fork/p", line=3, text="P3")
        self.gh.add_pr(101, "octo-fork/p", "fix(a): parent", rank="P1")
        self.sim.branch("octo-fork/c", start="octo-fork/p", line=4, text="C4 next to P3")
        self.run_pq("add", "octo-fork/c", "--title", "fix(a): child", "--needs", "#101")
        self.assertEqual(self.plan()["c"]["reasons"], ["needs #101 (open)"])
        self.sim.upstream_change(5, "M5 next to C4", pkg="a")  # a real conflict with main still shows
        self.assertEqual(self.plan()["c"]["reasons"],
                         ["needs #101 (open)", "conflicts with main in packages/a/src/x.txt"])
        self.sim.upstream_change(3, "M3 against P3", pkg="a")  # now the need itself conflicts with main
        self.assertEqual(self.plan()["c"]["reasons"],
                         ["needs #101 (open)", "its need #101 conflicts with main in packages/a/src/x.txt"])

    def test_an_open_parent_that_outgrows_its_queued_child_keeps_its_own_commits(self):
        self.open_parent_and_queue_child()
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/p")
        for line, text in ((6, "P6"), (8, "P8")):  # bot fixes pushed to the open parent
            self.sim.change(self.sim.work, line, text, f"fix(a): parent fix {line}")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "fork", "octo-fork/p")
        plan = self.plan()
        self.assertEqual(plan["#101"]["action"], "keep", plan["#101"]["reasons"])
        self.assertIn("needs #101 (open)", plan["c"]["reasons"][0])

    def test_child_of_open_parent_waits(self):
        self.open_parent_and_queue_child()
        row = self.plan()["c"]
        self.assertEqual(row["action"], "wait")
        self.assertIn("needs #101 (open)", row["reasons"][0])
        self.assertEqual(self.plan()["#101"]["action"], "keep")
        code, out = self.run_pq("advance")
        self.assertIn("c: waits on #101 (open)", out)

    def test_a_held_entry_never_opens_until_unheld(self):
        # 2026-10-18: relay-popup-lossless was held for the user's OK in a note, which plan and open never
        # read, so the round's opener would open it as soon as its need merged.
        self.open_parent_and_queue_child()
        reason = "me, 2026-10-18: waits on my OK for the permission dependency"
        code, out = self.run_pq("set", "c", "--hold", reason)
        self.assertEqual(code, 0, out)
        self.sim.merge(self.gh, 101)
        self.run_pq("sync")
        self.assertEqual(self.run_pq("advance")[0], 0, "advance still rebases a held entry")
        row = self.plan()["c"]
        self.assertEqual((row["action"], row["reasons"]), ("held", [f"held: {reason}"]))
        self.assertIn("held 1", self.run_pq("plan")[1])
        code, out = self.run_pq("open", "c")
        self.assertEqual(code, 1, out)
        self.assertIn(f"c is held: {reason}", out)
        self.assertEqual((self.manifest()["c"]["state"], list(self.gh.prs)), ("queued", [101]), "nothing opened")
        code, out = self.run_pq("set", "c", "--unhold")
        self.assertEqual(code, 0, out)
        self.assertNotIn("hold", self.manifest()["c"])
        self.assertEqual(self.plan()["c"]["action"], "open")

    def test_an_opening_pause_stops_every_open_until_unpaused(self):
        # A pause relayed in one session's note reaches no other session, which then opens PRs (#101,
        # #102) during it. The pause lives in the queue every session reads.
        self.sim.branch("octo-fork/r", line=9, text="R9")
        self.gh.add_pr(301, "octo-fork/r", "fix(a): r", rank="P0")
        self.sim.branch("octo-fork/q", line=5, text="Q5", entry="Fixed q")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body, "--priority", "P1")
        self.assertEqual(self.plan()["q"]["action"], "open")
        reason = "user, 2026-01-02: pause for maintainer round"
        code, out = self.run_pq("pause", reason)
        self.assertEqual(code, 0, out)
        plan = self.plan()
        self.assertEqual((plan["q"]["action"], plan["#301"]["action"]), ("paused", "keep"),
                         "the queued entry is paused; the open PR is kept as before")
        code, out = self.run_pq("plan")
        self.assertTrue(out.startswith(f"OPENING PAUSED ({reason}): "), out)
        self.assertIn("other: keep 1, paused 1\n", out)
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 1, out)
        self.assertIn(f"not opening q: OPENING PAUSED ({reason})", out)
        code, out = self.run_pq("show", "--json")
        self.assertNotIn("opening", json.loads(out), "refused before taking the lock")
        self.assertEqual(list(self.gh.prs), [301], "nothing opened")
        code, out = self.run_pq("unpause")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.plan()["q"]["action"], "open")
        self.assertEqual(self.run_pq("built", "q", "#301")[0], 0)
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.gh.readied, [self.gh.next])

    def test_hold_is_refused_on_an_entry_that_is_not_queued(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        self.run_pq("set", "q", "--state", "closed")
        code, out = self.run_pq("set", "q", "--hold", "me, 2026-10-18: later")
        self.assertEqual(code, 1, out)
        self.assertIn("only a queued entry is held", out)

    def with_config(self, text):
        """Run the rest of the test under a config file holding `text` (references/config.md)."""
        # Subprocesses (precheck) read it too: keep the test identity, or they would ask gh who you are.
        ident = f'[github]\nfork_owner = "{contrib_env.FORK_OWNER}"\nfork_remote = "fork"\n\n'
        path = contrib_env.write_config(os.path.join(self.dir, "config.toml"), ident + text)
        patch = mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": path})
        patch.start()
        self.addCleanup(omp_config.load, True)
        self.addCleanup(patch.stop)
        omp_config.load(reload=True)
        return path

    def queue_r_and_q(self, *add):
        self.sim.branch("octo-fork/r", line=9, text="R9")
        self.gh.add_pr(301, "octo-fork/r", "fix(a): r", rank="P0")
        self.sim.branch("octo-fork/q", line=5, text="Q5", entry="Fixed q")
        code, out = self.run_pq("add", "octo-fork/q", "--title", "feat(a): q setting", "--body", self.body, *add)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_pq("built", "q", "#301")[0], 0)
        return out

    def test_a_p2_by_design_change_waits_for_the_users_approval(self):
        decision = "default `a.mode` to strict instead of lenient"
        self.with_config('[autonomy]\nopen_p2 = "hold"\nsupervised_opens = 0\n')
        out = self.queue_r_and_q("--p2-decision", decision)
        self.assertIn(f"held until you approve its maintainer decision: {decision} (pr-queue approve q)", out)
        row = self.plan()["q"]
        self.assertEqual((row["action"], row["reasons"][0], row["awaiting_user"], row["p2_decision"]),
                         ("held", f"held: user decision pending: {decision}", True, decision))
        code, out = self.run_pq("plan")
        self.assertIn(f"Awaiting your decision (P2 by design; `pr-queue approve ID` lets it open, autonomy.open_p2):\n"
                      f"  q: {decision}\n", out)
        self.assertIn("held 1", out)
        code, out = self.run_pq("show")
        self.assertTrue(any(line.startswith("held ") and " q " in line for line in out.splitlines()), out)
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 1, out)
        self.assertIn(f"q is held: user decision pending: {decision}. It is P2 by design: only the user approves", out)
        self.assertEqual(list(self.gh.prs), [301], "nothing opened")
        code, out = self.run_pq("approve", "q")
        self.assertEqual(code, 0, out)
        self.assertIn(f"approved q's decision: {decision}; it opens when plan says so", out)
        self.assertTrue(self.manifest()["q"]["p2_approved"])
        self.assertEqual(self.plan()["q"]["action"], "open")
        self.assertNotIn("Awaiting your decision", self.run_pq("plan")[1])
        # A changed decision needs its own approval; dropping it lifts the hold.
        self.run_pq("set", "q", "--p2-decision", "add a `a.strict` setting")
        self.assertNotIn("p2_approved", self.manifest()["q"])
        self.assertEqual(self.plan()["q"]["action"], "held")
        self.run_pq("set", "q", "--no-p2-decision")
        self.assertEqual(self.plan()["q"]["action"], "open")
        code, out = self.run_pq("approve", "q")
        self.assertEqual(code, 1, out)
        self.assertIn("carries no P2 decision", out)

    def test_open_p2_open_lets_a_p2_decision_open_without_approval(self):
        self.with_config('[autonomy]\nopen_p2 = "open"\nsupervised_opens = 0\n')
        self.queue_r_and_q("--p2-decision", "add a setting")
        self.assertEqual(self.plan()["q"]["action"], "open")
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 0, out)

    def test_supervised_start_refuses_open_without_the_users_ok_then_counts_down(self):
        path = self.with_config('[autonomy]\nopen_p2 = "hold"\nsupervised_opens = 1  # first PRs\n')
        self.queue_r_and_q()
        code, out = self.run_pq("plan")
        self.assertIn("Supervised start: the next 1 open(s) need your explicit OK first", out)
        self.assertEqual(self.plan()["q"]["action"], "open", "plan still says it opens")
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 1, out)
        self.assertIn("not opening q: supervised start, 1 open(s) left that need the user's explicit OK", out)
        self.assertIn("pr-queue open q --user-approved", out)
        self.assertEqual(list(self.gh.prs), [301], "nothing opened")
        code, out = self.run_pq("open", "q", "--user-approved")
        self.assertEqual(code, 0, out)
        self.assertIn("supervised start: 0 supervised open(s) left; opens are autonomous from now", out)
        self.assertEqual(self.gh.readied, [self.gh.next])
        with open(path) as f:
            self.assertTrue(f.read().endswith('\n[autonomy]\nopen_p2 = "hold"\nsupervised_opens = 0  # first PRs\n'))
        self.assertNotIn("Supervised start", self.run_pq("plan")[1])

    def test_plan_names_the_ready_budget_from_the_authors_tier(self):
        self.queue_r_and_q()
        code, out = self.run_pq("plan")
        self.assertIn("Ready budget: 0 of 8 events used in the last hour, 8 left "
                      "(roboomp caps a contributor author at 10 an hour).", out)
        with mock.patch.object(self.gh, "tier", return_value=("first-time", 3), create=True):
            self.assertIn("0 of 1 events", self.run_pq("plan")[1])
        with mock.patch.object(self.gh, "tier", return_value=("maintainer", None), create=True):
            self.assertIn("(roboomp does not cap a maintainer author)", self.run_pq("plan")[1])

    def test_parent_merged_with_merge_commit_then_child_advances(self):
        self.open_parent_and_queue_child()
        code, out = self.run_pq("sync")
        self.assertIn("#101 imported as p (other, P1)", out)
        self.sim.merge(self.gh, 101)
        self.sim.release()  # the parent's entry moves under 1.1.0; the child's must stay in [Unreleased]
        code, out = self.run_pq("sync")
        self.assertIn("#101 p: merged", out)
        self.assertEqual(self.manifest()["p"]["state"], "merged")
        code, out = self.run_pq("advance")
        self.assertEqual(code, 0, out)
        main = sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip()
        own = sh(self.sim.work, "git", "rev-list", "origin/main..fork/octo-fork/c").stdout.split()
        self.assertEqual(len(own), 1, out)
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/c^").stdout.strip(), main)
        log = self.sim.show("fork/octo-fork/c", "packages/a/CHANGELOG.md")
        unreleased = log.split("## [Unreleased]", 1)[1].split("## [1.1.0]", 1)[0]
        self.assertIn("- Fixed the child", unreleased, log)
        self.assertEqual(self.manifest()["c"]["base"], main)
        self.assertEqual(self.plan()["c"]["action"], "open")

    def test_parent_rebased_and_fixed_up_then_child_advances(self):
        self.open_parent_and_queue_child()
        self.sim.upstream_change(1, "unrelated")
        self.sim.merge(self.gh, 101, fixup=(3, "P3 fixed by the maintainer"))
        self.run_pq("sync")
        # A plain `git rebase origin/main` replays the parent's old commit and conflicts.
        naive = os.path.join(self.dir, "naive")
        sh(self.sim.work, "git", "worktree", "add", "-q", "--detach", naive, "octo-fork/c")
        self.assertNotEqual(sh(naive, "git", "rebase", "origin/main", check=False).returncode, 0)
        sh(naive, "git", "rebase", "--abort")
        sh(self.sim.work, "git", "worktree", "remove", "--force", naive)
        code, out = self.run_pq("advance")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(sh(self.sim.work, "git", "rev-list", "origin/main..fork/octo-fork/c").stdout.split()), 1)
        x = self.sim.show("fork/octo-fork/c", "packages/a/src/x.txt").split("\n")
        self.assertEqual((x[2], x[11]), ("P3 fixed by the maintainer", "C12"))
        self.assertEqual(self.plan()["c"]["action"], "open")

    def test_advance_stops_on_a_conflict_and_resumes_after_it_is_resolved(self):
        self.sim.branch("octo-fork/p", line=3, text="P3")
        self.gh.add_pr(101, "octo-fork/p", "fix(a): parent", rank="P1")
        self.sim.branch("octo-fork/c", start="octo-fork/p", line=4, text="C4 next to P3")
        self.run_pq("add", "octo-fork/c", "--title", "fix(a): child", "--needs", "#101")
        self.sim.merge(self.gh, 101, fixup=(4, "P4 added by the maintainer"))
        code, out = self.run_pq("advance")
        self.assertEqual(code, 1, out)
        self.assertIn("c: CONFLICT replaying its own commits onto origin/main", out)
        self.assertIn("packages/a/src/x.txt", out)
        wt = os.path.join(PQ.WORKTREES, "c")
        self.assertTrue(PQ.in_rebase(wt), "left stopped for an agent to resolve")
        resolved = sh(wt, "git", "show", "origin/main:packages/a/src/x.txt").stdout.split("\n")
        resolved[3] = "C4 next to P3"  # the child's line wins over the maintainer's, the rest is main's
        self.sim.write(wt, "packages/a/src/x.txt", "\n".join(resolved))
        sh(wt, "git", "add", "-A")
        sh(wt, "git", "rebase", "--continue", env={"GIT_EDITOR": ":"})
        code, out = self.run_pq("advance", "c")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(sh(self.sim.work, "git", "rev-list", "origin/main..fork/octo-fork/c").stdout.split()), 1)
        self.assertEqual(self.sim.show("fork/octo-fork/c", "packages/a/src/x.txt"), "\n".join(resolved))
        self.assertEqual(self.plan()["c"]["action"], "open")

    def test_unrelated_upstream_change_needs_no_rebase(self):
        tip = self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        self.sim.upstream_change(1, "unrelated")
        row = self.plan()["q"]
        self.assertEqual((row["action"], row["note"]), ("open", ""))
        code, out = self.run_pq("advance")
        self.assertIn("nothing to do", out)
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/q").stdout.strip(), tip)

    def test_conflicting_siblings_only_one_eligible(self):
        self.sim.branch("octo-fork/s1", line=7, text="S1")
        self.sim.branch("octo-fork/s2", line=7, text="S2")
        self.run_pq("add", "octo-fork/s1", "--title", "feat(a): s1", "--priority", "P1")
        self.run_pq("add", "octo-fork/s2", "--title", "fix(a): s2", "--priority", "P1")
        rows = self.plan()
        self.assertEqual(rows["s2"]["action"], "open", "a fix goes before a feature at the same rank")
        self.assertEqual(rows["s1"]["action"], "wait")
        self.assertIn("conflicts with s2 in packages/a/src/x.txt", rows["s1"]["reasons"])
        self.run_pq("set", "s1", "--priority", "P0")
        rows = self.plan()
        self.assertEqual((rows["s1"]["action"], rows["s2"]["action"]), ("open", "wait"))

    def test_a_queued_change_opens_however_many_prs_its_area_has_open(self):
        spots = [("a", 2), ("a", 6), ("a", 10), ("a", 14), ("b", 2), ("b", 6), ("b", 14)]
        for n, (pkg, line) in enumerate(spots, start=311):
            self.sim.branch(f"octo-fork/k{n}", line=line, text=f"K{n}", pkg=pkg)
            self.gh.add_pr(n, f"octo-fork/k{n}", f"fix(a): k{n}", rank="P1")
        self.sim.branch("octo-fork/n", line=10, text="N10", pkg="b")
        self.run_pq("add", "octo-fork/n", "--title", "fix(b): n", "--priority", "P2")
        rows = self.plan()
        self.assertEqual({rows[f"#{n}"]["area"] for n in range(311, 318)} | {rows["n"]["area"]}, {"other"})
        self.assertEqual([rows[f"#{n}"]["action"] for n in range(311, 318)], ["keep"] * 7)
        self.assertEqual((rows["n"]["action"], rows["n"]["reasons"]), ("open", []),
                         "it merges alone and clashes with no open ready PR: nothing else holds it back")
        code, out = self.run_pq("plan")
        self.assertIn("other: keep 7, open 1\n", out)

    def test_advance_names_prs_in_replayed_messages_without_linking_them(self):
        self.sim.branch("octo-fork/p", line=3, text="P3")
        self.gh.add_pr(101, "octo-fork/p", "fix(a): parent", rank="P1")
        sh(self.sim.work, "git", "checkout", "-q", "-b", "octo-fork/c", "octo-fork/p")
        self.sim.change(self.sim.work, 12, "C12", "fix(a): take #101's mode\n\nAs can1357/oh-my-pi#77 asked.",
                        entry="Fixed the child")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "fork", "octo-fork/c")
        self.run_pq("add", "octo-fork/c", "--title", "fix(a): child", "--needs", "#101", "--body", self.body)
        self.run_pq("sync")
        self.sim.merge(self.gh, 101)
        self.sim.release()  # the child's CHANGELOG line would land under 1.1.0: advance replays it
        self.run_pq("sync")
        code, out = self.run_pq("advance")
        self.assertEqual(code, 0, out)
        self.assertIn("1 replayed commit message(s) name PRs as `PR N` now", out)
        message = sh(self.sim.work, "git", "log", "-1", "--format=%B", "fork/octo-fork/c").stdout
        self.assertEqual(message.strip(), "fix(a): take PR 101's mode\n\nAs PR 77 asked.")
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/c^").stdout.strip(),
                         sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip())
        self.assertEqual(self.sim.show("fork/octo-fork/c", "packages/a/src/x.txt").split("\n")[11], "C12")

    def test_conflict_with_main_alone_rebases_in_place(self):
        self.sim.branch("octo-fork/r", line=9, text="R9")
        self.sim.branch("octo-fork/r2", line=9, text="R9 too")
        self.gh.add_pr(321, "octo-fork/r", "fix(a): r", rank="P1")
        self.gh.add_pr(322, "octo-fork/r2", "fix(a): r2", rank="P2")
        self.sim.upstream_change(9, "M9 from upstream", pkg="a")
        self.run_pq("sync")
        rows = self.plan()
        self.assertEqual(rows["#321"]["action"], "rebase")
        self.assertEqual(rows["#321"]["reasons"], ["conflicts with main in packages/a/src/x.txt"])
        self.assertEqual(rows["#322"]["action"], "requeue", "it also conflicts with #321, which ranks higher")
        self.assertIn("conflicts with #321 in packages/a/src/x.txt", rows["#322"]["reasons"])
        code, out = self.run_pq("advance")
        self.assertNotIn("r:", out, "an open PR is advanced only by name")
        code, out = self.run_pq("advance", "#321")
        self.assertEqual(code, 1, out)
        self.assertIn("r: CONFLICT replaying its own commits onto origin/main", out)
        wt = os.path.join(PQ.WORKTREES, "r")
        resolved = sh(wt, "git", "show", "origin/main:packages/a/src/x.txt").stdout.split("\n")
        resolved[8] = "R9 over M9"
        self.sim.write(wt, "packages/a/src/x.txt", "\n".join(resolved))
        sh(wt, "git", "add", "-A")
        sh(wt, "git", "rebase", "--continue", env={"GIT_EDITOR": ":"})
        code, out = self.run_pq("advance", "#321")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.gh.closed, [], "the PR stays open")
        self.assertEqual(self.manifest()["r"]["state"], "open")
        self.assertEqual(self.plan()["#321"]["action"], "keep")

    # GitHub's mergeability ignores the CHANGELOG merge=union: with main at af7b2c50aa (2026-10-18)
    # #16119, #15105 and #15184 read CONFLICTING there in packages/coding-agent/CHANGELOG.md alone.
    def upstream_entry(self, line, text, entry, pkg="a"):
        """main gains a code change and an [Unreleased] line, as #15751 did on 2026-10-18."""
        self.sim.maint_sync()
        self.sim.change(self.sim.maint, line, text, "fix: upstream work", pkg, entry)
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")

    def fork_tip(self, branch):
        return sh(self.sim.work, "git", "rev-parse", f"fork/{branch}").stdout.strip()

    def test_github_changelog_only_conflict_is_information_in_plan_and_audit(self):
        self.sim.branch("octo-fork/g", line=5, text="G5")
        self.sim.branch("octo-fork/h", line=15, text="H15", pkg="b")
        self.sim.branch("octo-fork/r", line=1, text="R1", pkg="b")
        for n, branch in ((331, "octo-fork/g"), (332, "octo-fork/h"), (333, "octo-fork/r")):
            self.gh.add_pr(n, branch, f"fix(a): {branch}", rank="P1")
        self.upstream_entry(1, "M1", "Fixed upstream")  # a CHANGELOG line in a, code in a away from #331's
        self.sim.upstream_change(1, "M1 in b")  # #333's code conflict: a real one, with no GitHub line
        self.run_pq("sync")
        tips = {b: self.fork_tip(b) for b in ("octo-fork/g", "octo-fork/h", "octo-fork/r")}
        rows = self.plan()
        self.assertEqual((rows["#331"]["action"], rows["#331"]["reasons"]), ("keep", []),
                         "a union-clean CHANGELOG overlap still merges alone (open-PR rule)")
        self.assertEqual(rows["#331"]["github"], {"main": ["packages/a/CHANGELOG.md"], "pairs": []})
        self.assertEqual(rows["#332"]["github"], {"main": [], "pairs": []}, "main's line is in another package")
        self.assertEqual(rows["#333"]["action"], "rebase")
        self.assertEqual(rows["#333"]["github"], {"main": [], "pairs": []}, "a code conflict is its own state")
        code, out = self.run_pq("plan")
        self.assertIn("GitHub: conflicting (CHANGELOG only: packages/a/CHANGELOG.md); the next needed push "
                      "rebases onto main (`pr-queue advance", out)
        code, out = self.run_pq("audit")
        self.assertIn("\n  GitHub: conflicting (CHANGELOG only: packages/a/CHANGELOG.md)", out)
        self.assertIn("1 of 3 open PRs break the rule: conflicts with main 1", out)
        self.run_pq("advance")
        self.assertEqual({b: self.fork_tip(b) for b in tips}, tips, "nothing pushes for it by itself")
        # The needed push names the PR: advance rebases it, and GitHub reads it clean.
        code, out = self.run_pq("advance", "#331")
        self.assertEqual(code, 0, out)
        self.assertNotEqual(self.fork_tip("octo-fork/g"), tips["octo-fork/g"])
        self.assertEqual(self.plan()["#331"]["github"], {"main": [], "pairs": []})
        log = self.sim.show("fork/octo-fork/g", "packages/a/CHANGELOG.md")
        self.assertIn("- Fixed upstream\n", log)
        self.assertIn("- Fixed octo-fork/g\n", log)

    def test_github_pair_conflict_shows_before_either_merges(self):
        self.sim.branch("octo-fork/g", line=5, text="G5")
        self.sim.branch("octo-fork/k", line=15, text="K15")
        self.gh.add_pr(341, "octo-fork/g", "fix(a): g", rank="P1")
        self.gh.add_pr(342, "octo-fork/k", "fix(a): k", rank="P1")
        self.run_pq("sync")
        rows = self.plan()
        self.assertEqual([(rows[n]["action"], rows[n]["reasons"]) for n in ("#341", "#342")], [("keep", [])] * 2)
        self.assertEqual(rows["#341"]["github"], {"main": [], "pairs": [["#342", ["packages/a/CHANGELOG.md"]]]})
        self.assertEqual(rows["#342"]["github"], {"main": [], "pairs": [["#341", ["packages/a/CHANGELOG.md"]]]})
        code, out = self.run_pq("plan")
        self.assertIn("GitHub, once either merges: conflicting with #342 (CHANGELOG only: packages/a/CHANGELOG.md)",
                      out)
        # As predicted: once the maintainer merges #341, GitHub reads #342 conflicting in that CHANGELOG.
        self.sim.merge(self.gh, 341)
        self.run_pq("sync")
        row = self.plan()["#342"]
        self.assertEqual((row["action"], row["github"]), ("keep", {"main": ["packages/a/CHANGELOG.md"], "pairs": []}))

    def test_queued_github_changelog_conflict_advances_only_by_name(self):
        tip = self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        self.upstream_entry(1, "M1", "Fixed upstream")
        row = self.plan()["q"]
        self.assertEqual((row["action"], row["reasons"], row["note"]), ("open", [], ""))
        self.assertEqual(row["github"]["main"], ["packages/a/CHANGELOG.md"])
        code, out = self.run_pq("plan")
        self.assertIn("`pr-queue advance q` rebases it before opening", out)
        code, out = self.run_pq("advance")
        self.assertIn("q: already on origin/main's line and merges alone; nothing to do", out)
        self.assertEqual(self.fork_tip("octo-fork/q"), tip)
        code, out = self.run_pq("advance", "q")
        self.assertEqual(code, 0, out)
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/q^").stdout.strip(),
                         sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip())
        self.assertEqual(self.plan()["q"]["github"]["main"], [])

    def test_advance_after_a_conflict_keeps_an_entry_reworded_in_the_resolution(self):
        # inflight-epoch (2026-10-16): resolving the stopped rebase, the agent reworded our entry; the
        # rerun's rebuild took the new wording for a union leftover (absent from the pre-rebase tip)
        # and dropped it, leaving the branch with no CHANGELOG line.
        self.sim.branch("octo-fork/r", line=9, text="R9", entry="Fixed r")
        self.gh.add_pr(321, "octo-fork/r", "fix(a): r", rank="P1")
        self.sim.upstream_change(9, "M9 from upstream", pkg="a")
        self.run_pq("sync")
        code, out = self.run_pq("advance", "#321")
        self.assertEqual(code, 1, out)
        wt = os.path.join(PQ.WORKTREES, "r")
        resolved = sh(wt, "git", "show", "origin/main:packages/a/src/x.txt").stdout.split("\n")
        resolved[8] = "R9 over M9"
        self.sim.write(wt, "packages/a/src/x.txt", "\n".join(resolved))
        path = "packages/a/CHANGELOG.md"
        self.sim.write(wt, path, self.sim.read(wt, path).replace("- Fixed r\n", "- Fixed r, now narrowed\n"))
        sh(wt, "git", "add", "-A")
        sh(wt, "git", "rebase", "--continue", env={"GIT_EDITOR": ":"})
        code, out = self.run_pq("advance", "#321")
        self.assertEqual(code, 0, out)
        log = self.sim.show("fork/octo-fork/r", path)
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        self.assertIn("- Fixed r, now narrowed\n", unreleased, log)
        self.assertNotIn("- Fixed r\n", log, "the wording the resolution replaced stays gone")

    def test_advance_rebuilds_changelogs_from_the_branch_before_the_rebase(self):
        # main's own [Unreleased] line, sitting next to ours when the branch is cut
        self.sim.maint_sync()
        self.sim.add_entry(self.sim.maint, "a", "Upstream fix")
        sh(self.sim.maint, "git", "commit", "-q", "-am", "fix: upstream")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        sh(self.sim.work, "git", "fetch", "-q", "origin")
        self.sim.branch("octo-fork/u", line=6, text="U6", entry="Fixed u")
        self.gh.add_pr(331, "octo-fork/u", "fix(a): u", rank="P1")
        # The link commit `open` adds rewrites our entry in place.
        path = "packages/a/CHANGELOG.md"
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/u")
        self.sim.write(self.sim.work, path, self.sim.read(self.sim.work, path).replace("- Fixed u\n", "- Fixed u (#331)\n"))
        sh(self.sim.work, "git", "commit", "-q", "-am", "docs(changelog): link #331")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "fork", "octo-fork/u")
        # A release rewords that line and leaves other sections in [Unreleased].
        self.sim.release()
        text = self.sim.read(self.sim.maint, path).replace("- Upstream fix\n", "- Upstream fix, reworded\n")
        text = text.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Removed\n\n- Dropped a flag\n", 1)
        self.sim.write(self.sim.maint, path, text)
        sh(self.sim.maint, "git", "commit", "-q", "-am", "chore: reword")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        self.run_pq("sync")
        code, out = self.run_pq("advance", "#331")
        self.assertEqual(code, 0, out)
        log = self.sim.show("fork/octo-fork/u", path)
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        self.assertNotIn("- Upstream fix\n", log, "main's old wording is not ours to keep")
        self.assertIn("### Fixed\n\n- Fixed u (#331)", unreleased, log)
        self.assertEqual(log.count("- Fixed u"), 1, "only the linked wording survives the replay:\n" + log)

    def test_advance_never_restores_a_main_line_main_deleted_after_the_branch_merged_it(self):
        # #14759 (2026-10-15): the branch merged main with "Files the write tool creates…" in it; main
        # later dropped that line, and merging main again union-kept it beside our adjacent entry.
        # The line came from main, so the rebuild must not put it back.
        path = "packages/a/CHANGELOG.md"
        self.sim.branch("octo-fork/w", line=6, text="W6")
        self.sim.maint_sync()
        self.sim.add_entry(self.sim.maint, "a", "Upstream line main later deletes")
        sh(self.sim.maint, "git", "commit", "-q", "-am", "feat: upstream line")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        self.merge_main_into("octo-fork/w")
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/w")  # our next entry lands right below main's line
        self.sim.write(self.sim.work, path, self.sim.read(self.sim.work, path).replace(
            "- Upstream line main later deletes\n", "- Upstream line main later deletes\n- Fixed w\n"))
        sh(self.sim.work, "git", "commit", "-q", "-am", "fix(a): w")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        self.sim.maint_sync()
        self.sim.write(self.sim.maint, path, self.sim.read(self.sim.maint, path).replace(
            "- Upstream line main later deletes\n", ""))
        sh(self.sim.maint, "git", "commit", "-q", "-am", "chore: rewrite changelog")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        self.merge_main_into("octo-fork/w")
        self.assertIn("- Upstream line main later deletes", self.sim.show("fork/octo-fork/w", path),
                      "the union merge kept main's deleted line beside ours")
        self.gh.add_pr(361, "octo-fork/w", "fix(a): w", rank="P1")
        self.sim.upstream_change(1, "unrelated")
        self.run_pq("sync")
        code, out = self.run_pq("advance", "#361")
        self.assertEqual(code, 0, out)
        log = self.sim.show("fork/octo-fork/w", path)
        self.assertNotIn("Upstream line main later deletes", log, out)
        self.assertIn("- Fixed w", log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0], log)

    def test_advance_no_push_carries_unpushed_fix_commits_and_their_changelog_lines(self):
        self.sim.branch("octo-fork/f", line=6, text="F6", entry="Fixed f")
        self.gh.add_pr(351, "octo-fork/f", "fix(a): f", rank="P1")
        fork_tip = sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/f").stdout.strip()
        wt = os.path.join(PQ.WORKTREES, "f")
        sh(self.sim.work, "git", "worktree", "add", "-q", wt, "octo-fork/f")
        self.sim.change(wt, 7, "F7", "fix(a): f again", entry="Fixed f again")
        self.sim.release()
        self.run_pq("sync")
        code, out = self.run_pq("advance", "#351")
        self.assertEqual(code, 1, "advance that pushes still refuses commits the fork lacks")
        self.assertIn("--no-push", out)
        code, out = self.run_pq("advance", "#351", "--no-push")
        self.assertEqual(code, 0, out)
        self.assertEqual(sh(wt, "git", "rev-parse", "fork/octo-fork/f").stdout.strip(), fork_tip, "nothing pushed")
        self.assertEqual(sh(wt, "git", "rev-list", "--count", "origin/main..HEAD").stdout.strip(), "2", out)
        log = self.sim.read(wt, "packages/a/CHANGELOG.md")
        unreleased = log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        self.assertIn("- Fixed f again", unreleased, log)
        self.assertIn("- Fixed f\n", unreleased, log)

    def test_advance_after_a_local_rebase_keeps_mains_rewording_of_lines_it_did_not_touch(self):
        # 2026-10-29: the worktrees sat on main 6693ddbfd58 after `advance --no-push`, the fork on an
        # older main. Main's 2407a34d11 then reworded [Unreleased] lines it added in between, and the
        # pushing `advance` judged the rebuild against the fork's tip and base: the union replay's old
        # wordings, absent from both, came back as ours (~20 coding-agent lines).
        path = "packages/a/CHANGELOG.md"
        self.sim.branch("octo-fork/e", line=6, text="E6", entry="Fixed e")
        self.gh.add_pr(371, "octo-fork/e", "fix(a): e", rank="P1")
        self.sim.maint_sync()
        self.sim.add_entry(self.sim.maint, "a", "Upstream fix main adds while the PR is open")
        sh(self.sim.maint, "git", "commit", "-q", "-am", "fix: upstream")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        self.run_pq("sync")
        code, out = self.run_pq("advance", "#371", "--no-push")
        self.assertEqual(code, 0, out)
        wt = os.path.join(PQ.WORKTREES, "e")
        self.assertNotEqual(sh(wt, "git", "rev-parse", "HEAD").stdout.strip(), self.fork_tip("octo-fork/e"), out)
        self.sim.maint_sync()  # main's changelog rewrite rewords the line our branch never touched
        self.sim.write(self.sim.maint, path, self.sim.read(self.sim.maint, path).replace(
            "- Upstream fix main adds while the PR is open\n", "- Upstream fix, reworded\n"))
        sh(self.sim.maint, "git", "commit", "-q", "-am", "chore: rewrite changelog")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        self.run_pq("sync")
        code, out = self.run_pq("advance", "#371")
        self.assertEqual(code, 0, out)
        main_log = self.sim.show("origin/main", path)
        expected = main_log.replace("- Upstream fix, reworded\n", "- Upstream fix, reworded\n- Fixed e\n")
        self.assertEqual(self.sim.show("fork/octo-fork/e", path), expected, out)

    def test_advance_replays_only_own_commits_of_a_branch_that_merged_main(self):
        self.sim.branch("octo-fork/m", line=6, text="M6", entry="Fixed m")
        self.gh.add_pr(341, "octo-fork/m", "fix(a): m", rank="P1")
        self.sim.upstream_change(1, "first upstream edit", pkg="b")
        sh(self.sim.work, "git", "fetch", "-q", "origin")
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/m")
        sh(self.sim.work, "git", "merge", "-q", "--no-edit", "origin/main")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "fork", "octo-fork/m")
        # main rewrites the line its merged-in commit touched, then releases (CHANGELOG drift)
        self.sim.upstream_change(1, "second upstream edit", pkg="b")
        self.sim.release()
        self.run_pq("sync")
        code, out = self.run_pq("advance", "#341")
        self.assertEqual(code, 0, out)
        own = sh(self.sim.work, "git", "rev-list", "origin/main..fork/octo-fork/m").stdout.split()
        self.assertEqual(len(own), 1, out)
        self.assertEqual(self.sim.show("fork/octo-fork/m", "packages/b/src/y.txt").split("\n")[0], "second upstream edit")

    def merge_main_into(self, branch):
        sh(self.sim.work, "git", "fetch", "-q", "origin")
        sh(self.sim.work, "git", "checkout", "-q", branch)
        sh(self.sim.work, "git", "merge", "-q", "--no-edit", "origin/main")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "fork", branch)

    def test_advance_never_replays_a_rerere_resolution_for_its_conflict(self):
        # rerere, on in this checkout, would replay the resolution it recorded for this conflict by itself.
        # pr-queue rebuilds CHANGELOGs itself, so advance must stop on the conflict instead.
        sh(self.sim.work, "git", "config", "rerere.enabled", "true")
        self.sim.branch("octo-fork/rr", line=9, text="R9", entry="Fixed rr")
        self.run_pq("add", "octo-fork/rr", "--title", "fix(a): rr", "--body", self.body)
        self.sim.upstream_change(9, "M9", pkg="a")
        sh(self.sim.work, "git", "fetch", "-q", "origin")
        branch_tip = sh(self.sim.work, "git", "rev-parse", "octo-fork/rr").stdout.strip()
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/rr")
        self.assertNotEqual(sh(self.sim.work, "git", "rebase", "origin/main", check=False).returncode, 0)
        resolved = sh(self.sim.work, "git", "show", "origin/main:packages/a/src/x.txt").stdout.split("\n")
        resolved[8] = "R9 over M9"
        self.sim.write(self.sim.work, "packages/a/src/x.txt", "\n".join(resolved))
        sh(self.sim.work, "git", "add", "-A")
        sh(self.sim.work, "git", "rebase", "--continue", env={"GIT_EDITOR": ":"})
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "branch", "-f", "octo-fork/rr", branch_tip)
        code, out = self.run_pq("advance", "rr")
        self.assertEqual(code, 1, out)
        self.assertIn("rr: CONFLICT replaying its own commits onto origin/main", out)
        wt = os.path.join(PQ.WORKTREES, "rr")
        self.assertIn("<<<<<<<", self.sim.read(wt, "packages/a/src/x.txt"))
        self.assertNotIn("R9 over M9", self.sim.read(wt, "packages/a/src/x.txt"))

    def test_a_failed_push_stops_only_its_entry_and_the_next_still_advances(self):
        self.sim.branch("octo-fork/a1", line=2, text="A2", entry="Fixed a1")
        self.sim.branch("octo-fork/a2", line=5, text="A5", entry="Fixed a2")
        self.run_pq("add", "octo-fork/a1", "--title", "fix(a): a1", "--body", self.body)
        self.run_pq("add", "octo-fork/a2", "--title", "fix(a): a2", "--body", self.body)
        self.sim.release()  # the CHANGELOG lines move under 1.1.0: both entries rebase
        self.run_pq("sync")
        old_base = self.manifest()["a1"]["base"]
        real_push = PQ.push

        def refused(repo, branch, old):
            if branch == "octo-fork/a1":
                raise PQ.GitError("the fork refused the push")
            return real_push(repo, branch, old)

        with mock.patch.object(PQ, "push", refused):
            code, out = self.run_pq("advance")
        main = sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip()
        self.assertEqual(code, 1, out)
        self.assertIn("a1: the fork refused the push", out)
        self.assertIn("a2: 1 own commit(s) rebased onto origin/main", out)
        manifest = self.manifest()
        self.assertEqual(manifest["a2"]["base"], main, "a2 pushed, so its base is recorded")
        self.assertEqual(manifest["a1"]["base"], old_base, "a1 did not push, so its base stays")

    def test_bases_of_entries_already_advanced_are_stored_when_a_later_step_raises(self):
        self.sim.branch("octo-fork/b1", line=2, text="B2", entry="Fixed b1")
        self.sim.branch("octo-fork/b2", line=5, text="B5", entry="Fixed b2")
        self.run_pq("add", "octo-fork/b1", "--title", "fix(a): b1", "--body", self.body)
        self.run_pq("add", "octo-fork/b2", "--title", "fix(a): b2", "--body", self.body)
        self.sim.release()
        self.run_pq("sync")
        main = sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip()
        real_quiet = PQ.quiet_replayed

        def crash(wt, upstream, kept):
            if os.path.basename(wt) == "b2":
                raise RuntimeError("disk full")
            return real_quiet(wt, upstream, kept)

        with mock.patch.object(PQ, "quiet_replayed", crash), self.assertRaises(RuntimeError):
            self.run_pq("advance")
        self.assertEqual(self.manifest()["b1"]["base"], main, "b1 was pushed before b2 raised: its base is kept")

    def test_advance_pushes_a_newer_local_tip_of_a_branch_already_on_mains_line(self):
        self.sim.branch("octo-fork/n", line=6, text="N6", entry="Fixed n")
        self.run_pq("add", "octo-fork/n", "--title", "fix(a): n", "--body", self.body)
        fork_before = sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/n").stdout.strip()
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/n")
        local = self.sim.change(self.sim.work, 7, "N7", "fix(a): n again #77", entry="Fixed n again")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        self.assertNotEqual(fork_before, local)
        code, out = self.run_pq("advance", "n", "--no-push")
        self.assertEqual(code, 0, out)
        self.assertIn("rebased onto origin/main", out)
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/n").stdout.strip(), fork_before)
        self.sim.upstream_change(1, "unrelated")
        code, out = self.run_pq("advance", "n")
        self.assertEqual(code, 0, out)
        self.assertIn("pushed to fork", out)
        self.assertEqual(self.sim.show("fork/octo-fork/n", "packages/a/src/x.txt").split("\n")[6], "N7")
        message = sh(self.sim.work, "git", "log", "-1", "--format=%B", "fork/octo-fork/n").stdout
        self.assertIn("fix(a): n again PR 77", message)
        self.assertNotIn("#77", message)
        log = self.sim.show("fork/octo-fork/n", "packages/a/CHANGELOG.md")
        self.assertIn("- Fixed n again", log.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0])

    def test_advance_noop_with_a_newer_local_tip_still_refuses_a_dirty_worktree(self):
        self.sim.branch("octo-fork/dirty", line=6, text="D6")
        self.run_pq("add", "octo-fork/dirty", "--title", "fix(a): dirty")
        fork_tip = sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/dirty").stdout.strip()
        wt = PQ.ensure_worktree(self.sim.work, "octo-fork/dirty")
        self.sim.change(wt, 7, "D7", "fix(a): dirty again")
        self.sim.edit(wt, "packages/a/src/x.txt", 8, "uncommitted")
        code, out = self.run_pq("advance", "dirty")
        self.assertEqual(code, 1, out)
        self.assertIn("has uncommitted changes", out)
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/dirty").stdout.strip(), fork_tip)

    def test_fold_and_quiet_git_errors_do_not_stop_unrelated_entries(self):
        for ident, line in (("fold", 2), ("quiet", 5), ("ok", 8)):
            self.sim.branch(f"octo-fork/{ident}", line=line, text=ident, entry=f"Fixed {ident}")
            code, out = self.run_pq("add", f"octo-fork/{ident}", "--title", f"fix(a): {ident}")
            self.assertEqual(code, 0, out)
        old_bases = {ident: entry["base"] for ident, entry in self.manifest().items()}
        self.sim.release()
        self.run_pq("sync")
        real_fold, real_quiet = PQ.fold_changelogs, PQ.quiet_replayed

        def fold(wt, tips, bases):
            if os.path.basename(wt) == "fold":
                raise PQ.GitError("fold failed")
            return real_fold(wt, tips, bases)

        def quiet(wt, upstream, kept):
            if os.path.basename(wt) == "quiet":
                raise PQ.GitError("quiet failed")
            return real_quiet(wt, upstream, kept)

        with mock.patch.object(PQ, "fold_changelogs", fold), mock.patch.object(PQ, "quiet_replayed", quiet):
            code, out = self.run_pq("advance")
        self.assertEqual(code, 1, out)
        self.assertIn("fold: fold failed", out)
        self.assertIn("quiet: quiet failed", out)
        self.assertIn("ok: 1 own commit(s) rebased onto origin/main", out)
        manifest = self.manifest()
        for ident in ("fold", "quiet"):
            self.assertEqual(manifest[ident]["base"], old_bases[ident])
        main = sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip()
        self.assertEqual(manifest["ok"]["base"], main)

    def test_failed_changelog_autosquash_does_not_push_or_record_a_base(self):
        fork_tip = self.sim.branch("octo-fork/squash", line=6, text="S6", entry="Fixed squash")
        self.run_pq("add", "octo-fork/squash", "--title", "fix(a): squash")
        old_base = self.manifest()["squash"]["base"]
        self.sim.release()
        self.run_pq("sync")
        real_git = PQ.git

        def fail_autosquash(repo, *args, **kwargs):
            if "--autosquash" in args:
                return subprocess.CompletedProcess(args, 1, "", "autosquash failed")
            return real_git(repo, *args, **kwargs)

        with mock.patch.object(PQ, "git", fail_autosquash), mock.patch.object(PQ, "push") as push:
            code, out = self.run_pq("advance", "squash")
        self.assertEqual(code, 1, out)
        self.assertIn("CHANGELOG fixup commits left unsquashed", out)
        self.assertIn("autosquash failed", out)
        push.assert_not_called()
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/octo-fork/squash").stdout.strip(), fork_tip)
        self.assertEqual(self.manifest()["squash"]["base"], old_base)

    def test_a_queued_branch_that_merged_main_lands_and_advances_its_own_commits(self):
        # 2026-10-14: five broker entries had merged main past their base; plan counted main's own later
        # edits as their conflicts with main, and advance would have replayed main's commits.
        self.sim.branch("octo-fork/m", line=6, text="M6", entry="Fixed m")
        self.run_pq("add", "octo-fork/m", "--title", "fix(a): m", "--body", self.body)
        self.sim.upstream_change(1, "first upstream edit", pkg="b")
        self.merge_main_into("octo-fork/m")
        self.sim.upstream_change(1, "second upstream edit", pkg="b")
        row = self.plan()["m"]
        self.assertEqual((row["action"], row["reasons"]), ("open", []), row)
        code, out = self.run_pq("sync")
        self.assertIn("warning: m: 1 merge commit(s) between its base", out)
        code, out = self.run_pq("advance")
        self.assertEqual(code, 0, out)
        self.assertNotIn("nothing to do", out, "a branch carrying merges is replayed linear")
        self.assertEqual(sh(self.sim.work, "git", "rev-list", "--merges", "origin/main..fork/octo-fork/m").stdout, "")
        self.assertEqual(len(sh(self.sim.work, "git", "rev-list", "origin/main..fork/octo-fork/m").stdout.split()), 1)
        self.assertEqual(self.sim.show("fork/octo-fork/m", "packages/b/src/y.txt").split("\n")[0], "second upstream edit")

    def test_add_and_set_base_warn_on_merges_since_base(self):
        base = sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip()
        self.sim.branch("octo-fork/n", line=6, text="N6")
        self.sim.upstream_change(1, "upstream edit", pkg="b")
        self.merge_main_into("octo-fork/n")
        code, out = self.run_pq("add", "octo-fork/n", "--title", "fix(a): n", "--base", base)
        self.assertEqual(code, 0, out)
        self.assertIn("warning: n: 1 merge commit(s) between its base", out)
        self.assertIn("take only its 1 non-merge commit(s)", out)
        code, out = self.run_pq("set", "n", "--base", base)
        self.assertIn("warning: n: 1 merge commit(s) between its base", out)

    def test_advance_off_mains_line_replays_only_own_commits_after_a_merge_of_main(self):
        self.open_parent_and_queue_child()  # c's base is #101's tip
        self.sim.upstream_change(1, "first upstream edit", pkg="b")
        self.merge_main_into("octo-fork/c")
        # The maintainer rebases #101 and folds a fixup in, so c's base never reaches main.
        self.sim.merge(self.gh, 101, fixup=(3, "P3 fixed by the maintainer"))
        self.sim.upstream_change(1, "second upstream edit", pkg="b")
        self.run_pq("sync")
        row = self.plan()["c"]
        self.assertEqual((row["action"], row["reasons"], row["note"]), ("open", [], "advance first"), row)
        code, out = self.run_pq("advance")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(sh(self.sim.work, "git", "rev-list", "origin/main..fork/octo-fork/c").stdout.split()), 1, out)
        y = self.sim.show("fork/octo-fork/c", "packages/b/src/y.txt").split("\n")
        x = self.sim.show("fork/octo-fork/c", "packages/a/src/x.txt").split("\n")
        self.assertEqual((y[0], x[2], x[11]), ("second upstream edit", "P3 fixed by the maintainer", "C12"))
        log = self.sim.show("fork/octo-fork/c", "packages/a/CHANGELOG.md")
        self.assertIn("- Fixed the child", log.split("## [Unreleased]", 1)[1].split("## [1.0.0]", 1)[0], log)

    def test_audit_flags_rule_breaks(self):
        self.sim.branch("octo-fork/a", line=2, text="A2")
        self.sim.branch("octo-fork/b", start="octo-fork/a", line=2, text="B2", pkg="b")
        self.sim.branch("octo-fork/d", line=15, text="D15")
        self.sim.branch("octo-fork/e", line=15, text="E15")
        self.sim.branch("octo-fork/f", line=18, text="F18", pkg="b")
        self.gh.add_pr(201, "octo-fork/a", "fix(a): a", rank="P0")
        self.gh.add_pr(202, "octo-fork/b", "fix(b): b", rank="P1",
                       body=BODY + "\n**Builds on #201**: its first commit is #201's; merge #201 first.\n")
        self.gh.add_pr(203, "octo-fork/d", "fix(a): d", rank="P1")
        self.gh.add_pr(204, "octo-fork/e", "fix(a): e", rank="P2")
        self.gh.add_pr(205, "octo-fork/f", "feat(b): f", draft=True, created=ago(10))
        manifest = os.path.join(self.dir, "queue.json")
        with open(manifest, "w") as f:
            json.dump({"version": 1, "config": {}, "entries": []}, f)
        code, out = self.run_pq("--manifest", manifest, "audit", "--json")
        self.assertEqual(code, 0, out)
        flags = {r["number"]: dict(r["flags"]) for r in json.loads(out)}
        self.assertEqual(flags[201], {})
        self.assertIn("**Builds on #201**", flags[202]["merge-order"][0])
        self.assertEqual(flags[202]["carries"], [["#201", 1]])
        self.assertEqual(flags[203]["conflicts-pr"], [["#204", ["packages/a/src/x.txt"]]])
        self.assertIn("conflicts-pr", flags[204])
        self.assertEqual(set(flags[203]), {"conflicts-pr"})
        self.assertEqual(flags[205], {"stale-draft": 10})
        self.gh.add_pr(206, "octo-fork/f", "fix(b): f elsewhere", base="dev")
        code, out = self.run_pq("--manifest", manifest, "audit", "--json")
        self.assertEqual({r["number"]: dict(r["flags"]) for r in json.loads(out)}[206]["base"], "dev")
        code, out = self.run_pq("--manifest", manifest, "plan", "--json")
        rows = {r["label"]: r for r in json.loads(out)["rows"]}
        self.assertIn("needs #201 (open)", rows["#202"]["reasons"], "a body's Builds-on counts before any sync")
        self.assertIn("targets dev, not main", rows["#206"]["reasons"])
        q = omp_queue.Queue(self.sim.work, omp_queue.empty_manifest(), self.gh)
        self.assertEqual(dict(q.carried(q.adhoc("refs/remotes/fork/octo-fork/a"))), {},
                         "precheck on an open PR's own branch is that PR, not a copy of it")
        # In the PR's worktree with a fix not pushed yet, HEAD is still that PR (matched by branch).
        wt = os.path.join(self.dir, "wt-a")
        sh(self.sim.work, "git", "worktree", "add", "-q", wt, "octo-fork/a")
        self.sim.change(wt, 4, "A4 fix", "fix(a): a round fix")
        q = omp_queue.Queue(wt, omp_queue.empty_manifest(), self.gh)
        self.assertEqual(dict(q.carried(q.adhoc("HEAD", branch="octo-fork/a"))), {},
                         "an unpushed commit does not make the branch a copy carrying its own PR")

    def test_renames_of_one_file_conflict(self):
        for name, target in (("octo-fork/u", "u.txt"), ("octo-fork/v", "v.txt")):
            sh(self.sim.work, "git", "checkout", "-q", "-b", name, "origin/main")
            sh(self.sim.work, "git", "mv", "packages/a/src/x.txt", f"packages/a/src/{target}")
            sh(self.sim.work, "git", "commit", "-q", "-m", f"refactor(a): {target}")
            sh(self.sim.work, "git", "checkout", "-q", "--detach")
            sh(self.sim.work, "git", "push", "-q", "fork", name)
            self.run_pq("add", name, "--title", f"refactor(a): {target}")
        rows = self.plan()
        self.assertEqual(sorted(r["action"] for r in rows.values()), ["open", "wait"])

    def test_merge_order_lines(self):
        ours = {15184, 15489}
        hits = ["**Builds on #15184**: its first 31 commits are #15184's.",
                "merge #15489 first, or merge this alone to land both.",
                "**Merge after #14074.** It adds the helper.",
                "- **Overlaps #12314** (another author) in `bridge.ts`.",
                "whichever lands second resolves.",
                "**Builds on #15105, #15110** (merge in that order)"]
        misses = ["Builds on #14060 by nnnnoel (co-author).", "Builds on #15275 (in `main` now).",
                  "Merged together it reads `x`.", "Supersedes #15001.", "Related: #12314."]
        for line in hits:
            self.assertEqual(omp_queue.merge_order_lines(line, ours), [line], line)
        for line in misses:
            self.assertEqual(omp_queue.merge_order_lines(line, ours), [], line)

    def test_open_refuses_then_opens_ready(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5", entry="Fixed q")
        bad = os.path.join(self.dir, "bad.md")
        with open(bad, "w") as f:
            f.write(BODY.replace("## Testing", "## Checks"))
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", bad, "--priority", "P1")
        self.gh.events = 8
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 1)
        self.assertIn("ready budget", out)
        self.gh.events = 0
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 1, out)
        self.assertIn("FIX   body       ## Testing", out)
        self.assertEqual(self.gh.prs, {}, "nothing opened when precheck fails")
        self.run_pq("set", "q", "--body", self.body)
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 0, out)
        number = self.gh.next
        self.assertEqual(self.gh.readied, [number])
        log = self.sim.show("fork/octo-fork/q", "packages/a/CHANGELOG.md")
        self.assertIn(f"- Fixed q ([#{number}](https://github.com/can1357/oh-my-pi/pull/{number}) by "
                      "[@octo-fork](https://github.com/octo-fork))", log)
        entry = self.manifest()["q"]
        self.assertEqual((entry["state"], entry["pr"]), ("open", number))
        self.assertIn("readied", entry)

    def test_a_reopen_points_the_closed_prs_changelog_link_at_the_new_number(self):
        old = ("- Fixed q ([#15503](https://github.com/can1357/oh-my-pi/pull/15503) by "
               "[@octo-fork](https://github.com/octo-fork))")
        self.sim.branch("octo-fork/q", line=5, text="Q5", entry=old.removeprefix("- "))
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        omp_queue.Store(self.sim.work).update(
            lambda m, f: next(e for e in m["entries"] if e["id"] == "q").update(closed_prs=[15503]), "closed")
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 0, out)
        number = self.gh.next
        log = self.sim.show("fork/octo-fork/q", "packages/a/CHANGELOG.md")
        self.assertIn(old.replace("15503", str(number)), log)
        self.assertNotIn("15503", log)

    def test_open_links_only_the_branchs_own_entries_not_main_ones_after_a_rebase(self):
        # #16556 (2026-10-20): rebased onto main by hand with its recorded base left behind, the link
        # step diffed from that base and credited us on maintainers' issue-only entries (#16493, #16508).
        self.sim.branch("octo-fork/q", line=5, text="Q5", entry="Fixed q")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        theirs = {"a": "Fixed z ([#16493](https://github.com/can1357/oh-my-pi/issues/16493))",
                  "b": "Added y ([#16508](https://github.com/can1357/oh-my-pi/issues/16508))"}
        self.sim.maint_sync()
        for pkg, entry in theirs.items():
            self.sim.change(self.sim.maint, 3, f"M{pkg}", f"fix({pkg}): theirs", pkg, entry)
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        sh(self.sim.work, "git", "fetch", "-q", "origin")
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/q")
        sh(self.sim.work, "git", "rebase", "-q", "origin/main")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "-f", "fork", "octo-fork/q")
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 0, out)
        self.assertIn("linked 1 CHANGELOG entry", out)
        number = self.gh.next
        log = self.sim.show("fork/octo-fork/q", "packages/a/CHANGELOG.md")
        self.assertIn(f"- Fixed q ([#{number}](https://github.com/can1357/oh-my-pi/pull/{number}) by ", log)
        self.assertIn(f"- {theirs['a']}\n", log + "\n", "a maintainer's issue-only entry stays as it was")
        self.assertEqual(self.sim.show("fork/octo-fork/q", "packages/b/CHANGELOG.md"),
                         self.sim.show("origin/main", "packages/b/CHANGELOG.md"), "another package's CHANGELOG untouched")

    def test_set_branch_records_a_restacked_branch_as_pushed_and_keeps_the_old_one(self):
        old_tip = self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        self.sim.branch("octo-fork/c", start="octo-fork/q", line=12, text="C12")
        self.run_pq("add", "octo-fork/c", "--title", "fix(a): c", "--needs", "q", "--body", self.body)
        new_tip = self.sim.branch("octo-fork/r2/q", line=6, text="Q6")
        wt = os.path.join(self.dir, "wt-r2-q")
        sh(self.sim.work, "git", "worktree", "add", "-q", wt, "octo-fork/r2/q")
        code, out = self.run_pq("set", "q", "--branch", "octo-fork/r2/q", "--keep-old")
        self.assertNotEqual(code, 0, "a restacked branch needs its new base")
        self.assertIn("pass --base", out)
        main = sh(self.sim.work, "git", "rev-parse", "origin/main").stdout.strip()
        code, out = self.run_pq("set", "q", "--branch", "octo-fork/r2/q", "--keep-old", "--base", main)
        self.assertEqual(code, 0, out)
        sh(self.sim.work, "git", "fetch", "-q", "fork")

        def rev(ref):
            return sh(self.sim.work, "git", "rev-parse", ref).stdout.strip()
        self.assertEqual((rev("fork/octo-fork/r2/q"), rev("fork/octo-fork/q")), (new_tip, old_tip), "both branches as pushed")
        entries = self.manifest()
        entry = entries["r2/q"]
        self.assertEqual((entry["branch"], entry["base"], entry["body"], os.path.realpath(entry["worktree"])),
                         ("octo-fork/r2/q", main, "bodies/r2/q.md", os.path.realpath(wt)))
        self.assertEqual(entries["c"]["needs"], ["r2/q"])

    def test_open_refuses_a_conflict_with_an_open_ready_pr(self):
        self.sim.branch("octo-fork/r", line=9, text="R9")
        self.gh.add_pr(301, "octo-fork/r", "fix(a): r", rank="P0")
        self.sim.branch("octo-fork/q", line=9, text="Q9")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 1)
        self.assertIn("conflicts with open ready #301 in packages/a/src/x.txt", out)

    def old_p2_and_p1(self, days=5, priority="P1"):
        """Open P2 #401 (line 7), open `days` days, and queued `q` at `priority` on the same line."""
        self.sim.branch("octo-fork/old", line=7, text="O7")
        self.gh.add_pr(401, "octo-fork/old", "fix(a): old", rank="P2", created=ago(days))
        self.run_pq("sync")
        self.sim.branch("octo-fork/q", line=7, text="Q7", entry="Fixed q")
        code, out = self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body, "--priority", priority)
        self.assertEqual(code, 0, out)

    def sibling_lines(self, ref, number=None):
        out = io.StringIO()
        with mock.patch.object(PC, "GitHub", lambda: self.gh), contextlib.redirect_stdout(out):
            PC.check_siblings(ref, number, self.sim.work)
        return [line for line in out.getvalue().splitlines() if " sibling " in line]

    def test_a_p1_opens_over_an_old_p2_it_only_conflicts_with(self):
        # Open-PR rule 3: merge waves take P0 and P1 first, so a P1 held behind an
        # old P2 misses them. browser-read-after-navigation waited on #15508 (P2, open 11 days).
        self.old_p2_and_p1()
        row = self.plan()["q"]
        self.assertEqual((row["action"], row["over"], row["reasons"], row["blocked_by"]), ("open", ["#401"], [], []))
        self.assertEqual(row["build_with"][0]["excluded"], "it conflicts with this one in packages/a/src/x.txt: "
                                                           "whichever merges second rebases onto main")
        self.assertIn("  open (over P2 #401) q ", self.run_pq("plan")[1])
        self.assertEqual(self.sibling_lines("fork/octo-fork/q"),
                         ["NOTE  sibling    #401  code conflict in packages/a/src/x.txt: #401 is P2, open 5d: plan "
                          "opens this over it unless another queued opening conflicts with it, and the one that "
                          "merges second rebases onto main"])
        code, out = self.run_pq("open", "q")
        self.assertEqual(code, 0, out)
        number = self.gh.next
        self.assertIn(f"#{number} opens over P2 #401: marked to rebase onto main once #{number} merges", out)
        self.assertEqual(self.gh.readied, [number])
        self.assertEqual(self.manifest()["old"]["rebases_after"], [number])
        plan = self.plan()
        self.assertEqual((plan["#401"]["action"], plan["#401"]["note"]), ("keep", f"rebases after #{number} merges"))
        self.assertEqual((plan[f"#{number}"]["action"], plan[f"#{number}"]["note"]), ("keep", "opened over P2 #401"))
        self.assertNotIn("conflicts with", self.run_pq("audit")[1])
        self.assertEqual(self.sibling_lines("fork/octo-fork/old", 401),
                         [f"NOTE  sibling    #{number}  code conflict in packages/a/src/x.txt: #{number} opened over "
                          f"this P2: this one rebases onto main once #{number} merges"])
        self.sim.merge(self.gh, number)
        self.run_pq("sync")
        row = self.plan()["#401"]
        self.assertEqual((row["action"], row["reasons"]), ("rebase", ["conflicts with main in packages/a/src/x.txt"]))

    def test_the_round_tree_never_merges_an_opening_with_the_p2_it_opens_over(self):
        # A third opening sharing packages/a with both sides pulled #401 and q into one tree, whose
        # merge stops on the very conflict the rule accepts (review of the 2026-10-23 change).
        self.old_p2_and_p1()
        self.sim.branch("octo-fork/ind", line=18, text="I18", entry="Fixed ind")
        self.run_pq("add", "octo-fork/ind", "--title", "fix(a): ind", "--body", self.body, "--priority", "P1")
        plan = self.plan()
        self.assertEqual((plan["q"]["over"], plan["ind"]["action"]), (["#401"], "open"))
        code, out = self.run_pq("tree")
        self.assertEqual(code, 0, out)
        trees = out.split("\n\n")
        self.assertTrue(trees[0].startswith("merged tree 1 of 2: "), out)
        self.assertTrue(trees[1].startswith("merged tree 2 of 2: "), out)
        for tree in trees[:2]:
            self.assertFalse(" q\n" in tree and " #401\n" in tree, tree)
        self.assertIn("build and record each", out)

    def test_a_p1_waits_on_a_young_p2_or_any_other_blocker(self):
        self.old_p2_and_p1(days=2)
        row = self.plan()["q"]
        self.assertEqual((row["action"], row["over"], row["blocked_by"]), ("wait", [], ["#401"]))
        self.assertEqual([line[:4] for line in self.sibling_lines("fork/octo-fork/q")], ["FIX "])
        view = self.sim.show("fork/omp-queue", "QUEUE.md")
        self.assertIn("## Conflict-held (1)", view)
        self.assertIn("| [#401](https://github.com/can1357/oh-my-pi/pull/401) |", view)
        self.gh.prs[401]["created"] = ago(5)
        self.assertEqual(self.plan()["q"]["action"], "open")
        # precheck accepts the conflict only while nothing else would hold it: a hold makes it a FIX again.
        self.run_pq("set", "q", "--hold", "me, 2026-10-23: later")
        self.assertEqual([line[:4] for line in self.sibling_lines("fork/octo-fork/q")], ["FIX "])
        self.run_pq("set", "q", "--unhold")
        # A P1 blocker beside the old P2 keeps both conflicts reasons to wait.
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/q")
        self.sim.change(self.sim.work, 15, "Q15", "fix(a): q, line 15 too")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "-f", "fork", "octo-fork/q")
        self.sim.branch("octo-fork/hot", line=15, text="H15")
        self.gh.add_pr(402, "octo-fork/hot", "fix(a): hot", rank="P1", created=ago(5))
        row = self.plan()["q"]
        self.assertEqual((row["action"], row["over"], sorted(row["blocked_by"])), ("wait", [], ["#401", "#402"]))
        self.assertIn("conflicts with #401 in packages/a/src/x.txt", row["reasons"])

    def test_a_p1_waits_on_an_old_p2_when_it_also_conflicts_with_main_or_is_not_p0_p1(self):
        self.old_p2_and_p1(priority="P2")
        self.assertEqual(self.plan()["q"]["action"], "wait", "a P2 never opens over a P2")
        self.run_pq("set", "q", "--priority", "P1")
        self.assertEqual(self.plan()["q"]["action"], "open")
        self.sim.upstream_change(6, "M6 next to both", pkg="a")
        row = self.plan()["q"]
        self.assertEqual((row["action"], row["over"]), ("wait", []))
        self.assertEqual(row["reasons"], ["conflicts with #401 in packages/a/src/x.txt",
                                          "conflicts with main in packages/a/src/x.txt"])

    def test_every_write_renders_queue_md_in_the_same_commit(self):
        self.old_p2_and_p1()
        files = sh(self.sim.work, "git", "show", "--name-only", "--format=", "fork/omp-queue").stdout.split()
        self.assertEqual(sorted(files), ["QUEUE.md", "bodies/q.md", "queue.json"], "add wrote all three at once")
        view = self.sim.show("fork/omp-queue", "QUEUE.md")
        self.assertIn("no `pr-queue plan` cached yet", view)
        self.assertIn("## Queued since the last plan (1)", view)
        self.sim.branch("octo-fork/c", start="octo-fork/q", line=12, text="C12")
        self.run_pq("add", "octo-fork/c", "--title", "fix(a): c", "--needs", "q", "--priority", "P1")
        self.sim.branch("octo-fork/d", line=1, text="D1", pkg="b")
        self.gh.add_pr(403, "octo-fork/d", "fix(b): d", draft=True, created=ago(10))
        self.run_pq("sync")
        self.plan()
        head = sh(self.sim.work, "git", "rev-parse", "fork/omp-queue").stdout.strip()
        self.plan()
        self.assertEqual(sh(self.sim.work, "git", "rev-parse", "fork/omp-queue").stdout.strip(), head,
                         "an unchanged plan under an hour old writes nothing")
        view = self.sim.show("fork/omp-queue", "QUEUE.md")
        lines = view.splitlines()
        self.assertEqual(lines[0], "# Our oh-my-pi PR queue")
        self.assertIn("**Opening:** not paused", view)
        self.assertIn("**Ready budget:** 0 of 8 ready events used", view)
        self.assertIn("**Counts:** openable now 1, conflict-held 0, stacked 1, held 0, open PRs 2;", view)
        order = [line for line in lines if line.startswith("## ")]
        self.assertEqual(order, ["## Openable now (1)", "## Conflict-held (0)", "## Stacked (1)", "## Held (0)",
                                 "## Open PRs (2)"])
        q = next(line for line in lines if line.startswith("| q |"))
        self.assertIn("| q | fix(a): q | other | P1 | 0h | open (over P2 #401) |", q)
        self.assertIn("[compare](https://github.com/can1357/oh-my-pi/compare/main...octo-fork:oh-my-pi:octo-fork/q)", q)
        self.assertIn("| c | fix(a): c |", view)
        old = next(line for line in lines if line.startswith("| [#401]"))
        self.assertIn("| old | fix(a): old |", old)
        self.assertIn("| P2 | 5d | keep |", old)
        draft = next(line for line in lines if line.startswith("| [#403]"))
        self.assertIn("| 10d | draft |", draft, "a draft's age is since GitHub opened it, not since its import")
        self.assertNotIn("I fixed the thing users hit", view, "no stored body")
        self.assertNotIn(self.dir, view, "no host paths")
        self.run_pq("pause", "me, 2026-10-23: test")
        self.assertIn("**Opening:** paused (me, 2026-10-23: test)", self.sim.show("fork/omp-queue", "QUEUE.md"))

    def test_a_cached_plan_is_rewritten_when_it_changed_or_is_an_hour_old(self):
        view = PQ.omp_queue_view
        prev = {"at": "2026-10-23T10:00:00Z", "budget": {"used": 0}, "rows": [{"id": "q"}], "drafts": []}
        self.assertFalse(view.plan_due(prev, {**prev, "at": "2026-10-23T10:59:00Z"}))
        self.assertTrue(view.plan_due(prev, {**prev, "at": "2026-10-23T11:00:00Z"}))
        self.assertTrue(view.plan_due(prev, {**prev, "at": "2026-10-23T10:01:00Z", "rows": []}))
        self.assertTrue(view.plan_due(None, prev))
        # Two plans started in one second still order, so a slow one never overwrites a later one.
        earlier, later = view.plan_stamp(), view.plan_stamp()
        self.assertTrue(view.started_no_earlier({"at": later}, {"at": earlier}))
        self.assertFalse(view.started_no_earlier({"at": earlier}, {"at": later}))
        self.assertTrue(view.started_no_earlier({"at": earlier}, {"at": "2026-10-23T10:00:00Z"}))

    def test_compare_links_quote_the_branch(self):
        self.assertEqual(PQ.omp_queue_view.compare_link("octo-fork/fix#edge|x"),
                         "[compare](https://github.com/can1357/oh-my-pi/compare/main...octo-fork:oh-my-pi:"
                         "octo-fork/fix%23edge%7Cx)")

    def test_requeue_drops_the_rebases_after_marks_of_the_closed_pr(self):
        entry = PQ.finish_requeue({"id": "old", "state": "open", "pr": 401, "requeue": 401, "rebases_after": [902]})
        self.assertEqual((entry["state"], entry["pr"], "rebases_after" in entry), ("queued", None, False))

    def test_open_refuses_what_plan_holds_back_and_while_another_open_runs(self):
        self.sim.branch("octo-fork/s1", line=7, text="S1")
        self.sim.branch("octo-fork/s2", line=7, text="S2")
        self.run_pq("add", "octo-fork/s1", "--title", "fix(a): s1", "--priority", "P0", "--body", self.body)
        self.run_pq("add", "octo-fork/s2", "--title", "fix(a): s2", "--priority", "P2", "--body", self.body)
        code, out = self.run_pq("open", "s2")
        self.assertEqual(code, 1)
        self.assertIn("plan marks it wait: conflicts with s1", out)
        store = omp_queue.Store(self.sim.work)
        store.update(lambda m, f: m.update(opening={"id": "s2", "host": "other", "at": omp_queue.stamp()}), "t")
        code, out = self.run_pq("open", "s1")
        self.assertEqual(code, 1)
        self.assertIn("another open is in progress: s2 on other", out)
        self.assertEqual(self.gh.prs, {})

    def test_open_refuses_when_an_open_pr_cannot_be_compared(self):
        self.sim.branch("octo-fork/r", line=9, text="R9")
        self.gh.add_pr(301, "octo-fork/r", "fix(a): r", rank="P0")
        self.sim.branch("octo-fork/q", line=12, text="Q12")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        sh(self.sim.work, "git", "update-ref", "-d", "refs/remotes/fork/octo-fork/r")
        sh(self.sim.work, "git", "branch", "-q", "-D", "octo-fork/r")
        code, out = self.run_pq("open", "q", "--no-fetch")
        self.assertEqual(code, 1, out)
        self.assertIn("cannot compare with open ready #301", out)

    def crate_branch(self, name, line, text, subject, start="origin/main", rust_checked=True):
        """A branch changing one line of crates/pi-natives/src/desktop/mod.rs (seeded on main first),
        with its linux rust-check recorded unless `rust_checked` is false."""
        path = "crates/pi-natives/src/desktop/mod.rs"
        if not os.path.exists(os.path.join(self.sim.work, path)):
            self.sim.maint_sync()
            self.sim.write(self.sim.maint, path, "".join(f"m{i}\n" for i in range(1, 21)))
            sh(self.sim.maint, "git", "add", "-A")
            sh(self.sim.maint, "git", "commit", "-q", "-m", "chore: seed the desktop crate")
            sh(self.sim.maint, "git", "push", "-q", "origin", "main")
            sh(self.sim.work, "git", "fetch", "-q", "origin")
        sh(self.sim.work, "git", "checkout", "-q", "-B", name, start)
        self.sim.edit(self.sim.work, path, line, text)
        sh(self.sim.work, "git", "commit", "-q", "-am", subject)
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "-f", "fork", name)
        if rust_checked:
            base = sh(self.sim.work, "git", "merge-base", "origin/main", name).stdout.strip()
            RC.record(omp_queue.Store(self.sim.work), omp_pr.rust_diff_id(base, name, cwd=self.sim.work), "linux",
                      sh(self.sim.work, "git", "rev-parse", name).stdout.strip())

    def test_open_refuses_a_rust_branch_without_its_rust_check_and_takes_it_after(self):
        # 2026-10-18: #16202's bot-round push broke the Linux build (E0618) and no check of ours
        # compiled it there; the maintainer's did (bf9fd4bd6a).
        title = "fix(natives): keep sent input"
        self.crate_branch("octo-fork/sent-input", 7, "let held = hold(held);", title, rust_checked=False)
        self.assertEqual(self.run_pq("add", "octo-fork/sent-input", "--title", title, "--body", self.body,
                                     "--priority", "P1")[0], 0)
        code, out = self.run_pq("open", "sent-input")
        self.assertEqual(code, 1, out)
        self.assertIn("FIX   rust       linux  no rust-check recorded for this Rust diff", out)
        base = sh(self.sim.work, "git", "merge-base", "origin/main", "octo-fork/sent-input").stdout.strip()
        RC.record(omp_queue.Store(self.sim.work), omp_pr.rust_diff_id(base, "octo-fork/sent-input", cwd=self.sim.work),
                  "linux", "f" * 40)
        code, out = self.run_pq("open", "sent-input")
        self.assertEqual(code, 0, out)

    def test_a_crate_shared_with_an_open_ready_pr_needs_the_merged_tree_built_before_open(self):
        # 2026-10-14: #15761 changed `worker_with`'s return type and #15762 moved that value, on
        # different lines of one crate. Git merges them cleanly and each passes alone; the merged
        # tree fails to compile (E0507).
        self.crate_branch("octo-fork/display-turn-hold", 15, "let held = worker_with(); hold(held);",
                          "fix(natives): keep the display awake")
        self.gh.add_pr(15762, "octo-fork/display-turn-hold", "fix(natives): keep the display awake", rank="P1")
        title = "test(natives): serialize desktop worker tests"
        self.crate_branch("octo-fork/test-ownership-lock", 3, "fn worker_with() -> &'static Worker {", title)
        code, out = self.run_pq("add", "octo-fork/test-ownership-lock", "--title", title, "--body", self.body,
                                "--priority", "P0")
        self.assertEqual(code, 0, out)
        step = ("build and test the merged tree with #15762 (crates/pi-natives), "
                "then pr-queue built test-ownership-lock #15762")
        row = self.plan()["test-ownership-lock"]
        self.assertEqual((row["action"], row["reasons"]), ("open", []), "git sees no conflict")
        self.assertEqual(row["build_with"], [{"label": "#15762", "units": ["crates/pi-natives"], "built": False,
                                              "excluded": ""}])
        code, out = self.run_pq("plan")
        self.assertIn(step, out)
        code, out = self.run_pq("open", "test-ownership-lock")
        self.assertEqual(code, 1, out)
        self.assertIn(step, out)
        self.assertEqual(sorted(self.gh.prs), [15762], "nothing opened before the pair is built")
        code, out = self.run_pq("built", "test-ownership-lock", "#15762")
        self.assertEqual(code, 0, out)
        self.assertIn("crates/pi-natives in both", out)
        self.assertTrue(self.plan()["test-ownership-lock"]["build_with"][0]["built"])
        # A code change on the other side voids the record; a rebuilt pair opens.
        self.crate_branch("octo-fork/display-turn-hold", 16, "drop(held);", "fix(natives): release the hold",
                          start="fork/octo-fork/display-turn-hold")
        self.assertFalse(self.plan()["test-ownership-lock"]["build_with"][0]["built"])
        code, out = self.run_pq("open", "test-ownership-lock")
        self.assertEqual(code, 1, out)
        self.assertIn(step, out)
        self.run_pq("built", "test-ownership-lock", "#15762")
        code, out = self.run_pq("open", "test-ownership-lock")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.gh.readied, [self.gh.next])

    def test_built_saves_the_valid_pairs_and_names_each_stale_key(self):
        # 2026-10-22: `built` with a key whose PR had merged meanwhile (#16760) printed "recorded" for
        # the pairs before it, then refused the stale key and saved none of them.
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        self.sim.branch("octo-fork/o", line=9, text="O9")
        self.gh.add_pr(201, "octo-fork/o", "fix(a): o", rank="P1")
        self.sim.branch("octo-fork/m", line=15, text="M15")
        self.gh.add_pr(202, "octo-fork/m", "fix(a): m", rank="P1")
        self.run_pq("sync")
        self.sim.merge(self.gh, 202)  # merged since the last sync: its entry still says open
        self.sim.branch("octo-fork/r", line=18, text="R18")
        self.run_pq("add", "octo-fork/r", "--title", "fix(a): r", "--body", self.body)
        self.run_pq("set", "r", "--state", "closed")
        code, out = self.run_pq("built", "q", "#201", "#202", "r", "nope", "q")
        self.assertEqual(code, 0, out)
        self.assertIn("q with #201: merged tree recorded as built and tested", out)
        self.assertIn("not recorded: q with #202: merged", out)
        self.assertIn("not recorded: q with r: closed", out)
        self.assertIn("not recorded: q with nope: unknown", out)
        self.assertIn("not recorded: q with q: q itself", out)
        self.assertEqual([r["with"] for r in self.manifest()["q"]["built"]], ["#201"])
        code, out = self.run_pq("built", "q", "#202")
        self.assertEqual(code, 1, out)
        self.assertIn("not recorded: q with #202: merged", out)
        self.assertNotIn("recorded as built", out)
        self.assertEqual([r["with"] for r in self.manifest()["q"]["built"]], ["#201"])

    def test_one_round_tree_records_every_opening_pair(self):
        # 2026-10-18: ~15 workers each built their own merged tree for one plan, and each new PR
        # voided the others' records; one tree of the round, extended by SHA, covers every pair.
        self.crate_branch("octo-fork/display-turn-hold", 15, "let held = worker_with(); hold(held);",
                          "fix(natives): keep the display awake")
        self.gh.add_pr(15762, "octo-fork/display-turn-hold", "fix(natives): keep the display awake", rank="P1")
        for name, line, title in (("lock", 3, "test(natives): serialize desktop worker tests"),
                                  ("probe", 8, "fix(natives): probe the worker once")):
            self.crate_branch(f"octo-fork/{name}", line, f"{name} line", title)
            self.run_pq("add", f"octo-fork/{name}", "--title", title, "--body", self.body, "--priority", "P0")
        tips = {b: sh(self.sim.work, "git", "rev-parse", f"octo-fork/{b}").stdout.strip()
                for b in ("display-turn-hold", "lock", "probe")}
        code, out = self.run_pq("tree")
        self.assertEqual(code, 0, out)
        self.assertIn("3 branches, 2 opening(s); build and test crates/pi-natives", out)
        sh(self.sim.work, "git", "checkout", "-q", "--detach", "origin/main")
        sh(self.sim.work, "git", "merge", "-q", "--no-edit", tips["display-turn-hold"], tips["lock"])
        partial = sh(self.sim.work, "git", "rev-parse", "HEAD").stdout.strip()
        code, out = self.run_pq("tree", partial, "--record")
        self.assertEqual(code, 1, out)
        self.assertIn("lacks probe at its current tip", out)
        code, out = self.run_pq("tree", partial)
        self.assertIn(f"merge --no-edit {tips['probe']}\n", out, "extends the tree with what it lacks")
        sh(self.sim.work, "git", "merge", "-q", "--no-edit", tips["probe"])
        full = sh(self.sim.work, "git", "rev-parse", "HEAD").stdout.strip()
        # Every pair here shares crates/pi-natives: without --rust nothing is recorded (2026-10-19,
        # release-helper-wait-test + #16223 recorded from a bun-only check).
        code, out = self.run_pq("tree", full, "--record")
        self.assertEqual(code, 0, out)
        self.assertIn(f"not recorded: lock with #15762 share a crate; once cargo build and test passed in {full[:10]}", out)
        self.assertFalse(any(s["built"] for r in self.plan().values() for s in r["build_with"]))
        code, out = self.run_pq("open", "lock")
        self.assertEqual(code, 1, out)
        code, out = self.run_pq("tree", full, "--record", "--rust")
        self.assertEqual(code, 0, out)
        self.assertTrue(all(s["built"] for r in self.plan().values() for s in r["build_with"]))
        entries = self.manifest()
        self.assertEqual({r["tree"] for e in ("lock", "probe") for r in entries[e]["built"]}, {full})
        code, out = self.run_pq("tree")
        self.assertIn("nothing to build", out)
        for name in ("lock", "probe"):
            code, out = self.run_pq("open", name)
            self.assertEqual(code, 0, out)

    def test_an_open_pr_conflicting_with_main_does_not_gate_the_merged_build(self):
        # 2026-10-16: #15433 conflicted with main in its own files, so no tree held it beside
        # inflight-epoch and `open` refused for a build that could not run. Its rebase builds with the rest.
        self.crate_branch("octo-fork/display-turn-hold", 15, "let held = worker_with(); hold(held);",
                          "fix(natives): keep the display awake")
        self.gh.add_pr(15762, "octo-fork/display-turn-hold", "fix(natives): keep the display awake", rank="P1")
        self.sim.maint_sync()
        self.sim.edit(self.sim.maint, "crates/pi-natives/src/desktop/mod.rs", 15, "upstream line 15")
        sh(self.sim.maint, "git", "commit", "-q", "-am", "chore: upstream rewrites line 15")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        title = "test(natives): serialize desktop worker tests"
        self.crate_branch("octo-fork/test-ownership-lock", 3, "fn worker_with() -> &'static Worker {", title)
        self.run_pq("add", "octo-fork/test-ownership-lock", "--title", title, "--body", self.body, "--priority", "P0")
        rows = self.plan()
        self.assertEqual(rows["#15762"]["action"], "rebase")
        row = rows["test-ownership-lock"]
        self.assertEqual(row["action"], "open")
        self.assertEqual(row["build_with"], [{
            "label": "#15762", "units": ["crates/pi-natives"], "built": False,
            "excluded": "it conflicts with main in crates/pi-natives/src/desktop/mod.rs"}])
        code, out = self.run_pq("plan")
        self.assertIn("nothing to build beside; not with #15762: it conflicts with main in "
                      "crates/pi-natives/src/desktop/mod.rs, so its own rebase builds with the rest", out)
        code, out = self.run_pq("open", "test-ownership-lock")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.gh.readied, [self.gh.next])

    def test_precheck_notes_an_open_ready_pr_in_the_same_crate(self):
        self.crate_branch("octo-fork/display-turn-hold", 15, "let held = worker_with(); hold(held);",
                          "fix(natives): keep the display awake")
        self.gh.add_pr(15762, "octo-fork/display-turn-hold", "fix(natives): keep the display awake")
        self.crate_branch("octo-fork/test-ownership-lock", 3, "fn worker_with() -> &'static Worker {",
                          "test(natives): serialize desktop worker tests")
        self.gh.add_pr(15761, "octo-fork/test-ownership-lock", "test(natives): serialize desktop worker tests")
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.gh.add_pr(301, "octo-fork/q", "fix(a): q")  # packages/a alone: no step
        out = io.StringIO()
        with mock.patch.object(PC, "GitHub", lambda: self.gh), contextlib.redirect_stdout(out):
            PC.check_siblings("fork/octo-fork/test-ownership-lock", 15761, self.sim.work)
        self.assertEqual(out.getvalue(), "NOTE  build      crates/pi-natives  also changed by open ready #15762: build "
                                         "and test the merged tree with it (queue.md, Opening)\n")

    def siblings(self, ref, number=None):
        out = io.StringIO()
        with mock.patch.object(PC, "GitHub", lambda: self.gh), contextlib.redirect_stdout(out):
            PC.check_siblings(ref, number, self.sim.work)
        return [line for line in out.getvalue().splitlines() if "carries" in line]

    def stacked_child_of_rebased_parent(self, context_changes=False):
        """#101 (two commits), drafts #102 and #103 stacked on them with one commit each, synced (so
        both need #101), then #101 rebased onto a newer main and given three fix commits: #15184,
        #15563 and #15195. With `context_changes`, main's new commit sits in the context of #101's
        first commit, so its rebased copy has another patch id (#15184's apps.open commit)."""
        sh(self.sim.work, "git", "checkout", "-q", "-b", "octo-fork/p", "origin/main")
        for line in (3, 5):
            self.sim.change(self.sim.work, line, f"P{line}", f"fix(a): parent {line}")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "fork", "octo-fork/p")
        self.gh.add_pr(101, "octo-fork/p", "fix(a): parent")
        self.sim.branch("octo-fork/c", start="octo-fork/p", line=12, text="C12")
        self.gh.add_pr(102, "octo-fork/c", "feat(a): child", draft=True)
        self.sim.branch("octo-fork/d", start="octo-fork/p", line=16, text="D16")
        self.gh.add_pr(103, "octo-fork/d", "feat(a): sibling", draft=True)
        code, out = self.run_pq("sync")
        self.assertEqual(code, 0, out)
        self.assertEqual([self.manifest()[k]["needs"] for k in ("c", "d")], [["#101"], ["#101"]])
        self.sim.upstream_change(1, "unrelated", pkg="a" if context_changes else "b")
        sh(self.sim.work, "git", "fetch", "-q", "origin")
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/p")
        sh(self.sim.work, "git", "rebase", "-q", "origin/main")
        for line in (7, 8, 9):
            self.sim.change(self.sim.work, line, f"P{line} fix", f"fix(a): parent fix {line}")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "--force", "fork", "octo-fork/p")

    def test_precheck_a_rebased_parent_does_not_carry_the_child_stacked_on_its_old_commits(self):
        self.stacked_child_of_rebased_parent()
        self.assertEqual(self.siblings("fork/octo-fork/p", 101), [])
        code, out = self.run_pq("audit", "--json")
        flags = {r["number"]: dict(r["flags"]) for r in json.loads(out)}
        self.assertNotIn("carries", flags[101])

    def test_precheck_a_child_still_carries_its_rebased_parents_commits_by_patch_id(self):
        self.stacked_child_of_rebased_parent()
        self.assertEqual(sh(self.sim.work, "git", "merge-base", "--is-ancestor", "fork/octo-fork/p", "fork/octo-fork/c",
                            check=False).returncode, 1, "only old copies of #101's commits are on #102")
        [line] = self.siblings("fork/octo-fork/c", 102)
        self.assertRegex(line, r"^FIX\s+carries\s+#101\s+2 of its commits are on this branch")

    def test_precheck_a_branch_holding_another_prs_own_commit_carries_it(self):
        self.stacked_child_of_rebased_parent()
        self.sim.branch("octo-fork/x", start="fork/octo-fork/c", line=18, text="X18")
        lines = self.siblings("fork/octo-fork/x")
        self.assertEqual(len(lines), 2, lines)
        self.assertRegex(lines[0], r"^FIX\s+carries\s+#101\s+2 of its commits")
        self.assertRegex(lines[1], r"^FIX\s+carries\s+#102\s+1 of its commits")

    def test_precheck_siblings_share_their_parents_old_commit_whose_rebased_copy_changed(self):
        self.stacked_child_of_rebased_parent(context_changes=True)
        old, new = (sh(self.sim.work, "git", "rev-parse", ref).stdout.strip() for ref in ("fork/octo-fork/c~2", "fork/octo-fork/p~4"))
        pids = omp_queue.PatchIds(self.sim.work)([old, new])
        self.assertNotEqual(pids[old], pids[new], "#101's first commit changed patch id in the rebase")
        self.assertEqual(self.siblings("fork/octo-fork/p", 101), [])
        [line] = self.siblings("fork/octo-fork/c", 102)
        self.assertRegex(line, r"^FIX\s+carries\s+#101\s+2 of its commits", "not #103's")

    def test_a_queue_write_failing_after_the_draft_names_the_draft(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5", entry="Fixed q")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        update = omp_queue.Store.update

        def failing(store, fn, message):
            if message.startswith(("open ", "unlock open")):  # the fork stays unreachable
                raise omp_queue.GitError("pushing the queue to fork: unreachable")
            return update(store, fn, message)
        omp_queue.Store.update = failing
        try:
            code, out = self.run_pq("open", "q")
        finally:
            omp_queue.Store.update = update
        self.assertEqual(code, 1)
        self.assertIn(f"#{self.gh.next} stays a draft: pushing the queue to fork: unreachable", out)
        self.assertIn(f"pr-queue set q --state open --pr {self.gh.next}", out)
        self.assertEqual(self.gh.readied, [])

    def test_an_open_whose_lock_was_taken_over_stops_before_ready(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5", entry="Fixed q")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        link = PQ.link_changelogs

        def slow_link(*args):  # this run outlives its lock and another run takes it meanwhile
            omp_queue.Store(self.sim.work).update(lambda m, f: m.update(opening={
                "id": "other", "token": "theirs", "host": "other", "at": omp_queue.stamp()}), "take over")
            return link(*args)
        PQ.link_changelogs = slow_link
        try:
            code, out = self.run_pq("open", "q")
        finally:
            PQ.link_changelogs = link
        self.assertEqual(code, 1)
        self.assertIn("stays a draft: this run's open lock expired and another run took it", out)
        self.assertEqual(self.gh.readied, [])

    def test_a_closed_need_whose_content_landed_unblocks(self):
        self.open_parent_and_queue_child()
        self.run_pq("sync")
        self.sim.cherry_pick(sh(self.sim.work, "git", "rev-parse", "octo-fork/p").stdout.strip())
        self.assertEqual(self.plan()["#101"]["action"], "close")
        self.gh.close(101)
        code, out = self.run_pq("sync")
        self.assertIn("#101 p: merged (closed, content on main)", out)
        self.assertEqual(self.run_pq("advance")[0], 0)
        self.assertEqual(self.plan()["c"]["action"], "open")

    def test_ready_events_follow_timeline_order_and_draft_state(self):
        since = omp_queue.now() - datetime.timedelta(hours=1)
        t = lambda m: (since + datetime.timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        old = "2026-01-01T00:00:00Z"

        def pr(created, draft, *events, hidden=0):
            return {"createdAt": created, "isDraft": draft, "timelineItems": {
                "filteredCount": len(events) + hidden,
                "nodes": [{"createdAt": at, "__typename": kind} for at, kind in events]}}
        nodes = [
            pr(old, True, (t(5), "ReadyForReviewEvent"), (t(5), "ConvertToDraftEvent"), (t(6), "ReopenedEvent")),
            pr(t(1), False),  # opened ready
            pr(t(2), True, (t(3), "ReadyForReviewEvent"), (t(4), "ConvertToDraftEvent")),
            pr(old, False, (t(7), "ReopenedEvent"), hidden=3),  # cut-off items may be in the window
            {"createdAt": t(8), "timelineItems": {"filteredCount": 0, "nodes": []}},  # an issue
        ]
        github = omp_queue.GitHub()
        github._graphql = lambda query, **v: {"search": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}
        self.assertEqual(github.ready_events_since(since), 1 + 1 + 1 + (3 + 1) + 1)

    def test_an_older_landed_pr_does_not_stand_for_its_entrys_newer_content(self):
        first = self.sim.branch("octo-fork/p", line=3, text="P3")
        self.gh.add_pr(501, "octo-fork/p", "fix(a): p")
        sh(self.sim.work, "git", "checkout", "-q", "octo-fork/p")
        self.sim.change(self.sim.work, 12, "P12 needed by the child", "fix(a): more p")
        sh(self.sim.work, "git", "checkout", "-q", "--detach")
        sh(self.sim.work, "git", "push", "-q", "fork", "octo-fork/p")
        self.gh.add_pr(502, "octo-fork/p", "fix(a): p, reworked")
        self.sim.branch("octo-fork/c", start="octo-fork/p", line=15, text="C15")
        self.run_pq("add", "octo-fork/p", "--title", "fix(a): p")
        self.run_pq("add", "octo-fork/c", "--title", "fix(a): c", "--needs", "p")
        for n in (501, 502):
            self.gh.close(n)
        omp_queue.Store(self.sim.work).update(lambda m, f: omp_queue.find_entry(m, "p").update(
            state="closed", closed_prs=[501, 502]), "close p")
        self.sim.cherry_pick(first)
        row = self.plan()["c"]
        self.assertEqual(row["action"], "wait")
        self.assertIn("needs p (closed)", row["reasons"][0])

    def test_sync_marks_a_branch_merged_as_is(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q")
        self.sim.maint_sync()
        sh(self.sim.maint, "git", "merge", "-q", "--no-ff", "fork/octo-fork/q", "-m", "Merge octo-fork/q")
        sh(self.sim.maint, "git", "push", "-q", "origin", "main")
        code, out = self.run_pq("sync")
        self.assertIn("q: merged (its branch is part of origin/main)", out)

    def test_sync_marks_content_on_main_merged_by_patch_id(self):
        tip = self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q")
        self.sim.cherry_pick(tip)
        code, out = self.run_pq("sync")
        self.assertIn("q: merged (its 1 own commit(s) are on origin/main)", out)
        self.assertEqual(self.manifest()["q"]["merged_by"], "patch-id")

    def test_requeue_closes_and_queues_with_inferred_need(self):
        a = self.sim.branch("octo-fork/a", line=2, text="A2")
        self.sim.branch("octo-fork/b", start="octo-fork/a", line=2, text="B2", pkg="b")
        self.gh.add_pr(401, "octo-fork/a", "fix(a): a", rank="P0")
        self.gh.add_pr(402, "octo-fork/b", "fix(b): b", rank="P1")
        code, out = self.run_pq("requeue", "402")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.gh.closed, [402])
        entry = self.manifest()["b"]
        self.assertEqual((entry["state"], entry["needs"], entry["base"], entry["closed_prs"]),
                         ("queued", ["#401"], a, [402]))

    def requeue_with(self, fail_store=None, fail_close=False, body=None):
        """Requeue #702 (octo-fork/q) with failures injected: `fail_store` is the message of the store
        write that fails ("*": every write), `body` replaces what `gh pr view` returns (an exception
        is raised)."""
        if 702 not in self.gh.prs:
            self.sim.branch("octo-fork/q", line=5, text="Q5")
            self.gh.add_pr(702, "octo-fork/q", "fix(a): q", rank="P1")
        update, close, read = omp_queue.Store.update, self.gh.close, self.gh.body

        def store_update(store, fn, message):
            if fail_store in ("*", message):
                raise omp_queue.GitError("pushing the queue to fork: unreachable")
            return update(store, fn, message)

        def gh_close(number):
            if fail_close:
                raise omp_queue.GitError(f"gh pr close {number}: HTTP 502")
            close(number)

        def gh_body(number):
            if isinstance(body, Exception):
                raise body
            return read(number) if body is None else body
        omp_queue.Store.update, self.gh.close, self.gh.body = store_update, gh_close, gh_body
        try:
            return self.run_pq("requeue", "702")
        finally:
            omp_queue.Store.update, self.gh.close, self.gh.body = update, close, read

    def test_requeue_body_read_failure_is_fail_safe(self):
        code, out = self.requeue_with(body="")  # what a failed read used to turn into
        self.assertEqual((code, self.gh.closed), (1, []), out)
        self.assertIn("empty body for a PR that has one", out)
        code, out = self.requeue_with(body=omp_queue.GitError("gh pr view 702: HTTP 502"))
        self.assertEqual((code, self.gh.closed), (1, []), out)
        self.assertIn("#702 stays open, nothing closed: reading its body failed", out)
        self.assertNotIn("q", self.manifest())
        run = omp_queue.run
        omp_queue.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "HTTP 502")
        try:
            with self.assertRaises(omp_queue.GitError, msg="the real reader fails loudly, never returns ''"):
                omp_queue.GitHub().body(702)
        finally:
            omp_queue.run = run

    def test_requeue_store_failure_is_fail_safe(self):
        code, out = self.requeue_with(fail_store="*")  # the fork is unreachable throughout
        self.assertEqual((code, self.gh.closed), (1, []), out)
        self.assertIn("#702 stays open, nothing closed: storing its entry failed", out)
        self.assertNotIn("q", self.manifest())

    def test_requeue_close_failure_leaves_the_entry_open_and_stored(self):
        code, out = self.requeue_with(fail_close=True)
        self.assertEqual((code, self.gh.closed), (1, []), out)
        self.assertIn("#702 stays open: gh pr close 702: HTTP 502", out)
        entry = self.manifest()["q"]
        self.assertEqual((entry["state"], entry["pr"]), ("open", 702))
        self.assertEqual(omp_queue.Store(self.sim.work).read(entry["body"]), BODY)

    def test_requeue_whose_last_write_fails_is_finished_by_sync(self):
        code, out = self.requeue_with(fail_store="requeue PR 702")  # the write after the close
        self.assertEqual((code, self.gh.closed), (1, [702]), out)
        self.assertIn("closed #702; its body and entry q are stored, but marking it queued failed", out)
        code, out = self.run_pq("sync")
        self.assertIn("#702 q: closed by requeue, now queued", out)
        entry = self.manifest()["q"]
        self.assertEqual((entry["state"], entry["pr"], entry["closed_prs"], "requeue" in entry),
                         ("queued", None, [702], False))
        self.assertEqual(omp_queue.Store(self.sim.work).read(entry["body"]), BODY)

    def test_manifest_on_fork_is_shared_and_survives_a_race(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q")
        other = os.path.join(self.dir, "other-host")
        sh(self.dir, "git", "clone", "-q", self.sim.upstream, other)
        sh(other, "git", "remote", "add", "fork", self.sim.fork)
        sh(other, "git", "fetch", "-q", "fork")
        self.assertIn("q", self.manifest(repo=other), "a second host reads the same queue")
        store, raced = omp_queue.Store(self.sim.work), []

        def change(m, files):
            if not raced:  # another host writes between our read and our push
                raced.append(1)
                self.assertEqual(self.run_pq("set", "q", "--area", "browser", repo=other)[0], 0)
            omp_queue.find_entry(m, "q")["note"] = "ours"
        store.update(change, "test")
        entry = self.manifest()["q"]
        self.assertEqual((entry["area"], entry["note"]), ("browser", "ours"))

    def test_a_store_commit_names_prs_without_linking_them(self):
        # A fork commit naming #N lands "referenced this pull request" on upstream PR N's timeline.
        omp_queue.Store(self.sim.work).update(lambda m, f: None, "ready #15920 after can1357/oh-my-pi#15919")
        message = sh(self.sim.work, "git", "log", "-1", "--format=%B", "refs/remotes/fork/omp-queue").stdout
        self.assertEqual(message.strip(), "ready PR 15920 after PR 15919")

    # --- watch ---------------------------------------------------------------------------------------

    def watch(self):
        code, out = self.run_pq("watch")
        self.assertEqual(code, 0, out)
        return out

    def record(self):
        manifest, _ = omp_queue.Store(self.sim.work).load()
        return manifest.get("watch")

    def store_rev(self):
        return sh(self.sim.work, "git", "ls-remote", self.sim.fork, "refs/heads/omp-queue").stdout.split()[0]

    def test_watch_sees_a_merge_its_child_turn_openable_then_open_and_the_merge_ship(self):
        self.open_parent_and_queue_child()
        out = self.watch()
        self.assertIn("Nothing ready to open", out)
        self.assertEqual(self.record()["events"], [], "the first run is the baseline")
        self.sim.merge(self.gh, 101, fixup=(3, "P3 fixed by the maintainer"))
        out = self.watch()
        self.assertIn("#101 merged by the maintainer (1 maintainer commit): fix(a): parent", out)
        self.assertIn("c ready to open: fix(a): child", out)
        since = self.record()["openable"]["c"]["since"]
        self.assertIn(f"Ready to open since {omp_watch.clock(since, omp_queue.now())}: c", out)
        self.assertEqual(list(self.record()["unreleased"]), ["101"])
        self.assertEqual(self.run_pq("advance")[0], 0)
        code, out = self.run_pq("open", "c")
        self.assertEqual(code, 0, out)
        out = self.watch()
        self.assertIn(f"c no longer ready to open: opened as #{self.gh.next}", out)
        self.assertEqual(self.record()["openable"], {})
        self.sim.release(tag="v1.1.0")
        out = self.watch()
        self.assertIn("#101 ships in v1.1.0", out)
        self.assertIn("Newly released: #101 in v1.1.0", out)
        self.assertEqual(self.record()["unreleased"], {})
        kinds = [e["kind"] for e in self.record()["events"]]
        self.assertEqual(kinds, ["merged", "openable", "unopenable", "released"])

    def test_watch_sees_an_open_ready_pr_start_conflicting_with_main(self):
        self.sim.branch("octo-fork/r", line=9, text="R9")
        self.gh.add_pr(301, "octo-fork/r", "fix(a): r", rank="P0")
        self.watch()
        self.assertEqual(self.record()["conflicts"], {})
        self.sim.upstream_change(9, "U9", pkg="a")
        out = self.watch()
        self.assertIn("#301 now conflicts with main in packages/a/src/x.txt", out)
        self.assertIn("#301 conflicts with main since", out)
        self.assertEqual(self.record()["conflicts"]["#301"]["files"], ["packages/a/src/x.txt"])
        out = self.watch()
        self.assertNotIn("now conflicts", out, "a conflict is an event once")

    def test_watch_records_post_merge_findings_until_main_takes_them_up(self):
        self.open_parent_and_queue_child()
        self.watch()
        self.sim.merge(self.gh, 101)
        self.gh.post_merge[101] = [{"bot": "chatgpt-codex-connector", "severity": "P2", "path": "packages/a/src/x.txt",
                                    "start": 3, "end": 3, "commit": "c" * 40, "url": "https://x/r3", "taken_up": None}]
        out = self.watch()
        self.assertIn("#101 drew a post-merge Codex P2 finding: packages/a/src/x.txt:3 https://x/r3", out)
        self.assertIn("Post-merge findings open (fix each as a follow-up off main, workflow step 10): #101 Codex P2 x1",
                      out)
        self.assertEqual(self.gh.asked_post_merge[-1], [101])
        self.gh.post_merge[101] = []  # a main commit took it up
        out = self.watch()
        self.assertNotIn("Post-merge findings open", out)
        self.assertEqual(self.record()["post_merge"]["101"]["findings"], [])

    def test_watch_seeds_post_merge_tracking_on_a_record_from_before_it(self):
        self.open_parent_and_queue_child()
        self.sim.merge(self.gh, 101)
        self.watch()
        omp_queue.Store(self.sim.work).update(lambda m, f: m["watch"].pop("post_merge"), "t")
        self.gh.asked_post_merge.clear()
        self.watch()
        self.assertEqual(self.gh.asked_post_merge, [[101]], "the merge from before the upgrade is asked about")

    def test_watch_skips_and_says_so_while_an_open_holds_the_lock(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        store = omp_queue.Store(self.sim.work)
        store.update(lambda m, f: m.update(opening={"id": "q", "host": "other", "at": omp_queue.stamp()}), "t")
        before = self.store_rev()
        self.assertTrue(self.watch().startswith("skipping this run: `open` holds the queue lock (q on other since "))
        self.assertEqual(self.store_rev(), before)
        self.assertIsNone(self.record())

    def test_watch_skips_its_run_and_says_so_when_the_graphql_budget_is_low(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        self.gh.left = PQ.WATCH_FLOOR - 1
        before = self.store_rev()
        out = self.watch()
        self.assertIn(f"budget low ({PQ.WATCH_FLOOR - 1} points left", out)
        self.assertIn("resets 00:03Z", out)
        self.assertEqual(self.store_rev(), before)
        self.assertIsNone(self.record())
        self.gh.left = PQ.WATCH_FLOOR
        self.watch()
        self.assertEqual(list(self.record()["openable"]), ["q"])

    def test_watch_writes_the_queue_only_on_a_change_or_an_hourly_heartbeat(self):
        self.sim.branch("octo-fork/q", line=5, text="Q5")
        self.run_pq("add", "octo-fork/q", "--title", "fix(a): q", "--body", self.body)
        self.watch()
        self.assertEqual(list(self.record()["openable"]), ["q"])
        before = self.store_rev()
        out = self.watch()
        self.assertIn("Ready to open since", out)
        self.assertEqual(self.store_rev(), before, "nothing changed: no queue commit")
        aged = omp_watch.fmt(omp_queue.now() - omp_watch.HEARTBEAT)
        omp_queue.Store(self.sim.work).update(lambda m, f: m["watch"].update(checked=aged), "t")
        before = self.store_rev()
        self.watch()
        self.assertNotEqual(self.store_rev(), before, "the heartbeat is due")
        self.assertGreater(self.record()["checked"], aged)

    def test_watch_refreshes_series_posts_when_a_pr_merges_closes_opens_turns_ready_or_ships(self):
        with open(PQ.SERIES_POSTS, "w") as f:
            f.write("# 999  # a disabled post\n16124  # series 1\n")
        calls = []
        with mock.patch.object(PQ, "refresh_posts", lambda repo, touched, posts: calls.append((touched, posts))):
            self.open_parent_and_queue_child()
            self.gh.add_pr(102, "octo-fork/c", "fix(a): child draft", draft=True)
            self.watch()
            self.assertEqual(calls[-1], ({101, 102}, [16124]), "first run: imports and ready PRs")
            self.watch()
            self.assertEqual(calls[-1][0], set(), "nothing changed: no refresh")
            self.gh.prs[102]["draft"] = False
            self.watch()
            self.assertEqual(calls[-1][0], {102}, "a draft turned ready")
            self.sim.merge(self.gh, 101)
            self.watch()
            self.assertEqual(calls[-1][0], {101}, "a merge")
            self.sim.release(tag="v1.1.0")
            self.watch()
            self.assertEqual(calls[-1][0], {101}, "a merge a release now ships")
            self.gh.prs[102]["state"] = "CLOSED"
            self.watch()
            self.assertEqual(calls[-1][0], {102}, "a close")

    def test_refresh_posts_runs_post_status_per_post_only_when_something_was_touched(self):
        runs = []
        done = subprocess.CompletedProcess([], 0, "discussion #16124: series status updated\n", "")
        with mock.patch.object(PQ.subprocess, "run", lambda args, **kw: runs.append(args) or done):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                PQ.refresh_posts("/repo", set(), [16124])
                PQ.refresh_posts("/repo", {15184, 15157}, [16124, 7])
        self.assertEqual([a[2:] for a in runs], [["16124", "--repo", "/repo", "--if-touched", "15157,15184"],
                                                 ["7", "--repo", "/repo", "--if-touched", "15157,15184"]])
        self.assertTrue(runs[0][1].endswith("post-status"))
        self.assertIn("post #16124: discussion #16124: series status updated", out.getvalue())

    def test_series_posts_reads_first_words_and_skips_comments(self):
        with open(PQ.SERIES_POSTS, "w") as f:
            f.write("# heading 5\n\n# 16124  # off\n16125  # series 2 has 3 words\n  77\n")
        self.assertEqual(PQ.series_posts(), [16125, 77])
        os.remove(PQ.SERIES_POSTS)
        self.assertEqual(PQ.series_posts(), [])
        self.assertEqual(PQ.series_posts(os.path.join(SCRIPTS, "series-posts")), [],
                         "the shipped list is a template: each user approves their own posts")


class StoredBodyTest(unittest.TestCase):
    """A closed PR whose change is queued reopens with the stored body (`open` posts it): two edits to
    closed #15569's GitHub body on 2026-10-15 would have been lost. `pr-queue body-home` and `precheck N`
    name it; an open PR, and a closed one no entry queues, keep GitHub's body as theirs."""

    STATES = {15569: "CLOSED", 15601: "OPEN", 15602: "CLOSED"}

    class States:
        def states(self, numbers):
            return {n: StoredBodyTest.STATES[n] for n in numbers}

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=ROOT)
        self.manifest = os.path.join(self.dir, "queue.json")
        entries = [omp_queue.new_entry("octo-fork/relay-turn-end-detach", closed_prs=[15569]),
                   omp_queue.new_entry("octo-fork/open-one", state="open", pr=15601)]
        with open(self.manifest, "w") as f:
            json.dump({**omp_queue.empty_manifest(), "entries": entries}, f)

    def body_home(self, number):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            PQ.main(["--manifest", self.manifest, "body-home", f"#{number}"], github=self.States())
        return json.loads(out.getvalue())

    def precheck(self, number, draft=False):
        """precheck N's output up to its first git call (the queue check runs before any)."""
        class Stop(Exception):
            pass

        asked = []

        def gh_json(*args):
            asked.append(args)
            return {"number": number, "state": self.STATES[number], "isDraft": draft, "title": "fix: x",
                    "headRefName": "octo-fork/x", "body": BODY, "closingIssuesReferences": []}

        def stop(*args, **kwargs):
            raise Stop

        out = io.StringIO()
        with mock.patch.object(PC, "gh_json", gh_json), mock.patch.object(PC, "run", stop), \
                mock.patch.object(PC, "Store", lambda repo: omp_queue.Store(repo, self.manifest)), \
                mock.patch.object(PC, "findings", []), contextlib.redirect_stdout(out):
            with self.assertRaises(Stop):
                PC.main([str(number)])
        self.assertIn("state", asked[0][-1].split(","))
        return out.getvalue()

    def test_body_home_names_the_entry_of_a_closed_queued_pr(self):
        self.assertEqual(self.body_home(15569), {
            "number": 15569, "entry": "relay-turn-end-detach",
            "message": "#15569 is closed, queued as relay-turn-end-detach; edit its stored body "
                       "(pr-queue show / set --body), not GitHub's"})

    def test_body_home_leaves_an_open_pr_and_an_unqueued_closed_one_on_github(self):
        for number in (15601, 15602):
            self.assertEqual(self.body_home(number), {"number": number, "entry": None, "message": None})

    def test_precheck_fixes_a_closed_queued_pr(self):
        self.assertEqual(self.precheck(15569).strip(),
                         "FIX   queue      #15569 is closed, queued as relay-turn-end-detach; edit its stored body "
                         "(pr-queue show / set --body), not GitHub's")

    def test_precheck_is_silent_on_an_open_pr_and_an_unqueued_closed_one(self):
        for number in (15601, 15602):
            self.assertEqual(self.precheck(number), "")

    def test_precheck_fixes_a_draft_or_closed_pr_while_opening_is_paused(self):
        pause = "user, 2026-01-02: pause for maintainer round"
        with open(self.manifest) as f:
            manifest = json.load(f)
        manifest["config"]["pause"] = pause
        with open(self.manifest, "w") as f:
            json.dump(manifest, f)
        line = omp_queue.pause_line(pause)
        self.assertEqual(self.precheck(15601, draft=True).strip(), f"FIX   queue      #15601 is a draft: {line}")
        self.assertEqual(self.precheck(15602).strip(), f"FIX   queue      #15602 is closed: {line}")
        self.assertEqual(self.precheck(15601), "", "an open ready PR carries on")



class WatchRecordTest(unittest.TestCase):
    AT = ["2026-10-14T10:00:00Z", "2026-10-14T10:30:00Z", "2026-10-14T11:00:00Z"]

    @staticmethod
    def cur(openable=(), entries=None, rows=None):
        return {"openable": {i: f"fix: {i}" for i in openable}, "rows": rows or {}, "entries": entries or {},
                "conflicts": {}, "merges": [], "releases": {}, "host": "linux-box"}

    def test_openable_since_holds_across_runs_and_its_end_says_why(self):
        first, events = omp_watch.observe(None, self.cur(["a"]), self.AT[0])
        self.assertEqual(events, [])
        second, events = omp_watch.observe(first, self.cur(["a", "b"]), self.AT[1])
        self.assertEqual([(e["kind"], e["id"]) for e in events], [("openable", "b")])
        self.assertEqual({i: o["since"] for i, o in second["openable"].items()}, {"a": self.AT[0], "b": self.AT[1]})
        third, events = omp_watch.observe(second, self.cur(
            [], entries={"a": {"state": "queued", "pr": None}, "b": {"state": "open", "pr": 15500}},
            rows={"a": {"action": "wait", "reasons": ["conflicts with b in x"]}}), self.AT[2])
        self.assertEqual({e["id"]: e["why"] for e in events},
                         {"a": "plan: wait (conflicts with b in x)", "b": "opened as #15500"})

    def test_headline_groups_by_since_and_says_when_the_watcher_went_silent(self):
        record, _ = omp_watch.observe(None, self.cur(["a"]), self.AT[0])
        record, _ = omp_watch.observe(record, self.cur(["a", "b", "c"]), self.AT[1])
        now = omp_watch.parse(self.AT[1])
        self.assertEqual(omp_watch.headline(record, now)[0],
                         "Ready to open since 10:00Z: a; since 10:30Z: b, c  (queue watch, linux-box 10:30Z)")
        late = omp_watch.headline(record, now + omp_watch.STALE + datetime.timedelta(minutes=1))
        self.assertTrue(late[0].startswith("Queue watcher silent since 10:30Z (2h ago)"), late[0])
        self.assertFalse(omp_watch.stale(record, now + omp_watch.STALE))
        self.assertEqual(omp_watch.headline(None, now)[0][:39], "Queue watcher: no run recorded in the q")

    def test_written_only_when_more_than_checked_changed_or_an_hour_passed(self):
        record, _ = omp_watch.observe(None, self.cur(["a"]), self.AT[0])
        again, _ = omp_watch.observe(record, self.cur(["a"]), self.AT[1])
        self.assertFalse(omp_watch.changed(record, again))
        self.assertFalse(omp_watch.heartbeat_due(record, self.AT[1]))
        self.assertTrue(omp_watch.heartbeat_due(record, self.AT[2]))
        moved, _ = omp_watch.observe(record, self.cur(["a", "b"]), self.AT[1])
        self.assertTrue(omp_watch.changed(record, moved))

    def test_headline_on_a_host_that_could_not_fetch_the_queue_does_not_blame_the_watcher(self):
        # 2026-10-20: a second host printed "silent since 03:52Z (16h ago)" from its last-fetched copy while
        # linux-box's timer had written the record at 19:38Z.
        record, _ = omp_watch.observe(None, self.cur(["a"]), self.AT[0])
        late = omp_watch.parse(self.AT[0]) + datetime.timedelta(hours=16)
        lines = omp_watch.headline(record, late, fetch_error="fetching the queue from fork: offline")
        self.assertEqual(lines[0], "Queue record not refreshed on this host (fetching the queue from fork: offline); "
                                   "below is this host's copy, as of 10-14 10:00Z")
        self.assertFalse(any("silent" in line for line in lines))

    FINDING = {"bot": "chatgpt-codex-connector", "severity": "P1", "path": "a.rs", "start": 9, "end": 9,
               "commit": "c" * 40, "url": "https://x/r9", "taken_up": None}
    MERGE = {"number": 16288, "title": "fix(catalog): keep requests under the limit", "merge_commit": "e" * 40,
             "merged_at": "2026-10-14T09:00:00Z"}

    def checked(self, findings):
        cur = self.cur()
        cur["post_merge"] = {16288: {**{k: self.MERGE[k] for k in ("title", "merge_commit", "merged_at")},
                                     "findings": findings}}
        return cur

    def test_a_post_merge_finding_is_an_event_once_and_stays_until_taken_up(self):
        record, _ = omp_watch.observe(None, self.cur(), self.AT[0])
        record, events = omp_watch.observe(record, self.checked([self.FINDING]), self.AT[1])
        self.assertEqual([(e["kind"], e["number"], e["url"]) for e in events], [("post-merge", 16288, "https://x/r9")])
        self.assertEqual(omp_watch.event_line(events[0], omp_watch.parse(self.AT[1])),
                         "10:30Z #16288 drew a post-merge Codex P1 finding: a.rs:9 https://x/r9")
        record, events = omp_watch.observe(record, self.checked([self.FINDING]), self.AT[2])
        self.assertEqual(events, [], "an event once")
        days_later = omp_watch.fmt(omp_watch.parse(self.AT[2]) + datetime.timedelta(days=5))
        self.assertEqual(omp_watch.post_merge_candidates(record, [], days_later),
                         [self.MERGE], "an open finding keeps its merge asked about past POST_MERGE_DAYS")
        record, _ = omp_watch.observe(record, self.checked([self.FINDING]), days_later)
        self.assertIn("Post-merge findings open (fix each as a follow-up off main, workflow step 10): #16288 Codex P1 x1",
                      omp_watch.headline(record, omp_watch.parse(days_later)))
        failed = omp_watch.observe(record, self.cur(), days_later)[0]
        self.assertEqual(failed["post_merge"], record["post_merge"], "a failed query keeps the last findings")
        record, _ = omp_watch.observe(record, self.checked([]), days_later)
        self.assertEqual(record["post_merge"], {}, "taken up (or resolved), and past the window: dropped")

    def test_a_finding_our_follow_up_addresses_leaves_the_open_line_but_stays_tracked(self):
        # 2026-10-22: #16564 ("Follow-up to #16288") was open while the headline still asked us to fix #16288.
        record, _ = omp_watch.observe(None, self.cur(), self.AT[0])
        record, _ = omp_watch.observe(record, self.checked([{**self.FINDING, "addressed_by": 16564}]), self.AT[1])
        lines = omp_watch.headline(record, omp_watch.parse(self.AT[1]))
        self.assertFalse(any(line.startswith("Post-merge findings open") for line in lines), lines)
        self.assertIn("Post-merge findings with a follow-up PR open or merged: #16288 by #16564", lines)
        days_later = omp_watch.fmt(omp_watch.parse(self.AT[1]) + datetime.timedelta(days=5))
        self.assertEqual(omp_watch.post_merge_candidates(record, [], days_later), [self.MERGE],
                         "still asked about, so a follow-up closed unmerged brings it back")
        record, _ = omp_watch.observe(record, self.checked([{**self.FINDING, "addressed_by": None}]), days_later)
        self.assertIn("Post-merge findings open (fix each as a follow-up off main, workflow step 10): #16288 Codex P1 x1",
                      omp_watch.headline(record, omp_watch.parse(days_later)))

    def test_candidates_are_recent_merges_with_a_merge_commit(self):
        old = {**self.MERGE, "number": 1, "merged_at": "2026-10-10T00:00:00Z"}
        squash = {**self.MERGE, "number": 2, "merge_commit": None}
        self.assertEqual([m["number"] for m in omp_watch.post_merge_candidates(None, [old, squash, self.MERGE],
                                                                                self.AT[0])], [16288])

    def test_a_merge_seen_while_the_findings_query_failed_is_asked_about_next_run(self):
        record, _ = omp_watch.observe(None, self.cur(), self.AT[0])
        cur = self.cur()
        cur.update(merges=[{**self.MERGE, "merged_by": "the maintainer", "maintainer_commits": [], "merged_at": self.AT[1]}],
                   post_merge_unchecked=[{**self.MERGE, "merged_at": self.AT[1]}])
        record, _ = omp_watch.observe(record, cur, self.AT[1])
        self.assertEqual(record["merged_through"], self.AT[1], "the watermark moves on")
        self.assertEqual([m["number"] for m in omp_watch.post_merge_candidates(record, [], self.AT[2])], [16288])

    def test_a_failed_gh_call_in_the_findings_query_is_a_handled_error(self):
        def fail(*args):
            raise SystemExit("gh: HTTP 502")
        with mock.patch.object(omp_pr, "gh_json", fail):
            with self.assertRaises(omp_queue.GitError):
                omp_queue.GitHub().post_merge_open([self.MERGE], cwd=".")


if __name__ == "__main__":
    unittest.main()
