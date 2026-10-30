"""rust-check's reading of cargo's JSON, its record, and the offline parts of `--ci` (the temporary
branch's commit, the workflow, a run's outcome), on cargo-shaped fixtures (#16202's Linux build).
Run: python3 -m unittest discover -s tests"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import contrib_env  # noqa: F401  (before any script module: a hermetic config)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
loader = importlib.machinery.SourceFileLoader("rust_check", os.path.join(SCRIPTS, "rust-check"))
spec = importlib.util.spec_from_loader("rust_check", loader)
RC = importlib.util.module_from_spec(spec)
loader.exec_module(RC)
import omp_queue  # noqa: E402

LIBEI = "crates/pi-natives/src/desktop/linux/wayland/libei.rs"
MOD = "crates/pi-natives/src/desktop/mod.rs"
PTY = "crates/pi-natives/src/pty.rs"


def message(level, code, text, path, line, secondary=()):
    spans = [{"file_name": path, "line_start": n, "line_end": n, "is_primary": False} for n in secondary]
    spans.append({"file_name": path, "line_start": line, "line_end": line, "is_primary": True})
    return json.dumps({"reason": "compiler-message", "message": {
        "level": level, "code": {"code": code} if code else None, "message": text, "spans": spans,
        "rendered": f"{level}: {text}\n  --> {path}:{line}\n"}})


# What `cargo clippy -p pi-natives --all-targets --message-format=json` printed on Linux for
# 8bb3284667, #16202's head before the maintainer's bf9fd4bd6a (trimmed): the closure parameter `held` shadowed
# the press counter, main's `#[ignore]` without reason, and the lib and its test target repeating
# the error.
CARGO_16202 = "\n".join([
    '{"reason":"compiler-artifact","target":{"name":"libc"}}',
    message("error", "E0618", "expected function, found `{integer}`", LIBEI, 714, secondary=(714, 706)),
    message("error", "E0618", "expected function, found `{integer}`", LIBEI, 714, secondary=(714, 706)),
    message("warning", "clippy::ignore_without_reason", "`#[ignore]` without reason", PTY, 987),
    message("warning", "clippy::significant_drop_in_scrutinee",
            "temporary with significant `Drop` in `if let` scrutinee will live until the end of the `if let` "
            "expression", MOD, 3141),
    json.dumps({"reason": "compiler-message", "message": {"level": "error", "code": None, "spans": [],
                                                          "message": "aborting due to 1 previous error"}}),
    '{"reason":"build-finished","success":false}',
])


class DiagnosticsTest(unittest.TestCase):
    def test_compile_errors_fail_anywhere_and_lints_only_on_the_branchs_lines(self):
        diags = RC.diagnostics(CARGO_16202)
        self.assertEqual([(d["path"], d["start"], d["code"]) for d in diags],
                         [(LIBEI, 714, "E0618"), (PTY, 987, "clippy::ignore_without_reason"),
                          (MOD, 3141, "clippy::significant_drop_in_scrutinee")], "once each, primary span")
        # 8bb3284667 added libei.rs:714 (`held()?;`) and the test fake's if-let at mod.rs:3141.
        failures, others = RC.judge(diags, {LIBEI: {686, 714}, MOD: {3141}})
        self.assertEqual([d["code"] for d in failures], ["E0618", "clippy::significant_drop_in_scrutinee"])
        self.assertEqual([d["path"] for d in others], [PTY], "main's lint is counted, not failed")
        failures, _ = RC.judge(diags, {})
        self.assertEqual([d["code"] for d in failures], ["E0618"], "a compile error fails wherever it is")

    def test_rustfmt_counts_only_files_the_branch_changes(self):
        out = f"/w/{LIBEI}\n/w/{PTY}\n"
        self.assertEqual(RC.unformatted(out, "/w", [LIBEI, MOD]), [LIBEI])

    def test_windows_goes_through_cargo_xwin(self):
        self.assertEqual(RC.clippy_command(True)[:5], ["cargo", "xwin", "clippy", "--target", RC.WINDOWS_TARGET])
        self.assertEqual(RC.clippy_command(False)[:2], ["cargo", "clippy"])
        self.assertIn("--all-targets", RC.clippy_command(False))


class RecordTest(unittest.TestCase):
    def test_a_pass_is_recorded_per_platform_and_old_diffs_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = omp_queue.Store(tmp, os.path.join(tmp, "queue.json"))
            RC.record(store, "old", "linux", "a" * 40, at="2026-01-01T00:00:00Z")
            RC.record(store, "d1", "linux", "b" * 40)
            RC.record(store, "d1", "windows", "c" * 40)
            checks = store.load()[0]["rust_checks"]
            self.assertEqual(sorted(checks), ["d1"], "a record no run touched in RECORD_DAYS is dropped")
            self.assertEqual({p: r["sha"][0] for p, r in checks["d1"].items()}, {"linux": "b", "windows": "c"})

    def test_a_host_that_cannot_push_prints_the_record_and_import_stores_it(self):
        # A host with no push path to the fork: its record crosses through its log.
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            RC.hand_over("d1", "macos", "e" * 40, "push denied")
        self.assertIn("rust-check --import", str(ctx.exception.code))
        log = "$ cargo clippy ...\nmacos: clippy and rustfmt pass\n" + out.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            store = omp_queue.Store(tmp, os.path.join(tmp, "queue.json"))
            with mock.patch.object(RC, "Store", lambda repo: store), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(RC.import_records(log), 1)
            row = store.load()[0]["rust_checks"]["d1"]["macos"]
            self.assertEqual((row["sha"], row["host"]), ("e" * 40, RC.this_host()))
            with self.assertRaises(SystemExit):
                RC.import_records("macos: 1 diagnostic(s)\n")


class RefusalTest(unittest.TestCase):
    """What makes a run record nothing, in a real git worktree with a fake `cargo` (a review found a
    fixed but uncommitted tree recording the broken HEAD, and a rustfmt that could not parse its
    config passing)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "w")
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(os.path.join(self.dir, "crates/a/src"))
        os.makedirs(self.bin)
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"),
                     ("config", "user.name", "t")):
            self.git(*args)
        self.write("crates/a/src/l.rs", "fn a() {}\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.write("crates/a/src/l.rs", "fn a() { b(); }\n")
        self.git("commit", "-qam", "fix(a): call b")
        self.cargo("exit 0")
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.dir, capture_output=True, text=True, check=True).stdout

    def write(self, path, text):
        with open(os.path.join(self.dir, path), "w") as f:
            f.write(text)

    def cargo(self, body):
        path = os.path.join(self.bin, "cargo")
        with open(path, "w") as f:
            f.write(f"#!/bin/sh\n{body}\n")
        os.chmod(path, 0o755)

    def main(self):
        manifest = os.path.join(self.tmp.name, "queue.json")
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}:{old}"
        try:
            with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(io.StringIO()):
                RC.main(["--base", self.base, "--manifest", manifest])
        finally:
            os.environ["PATH"] = old
        return str(ctx.exception.code), os.path.exists(manifest)

    def test_an_uncommitted_rust_change_is_refused_before_cargo_runs(self):
        self.write("crates/a/src/l.rs", "fn a() { c(); }\n")
        self.cargo("echo ran >&2; exit 0")
        why, recorded = self.main()
        self.assertIn("uncommitted changes under the Rust paths", why)
        self.assertIn("crates/a/src/l.rs", why)
        self.assertFalse(recorded)

    def test_a_rustfmt_that_cannot_run_fails_closed(self):
        self.cargo('case "$1" in fmt) echo "error: invalid rustfmt.toml" >&2; exit 1;; esac; exit 0')
        why, recorded = self.main()
        self.assertIn("cargo fmt failed without listing a file", why)
        self.assertFalse(recorded)


def git(cwd, *args, input=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, input=input).stdout


class CiBranchTest(unittest.TestCase):
    """The temporary branch `--ci` pushes: the PR head plus one commit touching only the workflows."""

    def test_the_workflow_runs_rust_checks_command_on_the_platforms_asked_for(self):
        text = RC.ci_workflow(["linux", "windows"])
        self.assertIn("platform: [linux, windows] #", text, "the matrix line is narrowed, its comment kept")
        self.assertIn("omp-contrib-ci/**", text)
        with open(RC.CI_TEMPLATE) as f:
            template = f.read()
        self.assertIn("platform: [linux, macos, windows]", template)
        # The workflow's clippy is clippy_command(False): CI and a local run check the same thing.
        self.assertIn(" ".join(RC.clippy_command(False)), template)
        self.assertIn("cargo fmt --all -- --check --files-with-diff", template)
        with tempfile.NamedTemporaryFile("w", suffix=".yml") as f:
            f.write("on: push\n")
            f.flush()
            with self.assertRaises(ValueError):
                RC.ci_workflow(["linux"], f.name)

    def test_the_branch_name_carries_the_head(self):
        self.assertEqual(RC.ci_branch("0123456789abcdef" * 2, "beef"), "omp-contrib-ci/0123456789ab-beef")
        self.assertNotEqual(RC.ci_branch("a" * 40), RC.ci_branch("a" * 40), "each run gets its own branch")

    def test_the_commit_adds_the_workflow_drops_the_others_and_leaves_the_worktree_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"),
                         ("config", "user.name", "t")):
                git(tmp, *args)
            os.makedirs(os.path.join(tmp, ".github/workflows"))
            os.makedirs(os.path.join(tmp, "crates/a/src"))
            for rel, text in ((".github/workflows/ci.yml", "on: push\n"), (".github/workflows/nix.yml", "on: push\n"),
                              ("crates/a/src/l.rs", "fn a() {}\n")):
                with open(os.path.join(tmp, rel), "w") as f:
                    f.write(text)
            git(tmp, "add", "-A")
            git(tmp, "commit", "-qm", "head")
            head = git(tmp, "rev-parse", "HEAD").strip()
            with open(os.path.join(tmp, "crates/a/src/l.rs"), "w") as f:
                f.write("fn a() { b(); }\n")  # an uncommitted edit stays out of the commit
            commit = RC.ci_commit(tmp, head, "name: x\n")
            self.assertEqual(git(tmp, "rev-parse", f"{commit}^").strip(), head, "the PR head is its parent")
            self.assertEqual(git(tmp, "diff", "--name-status", head, commit).split("\n")[:3],
                             ["D\t.github/workflows/ci.yml", "D\t.github/workflows/nix.yml",
                              f"A\t{RC.CI_WORKFLOW}"])
            self.assertEqual(git(tmp, "show", f"{commit}:{RC.CI_WORKFLOW}"), "name: x\n")
            self.assertEqual(git(tmp, "status", "--porcelain"), " M crates/a/src/l.rs\n", "index and tree untouched")
            self.assertEqual(git(tmp, "rev-parse", "HEAD").strip(), head)


class CiOutcomeTest(unittest.TestCase):
    """How a run's jobs and artifacts become a verdict and a record."""

    def artifact(self, tmp, head, root, fmt=(0, "", ""), clippy=(0, "", "")):
        os.makedirs(tmp, exist_ok=True)
        files = {"head": head + "\n", "root": root + "\n", "toolchain": "nightly-2026-10-06\n"}
        for step, (code, out, err) in (("fmt", fmt), ("clippy", clippy)):
            files |= {f"{step}.code": f"{code}\n", f"{step}.out": out, f"{step}.err": err}
        for name, text in files.items():
            with open(os.path.join(tmp, name), "w") as f:
                f.write(text)
        return RC.read_artifact(tmp)

    def test_a_job_that_gives_no_verdict_says_why(self):
        self.assertIsNone(RC.job_failure({"status": "completed", "conclusion": "success"}))
        cases = {
            ("queued", None, True): "no runner picked the job up",
            ("in_progress", None, True): "still running at the deadline",
            ("completed", "timed_out", False): "timeout-minutes",
            ("completed", "cancelled", False): "no GitHub-hosted runner picked the job up",
            ("completed", "skipped", False): "ended skipped",
        }
        for (status, conclusion, late), want in cases.items():
            self.assertIn(want, RC.job_failure({"status": status, "conclusion": conclusion}, late))
        failed = {"status": "completed", "conclusion": "failure",
                  "steps": [{"name": "Set up job", "conclusion": "success"},
                            {"name": "Toolchain (rust-toolchain.toml)", "conclusion": "failure"}]}
        self.assertEqual(RC.job_failure(failed), "setup failed at step 'Toolchain (rust-toolchain.toml)', "
                                                 "before cargo's verdict")
        # A run's macOS arm64 job, 2026-10-30: cancelled by GitHub, no runner, no steps.
        unacquired = {"name": "rust-check macos", "status": "completed", "conclusion": "cancelled",
                      "runner_name": "", "steps": []}
        self.assertIn("runner capacity); rerun later with --platform macos", RC.job_failure(unacquired))
        self.assertEqual(RC.job_failure(unacquired | {"runner_name": "GitHub Actions 7",
                                                      "steps": [{"name": "Set up job"}]}), "the run was cancelled")
        self.assertEqual(RC.job_platform({"name": "rust-check windows"}), "windows")

    def test_actions_off_on_the_fork_names_the_command_and_changes_nothing(self):
        self.assertIsNone(RC.actions_refusal("o/r", {"enabled": True, "allowed_actions": "all"}))
        why = RC.actions_refusal("o/r", {"enabled": False})
        self.assertIn("gh api -X PUT repos/o/r/actions/permissions -F enabled=true", why)
        self.assertIn("allowed_actions=all", RC.actions_refusal("o/r", {"enabled": True, "allowed_actions": "local_only"}))

    def test_a_windows_runners_paths_are_judged_like_a_local_run(self):
        sha = "f" * 40
        win = LIBEI.replace("/", "\\")
        clippy = message("warning", "clippy::needless_return", "unneeded `return`", win, 714)
        fmt_out = f"\\\\?\\D:\\a\\oh-my-pi\\oh-my-pi\\{win}\n"  # rustfmt on a windows-2025 runner: a verbatim path
        with tempfile.TemporaryDirectory() as tmp:
            art = self.artifact(tmp, sha, "D:\\a\\oh-my-pi\\oh-my-pi", fmt=(1, fmt_out, ""), clippy=(0, clippy, ""))
            ok, lines, verdict = RC.ci_verdict("windows", art, sha, {LIBEI: {714}})
        self.assertFalse(ok)
        self.assertIn(f"rustfmt: {LIBEI} is not formatted: cargo fmt -- {LIBEI}", lines)
        self.assertIn("1 diagnostic(s) on this branch's lines", verdict)

    def test_an_artifact_of_another_commit_or_without_exit_codes_records_nothing(self):
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as tmp:
            art = self.artifact(tmp, "b" * 40, "/w")
            self.assertIn("not aaaaaaaaaa", RC.ci_verdict("linux", art, sha, {})[2])
            self.artifact(tmp, sha, "/w")
            os.remove(os.path.join(tmp, "clippy.code"))  # the step died before cargo exited
            art = RC.read_artifact(tmp)
            self.assertIn("no cargo exit code", RC.ci_verdict("linux", art, sha, {})[2])
            art = self.artifact(tmp, sha, "/home/runner/work/oh-my-pi/oh-my-pi")
            self.assertEqual(RC.ci_verdict("linux", art, sha, {LIBEI: {1}}), (True, [], None))

    def test_passing_platforms_are_recorded_as_ci_for_the_pr_head_and_failures_listed(self):
        sha = "c" * 40
        run = {"id": 7, "html_url": "https://github.com/o/r/actions/runs/7", "status": "completed"}
        jobs = [{"name": "rust-check linux", "status": "completed", "conclusion": "success",
                 "html_url": "https://github.com/o/r/actions/runs/7/job/1",
                 "started_at": "2026-10-30T10:00:00Z", "completed_at": "2026-10-30T10:12:05Z"},
                {"name": "rust-check windows", "status": "completed", "conclusion": "failure",
                 "html_url": "https://github.com/o/r/actions/runs/7/job/2",
                 "steps": [{"name": "System libraries (Linux)", "conclusion": "failure"}]}]
        with tempfile.TemporaryDirectory() as tmp:
            manifest = os.path.join(tmp, "queue.json")

            def download(cmd, **kw):
                self.artifact(cmd[cmd.index("-D") + 1], sha, "/home/runner/work/oh-my-pi/oh-my-pi")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            args = RC.argparse.Namespace(no_record=False, manifest=manifest)
            ctx = {"root": tmp, "sha": sha, "diff_id": "d1", "added": {LIBEI: {714}}}
            with mock.patch.object(RC.subprocess, "run", download), contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(SystemExit) as raised:
                RC.ci_collect(args, "o/r", run, jobs, ["linux", "windows"], False, ctx)
            self.assertIn("windows: setup failed at step 'System libraries (Linux)'", str(raised.exception.code))
            row = omp_queue.Store(tmp, manifest).load()[0]["rust_checks"]["d1"]
        self.assertEqual(sorted(row), ["linux"])
        self.assertEqual(row["linux"]["sha"], sha, "the PR head, not the temporary commit")
        self.assertEqual((row["linux"]["host"], row["linux"]["run"]), ("ci", jobs[0]["html_url"]))


class PlacementTest(unittest.TestCase):
    def test_each_placement_names_where_the_check_runs(self):
        self.assertEqual(RC.where("linux", "ssh:buildbox"),
                         "scripts/rust-check in the PR's worktree on buildbox (`ssh buildbox`)")
        self.assertEqual(RC.where("windows", "local"), "scripts/rust-check --windows in the PR's worktree here")
        self.assertEqual(RC.where("macos", "ci"), "scripts/rust-check --ci --platform macos")
        self.assertIn("unchecked", RC.where("macos", "none"))
        steps = RC.next_steps({"linux", "windows"}, {"linux"}, {"linux": "local", "macos": "local", "windows": "ci"})
        self.assertEqual(steps, ["  windows (build.windows = ci): scripts/rust-check --ci --platform windows"])


if __name__ == "__main__":
    unittest.main()
