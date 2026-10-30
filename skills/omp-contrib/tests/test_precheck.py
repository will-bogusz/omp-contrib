"""precheck's preparation checks (code-style.md), each run on a real git diff in a
scratch repo. Run: python3 -m unittest discover -s tests"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
loader = importlib.machinery.SourceFileLoader("precheck", os.path.join(SCRIPTS, "precheck"))
spec = importlib.util.spec_from_loader("precheck", loader)
PC = importlib.util.module_from_spec(spec)
loader.exec_module(PC)
import omp_config  # noqa: E402
import omp_pr  # noqa: E402


class IssueLinkTest(unittest.TestCase):
    def test_color_literals_are_not_issue_numbers(self):
        pr = {"number": 999, "body": "colors #000000 #123abc #abcdef #123456; see #123 and /issues/456",
              "closingIssuesReferences": []}
        with mock.patch.object(PC, "gh_json", return_value={"state": "closed"}) as gh:
            PC.check_links(pr)
        self.assertEqual([call.args[-1] for call in gh.call_args_list],
                         ["repos/can1357/oh-my-pi/issues/123", "repos/can1357/oh-my-pi/issues/456"])

AX_BEFORE = """pub(super) fn window_records(pid: libc::pid_t) -> Option<Vec<AxWindowRecord>> {
\tlet app = probe_application(pid)?;
\tenable_web_accessibility(pid, &app);
\tlet windows = copy_elements_optional(&app, "AXWindows")?;
\tlog_windows(&windows);
\tSome(records(windows))
}
"""
# The #15604 shape: one call dropped, one moved into a helper module verbatim, one changed.
AX_AFTER = """pub(super) fn window_records(pid: libc::pid_t) -> Option<Vec<AxWindowRecord>> {
\tlet app = probe_application(pid)?;
\tlet windows = copy_elements_optional(&app, "AXWindows")?;
\tSome(records(windows))
}
"""
HELPER = """pub(super) fn trace(windows: &[AXUIElement]) {
\tlog_windows(&windows);
}
"""
ENTRY_FIELDS = ["activeLeafId", "parentSession", "firstKeptEntryId", "stopReason", "customType", "targetId",
                "thinkingLevel", "serviceTier", "previousTitle", "modelRole", "shortSummary", "errorMessage"]


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


class Repo:
    def __init__(self, tmp):
        self.dir = tmp
        sh(tmp, "git", "init", "-q", "-b", "main")
        sh(tmp, "git", "config", "user.email", "t@example.com")
        sh(tmp, "git", "config", "user.name", "T")

    def write(self, path, text):
        full = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)

    def commit(self, subject, files):
        for path, text in files.items():
            self.write(path, text)
        sh(self.dir, "git", "add", "-A")
        sh(self.dir, "git", "commit", "-q", "-m", subject)
        return sh(self.dir, "git", "rev-parse", "HEAD").strip()


def notes(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args)
    return [line for line in out.getvalue().splitlines() if line.startswith("NOTE")]


class PrecheckPrepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_removed_call_statement_is_listed_unless_added_back(self):
        base = self.repo.commit("init", {"crates/n/src/ax.rs": AX_BEFORE, "crates/n/tests/ax.rs": "\tcheck(1);\n"})
        self.repo.commit("refactor(natives): split ax", {"crates/n/src/ax.rs": AX_AFTER, "crates/n/src/trace.rs": HELPER,
                                                         "crates/n/tests/ax.rs": "\n"})
        out = notes(PC.check_removed_calls, PC.Diff(base, "HEAD", self.repo.dir))
        self.assertEqual(len(out), 1, out)
        self.assertIn("crates/n/src/ax.rs:3 in pub(super) fn window_records", out[0])
        self.assertIn("enable_web_accessibility(pid, &app);", out[0])

    def test_removed_calls_of_a_deleted_file_are_listed(self):
        base = self.repo.commit("init", {"packages/a/src/x.ts": "export function f() {\n\tstartWatcher(dir);\n}\n"})
        sh(self.repo.dir, "git", "rm", "-q", "packages/a/src/x.ts")
        sh(self.repo.dir, "git", "commit", "-q", "-m", "refactor(a): drop x")
        out = notes(PC.check_removed_calls, PC.Diff(base, "HEAD", self.repo.dir))
        self.assertEqual([("packages/a/src/x.ts:2" in o and "startWatcher(dir);" in o) for o in out], [True], out)

    def test_commit_scoped_outside_the_title_is_flagged(self):
        base = self.repo.commit("init", {"crates/n/src/d.rs": "fn a() {}\n", "packages/c/test/s.test.ts": "\n"})
        self.repo.commit("fix(natives): release the hold", {"crates/n/src/d.rs": "fn a() { b(); }\n"})
        self.repo.commit("test(natives): cover the hold", {"crates/n/tests/d.rs": "fn t() {}\n"})
        self.repo.commit("test(coding-agent): pin each notice flag", {"packages/c/test/s.test.ts": "it();\n"})
        self.repo.commit("docs(natives,coding-agent): attribute", {"packages/c/CHANGELOG.md": "- x\n"})
        commits = PC.branch_commits(base, "HEAD", self.repo.dir)
        out = notes(PC.check_scope, commits, "fix(natives): release the display-awake hold")
        self.assertEqual(len(out), 1, out)
        self.assertIn("test(coding-agent): pin each notice flag", out[0])
        self.assertIn("test-only commit scoped coding-agent", out[0])

    def test_a_commit_naming_a_pr_as_hash_n_is_noted(self):
        base = self.repo.commit("init", {"packages/c/src/x.ts": "\n"})
        named = self.repo.commit("fix(c): take #15191's mode", {"packages/c/src/x.ts": "a\n"})
        linked = self.repo.commit("docs(c): link\n\nSee can1357/oh-my-pi#15193.", {"packages/c/src/x.ts": "b\n"})
        self.repo.commit("fix(c): name PR 15191 plainly", {"packages/c/src/x.ts": "c\n"})
        out = notes(PC.check_refs, base, "HEAD", self.repo.dir)
        self.assertEqual([o.split()[2] for o in out], [named[:10], linked[:10]], out)
        self.assertIn("fix(c): take #15191's mode: names a PR as #N", out[0])
        self.assertIn("docs(c): link:", out[1])

    def test_assertion_on_script_text_is_flagged_and_a_real_run_is_not(self):
        base = self.repo.commit("init", {"packages/c/src/x.ts": "\n"})
        self.repo.commit("fix(c): body", {"packages/c/test/cmux.test.ts": (
            "for (const script of scripts) expect(script).toContain('\"body\"');\n"
            "const src = readFileSync(path.join(import.meta.dir, \"../src/tab.ts\"), \"utf8\");\n"
            "expect(fn.toString()).toMatch(/body/);\n"
            "expect(await tab.text()).toBe(\"page\");\n"
            "expect(reads).toEqual([[parseSelector(\"body\"), \"text\"]]);\n")})
        out = notes(PC.check_text_tests, PC.Diff(base, "HEAD", self.repo.dir).added)
        self.assertEqual([o.split()[2] for o in out], [f"packages/c/test/cmux.test.ts:{n}" for n in (1, 2, 3)], out)

    def test_inline_import_is_a_fix_unless_the_file_already_loads_lazily_on_main(self):
        registry = "const loaders = {\n\tbrave: () => import(\"./brave\"),\n};\n"
        base = self.repo.commit("init", {"packages/c/src/registry.ts": registry, "packages/c/src/plain.ts": "\n"})
        self.repo.commit("feat(c): factory", {
            "packages/c/src/registry.ts": registry.replace("};", "\tfactory: () => import(\"./factory\"),\n};"),
            "packages/c/src/plain.ts": "const m = await import(\"./m\");\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            PC.check_code(PC.Diff(base, "HEAD", self.repo.dir).added, base, self.repo.dir)
        lines = [line.split()[:3] for line in out.getvalue().splitlines()]
        self.assertIn(["FIX", "import()", "packages/c/src/plain.ts:1"], lines)
        self.assertIn(["NOTE", "import()", "packages/c/src/registry.ts:3"], lines)

    def timing(self):
        base = self.repo.commit("init", {"packages/c/src/x.ts": "\n"})
        self.repo.commit("test(c): timing", {
            "packages/c/test/wall.test.ts": (
                "await Bun.sleep(50);\n"
                "const start = performance.now();\n"
                "expect(elapsedMs).toBeLessThan(200);\n"
                "setTimeout(resolve, 30);\n"
                "expect(count).toBeGreaterThan(2);\n"
                "await done.promise; await Bun.sleep(0);\n"
                "}, 20_000);\n"),
            "packages/c/test/fake.test.ts": "jest.useFakeTimers();\nsetTimeout(resolve, 30);\n",
            "crates/n/src/lib.rs": "#[cfg(test)]\nconst fn probe() {}\nfn live() { std::thread::sleep(PAUSE); }\n\n"
                                   "#[cfg(test)]\nmod tests {\n"
                                   "\tfn waits() { let t = Instant::now(); assert!(t.elapsed() < LIMIT); }\n"
                                   "\tfn epoch() { let t0 = Instant::now(); assert!(place(t0, t0 + ms(30))); }\n}\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            PC.check_timing(PC.Diff(base, "HEAD", self.repo.dir).added, "HEAD", self.repo.dir)
        return [line.split()[:3] for line in out.getvalue().splitlines()]

    def test_wall_clock_test_lines_are_fixes_and_fake_timers_or_product_code_are_not(self):
        lines = self.timing()
        self.assertEqual(lines, [
            ["FIX", "timing", "crates/n/src/lib.rs:7"],
            *[["FIX", "timing", f"packages/c/test/wall.test.ts:{n}"] for n in (1, 2, 3, 4)],
            ["NOTE", "timing", "packages/c/test/wall.test.ts:7"]])

    def test_new_type_field_lists_field_readers_that_miss_it(self):
        entries = "export interface EntryBase {\n\ttype: string;\n\tid: string;\n}\n\n" + \
            "export interface Rich extends EntryBase {\n" + "".join(f"\t{f}?: string;\n" for f in ENTRY_FIELDS) + "}\n"
        rules = "const RULES = {\n" + "".join(f"\t{f}: \"keep\",\n" for f in ENTRY_FIELDS) + "};\n"
        base = self.repo.commit("init", {"packages/c/src/session/entries.ts": entries,
                                         "packages/c/src/session/anonymizer.ts": rules,
                                         "packages/c/src/session/manager.ts": rules,
                                         "packages/c/src/other.ts": "const x = { parentSession: 1, stopReason: 2 };\n"})
        self.repo.commit("feat(c): record the build", {
            "packages/c/src/session/entries.ts": entries.replace("\tid: string;\n", "\tid: string;\n\truntime?: Build;\n"),
            "packages/c/src/session/manager.ts": rules.replace("};", "\truntime: \"keep\",\n};")})
        out = notes(PC.check_consumers, PC.Diff(base, "HEAD", self.repo.dir), "HEAD", self.repo.dir)
        self.assertEqual(len(out), 1, out)
        self.assertIn("packages/c/src/session/anonymizer.ts", out[0])
        self.assertIn("but not new runtime", out[0])

    def changelog_lines(self, base):
        diff = PC.Diff(base, "HEAD", self.repo.dir)
        fresh = PC.unreleased_code(diff, base, "HEAD", self.repo.dir)
        out = io.StringIO()
        PC.findings.clear()
        with contextlib.redirect_stdout(out):
            PC.check_changelogs(diff.added, "HEAD", self.repo.dir, None, fresh)
        return out.getvalue().splitlines()

    LOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n\n- old\n"

    def test_fix_of_a_regression_no_release_shipped_needs_no_entry(self):
        # #15941: the default `start` an unreleased commit wrote is what the fix rewrites.
        self.repo.commit("init", {"packages/c/src/power.ts": "start = options => PowerAssertion.start(options);\n",
                                  "packages/c/CHANGELOG.md": self.LOG})
        sh(self.repo.dir, "git", "tag", "v1.0.0")
        base = self.repo.commit("fix(c): log a missing backend once", {
            "packages/c/src/power.ts": "start = PowerAssertion.start;\n"})
        self.repo.commit("fix(c): call start bound", {
            "packages/c/src/power.ts": "start = options => PowerAssertion.start(options);\n"})
        out = self.changelog_lines(base)
        self.assertEqual([l.split()[0] for l in out], ["NOTE"], out)
        self.assertIn("no entry", out[0])
        self.repo.commit("docs(c): entry", {"packages/c/CHANGELOG.md": self.LOG.replace(
            "## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- Fixed sleep prevention\n")})
        out = self.changelog_lines(base)
        self.assertEqual([l.split()[0] for l in out], ["NOTE"], out)
        self.assertIn("drop the entry", out[0])

    def test_fix_of_released_code_still_needs_an_entry(self):
        self.repo.commit("init", {"packages/c/src/power.ts": "start = PowerAssertion.start;\n",
                                  "packages/c/CHANGELOG.md": self.LOG})
        base = self.repo.commit("feat(c): later work", {"packages/c/src/other.ts": "x();\n"})
        sh(self.repo.dir, "git", "tag", "v1.0.0")
        self.repo.commit("fix(c): call start bound", {
            "packages/c/src/power.ts": "start = options => PowerAssertion.start(options);\n"})
        out = self.changelog_lines(base)
        self.assertEqual([l.split()[:2] for l in out], [["FIX", "changelog"]], out)

    def test_a_release_that_already_holds_the_fix_does_not_count_as_shipping_the_bug(self):
        # v18.11.2 shipped both #14591's line and #15941's fix: the bug still never reached a user.
        self.repo.commit("init", {"packages/c/src/power.ts": "start = ok;\n", "packages/c/CHANGELOG.md": self.LOG})
        base = self.repo.commit("fix(c): regress", {"packages/c/src/power.ts": "start = broken;\n"})
        self.repo.commit("fix(c): repair", {"packages/c/src/power.ts": "start = ok;\n"})
        sh(self.repo.dir, "git", "tag", "v1.0.1")
        out = self.changelog_lines(base)
        self.assertEqual([l.split()[0] for l in out], ["NOTE"], out)

    def test_a_fix_rewriting_released_and_unreleased_lines_names_the_unreleased_commit(self):
        # inflight-epoch: #15947's early return (unreleased) and an older released decrement, rewritten together.
        self.repo.commit("init", {"packages/c/src/s.ts": "count--;\nsettle();\n", "packages/c/CHANGELOG.md": self.LOG})
        sh(self.repo.dir, "git", "tag", "v1.0.0")
        base = self.repo.commit("fix(session): stamp brackets", {"packages/c/src/s.ts": "if (old) return;\ncount--;\n"
                                                                                         "settle();\n"})
        self.repo.commit("fix(c): settle a turn begun during abort", {"packages/c/src/s.ts": "if (!old) count--;\n"
                                                                                              "settle();\n"})
        out = self.changelog_lines(base)
        self.assertEqual([l.split()[0] for l in out], ["NOTE"], out)
        self.assertIn("fix(session): stamp brackets", out[0])
        self.assertNotIn(" init", out[0])


class PrecheckBodyTest(unittest.TestCase):
    BODY = "## What\n\nI fixed it.\n\n{chart}\n\n## Why\n\n{prose}\n\n## Testing\n\nRan it.\n"

    def length_findings(self, chart, prose):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            PC.check_body(self.BODY.format(chart=chart, prose=prose))
        return [line for line in out.getvalue().splitlines() if "length" in line]

    def test_a_chart_costs_no_more_than_the_table_it_replaces(self):
        url = "https://github.com/user-attachments/assets/00000000-0000-4000-8000-000000000000"
        picture = (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="{url}">\n'
                   f'  <img width="780" height="390" alt="{"takeaway " * 60}" src="{url}">\n</picture>')
        prose = "x" * 2900
        self.assertEqual(self.length_findings(picture, prose), [])
        self.assertEqual(self.length_findings(f"![{'alt ' * 40}]({url})", prose), [])
        self.assertEqual(len(self.length_findings("", "x" * 3100)), 1)

    def test_a_picture_and_the_blank_lines_around_it_add_nothing(self):
        # #15293: a picture placed between two paragraphs left its two blank lines behind, 2,999 -> 3,001.
        before = "## What\n\nI fixed it.\n\nNext paragraph.\n"
        after = before.replace("\n\nNext", "\n\n<picture>\n  <img alt=\"a\" src=\"u\">\n</picture>\n\n"
                               "<details><summary>Exact</summary>\n\n| a |\n|---|\n\n</details>\n\nNext")
        self.assertEqual(PC.prose_length(after), PC.prose_length(before))

    def test_a_video_line_and_its_blank_lines_add_nothing_but_a_url_in_a_sentence_counts(self):
        url = "https://github.com/user-attachments/assets/00000000-0000-4000-8000-000000000000"
        before = "## What\n\nI fixed it.\n\nNext paragraph.\n"
        self.assertEqual(PC.prose_length(before.replace("\n\nNext", f"\n\n{url}\n\nNext")), PC.prose_length(before))
        self.assertGreater(PC.prose_length(before.replace("Next", f"See {url}. Next")), PC.prose_length(before) + 80)


def printed(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args)
    return out.getvalue().splitlines()


class PrecheckBehaviorEvalTest(unittest.TestCase):
    PROMPT = {"packages/coding-agent/src/prompts/tools/todo.md": [(1, "With parallel tool calls, todo ...")]}
    BODY = "## What\n\nI changed it.\n\n## Testing\n\n{testing}\n\n---\n\n- [x] Tested locally (Opus said fine)\n"

    def kinds(self, added, body):
        return [line.split()[0] for line in printed(PC.check_behavior_eval, added, body) if " behavior " in line]

    def test_an_agent_facing_change_is_advised_until_both_families_ran(self):
        # #16231: prompt-only, checked by rendering tests, no model run.
        self.assertEqual(self.kinds(self.PROMPT, self.BODY.format(testing="Prompt-only change, so no new test.")), ["NOTE"])
        self.assertEqual(self.kinds(self.PROMPT, self.BODY.format(testing="Haiku 5.5, n=10 per arm: 0.1 -> 0.1.")), ["NOTE"])
        # A family named only in the checklist below `---` (Opus here) is not a run.
        self.assertEqual(self.kinds(self.PROMPT, self.BODY.format(testing="GPT-6.1 Sol, n=10 per arm: 0.1 -> 0.1.")), ["NOTE"])
        self.assertEqual(self.kinds(self.PROMPT, self.BODY.format(
            testing="Haiku 5.5 and GPT-6.1 Sol, n=10 per arm: todo-only turns 0.1 -> 0.1.")), [])
        self.assertEqual(self.kinds(self.PROMPT, None), ["NOTE"])

    def test_tool_code_counts_and_paths_no_model_sees_do_not(self):
        tool = {"packages/coding-agent/src/tools/browser/prelude.js": [(1, "x")]}
        self.assertEqual(self.kinds(tool, self.BODY.format(testing="Ran it.")), ["NOTE"])
        self.assertEqual(self.kinds({"packages/coding-agent/src/session/agent-storage.ts": [(1, "x")],
                                     "packages/coding-agent/docs/todo.md": [(1, "x")],
                                     "packages/coding-agent/test/tools/todo.test.ts": [(1, "x")]},
                                    self.BODY.format(testing="")), [])

    def test_configured_behaviour_models_must_each_be_named(self):
        path = contrib_env.write_config(os.path.join(tempfile.mkdtemp(dir=contrib_env.ROOT), "config.toml"),
                                        '[models]\nbehaviour = ["anthropic/claude-haiku-4-5", "openai/gpt-5.1-codex"]\n')
        with mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": path}):
            omp_config.load(reload=True)
            try:
                lines = printed(PC.check_behavior_eval, self.PROMPT, self.BODY.format(testing="claude-haiku-4-5: 0.1 -> 0.1."))
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("with anthropic/claude-haiku-4-5 and openai/gpt-5.1-codex", lines[0])
                self.assertIn("not named: openai/gpt-5.1-codex", lines[0])
                self.assertEqual(self.kinds(self.PROMPT, self.BODY.format(
                    testing="claude-haiku-4-5 and gpt-5.1-codex, n=10 per arm: 0.1 -> 0.1.")), [])
            finally:
                omp_config.load(reload=True)


# The #16390 shape (6a24977a45..168ceaabdf): a relay-guidance template rendering `browser.cdpUrl`.
PRELUDE_BEFORE = """import browserDescription from "../../prompts/tools/browser.md" with { type: "text" };

export function createBrowserPreludeDefinition(session: ToolSession, host: Host): EvalPreludeDefinition {
\treturn {
\t\tname: "browser",
\t\tdocumentation: browserDescription,
\t};
}
"""
PRELUDE_OURS = """import browserDescription from "../../prompts/tools/browser.md" with { type: "text" };

export function createBrowserPreludeDefinition(session: ToolSession, host: Host): EvalPreludeDefinition {
\tconst fallback = host.relayFallback;
\treturn {
\t\tname: "browser",
\t\tdocumentation: browserDescription,
\t\tguidance: fallback
\t\t\t? prompt.render(relayGuidance, {
\t\t\t\t\tcdpUrl: fallback.kind === "connected" ? fallback.cdpUrl : undefined,
\t\t\t\t\ttern: fallback.kind === "tern",
\t\t\t\t})
\t\t\t: undefined,
\t};
}
"""
PRELUDE_MAINTAINER = PRELUDE_OURS.replace("? fallback.cdpUrl :", "? redactUrlForLog(fallback.cdpUrl) :")
RELAY_MD = "# Browser Relay\n\n{{#if cdpUrl}}Pass `app: { relay: false }` to open at `browser.cdpUrl` ({{cdpUrl}}).{{/if}}\n"


class PrecheckPromptValueTest(unittest.TestCase):
    PRELUDE = "packages/coding-agent/src/tools/browser/prelude-definition.ts"
    TEMPLATE = "packages/coding-agent/src/prompts/system/browser-relay.md"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.tmp.name)
        self.base = self.repo.commit("init", {self.PRELUDE: PRELUDE_BEFORE})

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        diff = PC.Diff(self.base, "HEAD", self.repo.dir)
        return notes(PC.check_prompt_values, diff.added, "HEAD", self.repo.dir)

    def test_a_url_setting_rendered_into_the_prompt_unredacted_is_noted(self):
        self.repo.commit("fix(coding-agent): relay guidance", {self.PRELUDE: PRELUDE_OURS, self.TEMPLATE: RELAY_MD})
        out = self.check()
        self.assertEqual(len(out), 1, out)
        self.assertIn(f"{self.PRELUDE}:10", out[0])
        self.assertIn("`cdpUrl: fallback.kind === \"connected\" ? fallback.cdpUrl : undefined` goes into a prompt", out[0])

    def test_the_redacted_value_the_maintainer_shipped_is_not(self):
        self.repo.commit("fix(coding-agent): relay guidance", {self.PRELUDE: PRELUDE_MAINTAINER, self.TEMPLATE: RELAY_MD})
        self.assertEqual(self.check(), [])

    def test_a_redacted_argument_does_not_hide_another_call_passing_the_same_name_raw(self):
        other = "packages/coding-agent/src/tools/browser/relay-panel.ts"  # sorts after the raw caller
        second = PRELUDE_MAINTAINER.replace("createBrowserPreludeDefinition", "createOther")
        self.repo.commit("fix(coding-agent): relay guidance", {self.PRELUDE: PRELUDE_OURS, other: second,
                                                               self.TEMPLATE: RELAY_MD})
        out = self.check()
        self.assertEqual(len(out), 1, out)
        self.assertIn(f"{self.PRELUDE}:10", out[0])

    def test_a_template_rendering_a_url_whose_caller_the_diff_leaves_alone_is_noted(self):
        self.repo.commit("fix(coding-agent): relay guidance", {self.TEMPLATE: RELAY_MD})
        out = self.check()
        self.assertEqual(len(out), 1, out)
        self.assertIn(f"{self.TEMPLATE}:3  renders {{{{cdpUrl}}}}", out[0])

    def test_names_are_split_into_words(self):
        self.assertLessEqual({"cdp", "url"}, PC.name_words("cdpUrl"))
        self.assertIn("apikey", PC.name_words("OPENAI_API_KEY"))
        self.assertNotIn("url", PC.name_words("security"))


class PrecheckRustTest(unittest.TestCase):
    MOD = "crates/pi-natives/src/desktop/mod.rs"
    WAYLAND = "crates/pi-natives/src/desktop/linux/wayland/libei.rs"
    MACOS = "crates/pi-natives/src/desktop/macos/key_reroute.rs"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.tmp.name)
        self.base = self.repo.commit("init", {self.MOD: "fn a() {}\n", self.WAYLAND: "fn w() {}\n",
                                              self.MACOS: "fn m() {}\n", "packages/natives/CHANGELOG.md": "# C\n"})

    def tearDown(self):
        self.tmp.cleanup()

    def platforms(self):
        return PC.rust_platforms(PC.Diff(self.base, "HEAD", self.repo.dir), self.base, "HEAD", self.repo.dir)

    def test_platforms_follow_the_paths_and_cfg_lines_the_diff_touches(self):
        self.assertEqual(self.platforms(), set())
        self.repo.commit("fix(natives): wayland", {self.WAYLAND: "fn w() { hold(); }\n"})
        self.assertEqual(self.platforms(), {"linux"})
        self.repo.commit("fix(natives): reroute", {self.MACOS: "const fn m() {}\n"})
        self.assertEqual(self.platforms(), {"linux", "macos"})
        self.repo.commit("fix(natives): win", {self.MOD: "fn a() {}\n#[cfg(target_os = \"windows\")]\nfn b() {}\n"})
        self.assertEqual(self.platforms(), {"linux", "macos", "windows"})

    def test_a_change_inside_an_existing_gate_needs_that_platform(self):
        # mod.rs is shared, but its macOS-only functions build only there: a call changed inside one
        # needs the macOS run though the diff adds no cfg line (reviewer, 2026-10-20).
        gated = ("#[cfg(target_os = \"macos\")]\nfn mac() {\n    mac_call();\n}\n\n"
                 "#[cfg(\n    windows,\n)]\nmod win {\n    fn w() {\n        win_call(\"}\");\n    }\n}\n\n"
                 "fn shared() {\n    shared_call();\n}\n")
        self.assertEqual({n: p for n, p in omp_pr.gated_lines(gated).items() if n in (3, 11, 16)},
                         {3: {"macos"}, 11: {"windows"}}, "a cfg attribute may span lines; a string brace is no brace")
        self.base = self.repo.commit("seed", {self.MOD: gated})
        for change, want in ((("shared_call", "shared_new"), {"linux"}),
                             (("mac_call", "mac_new"), {"linux", "macos"}),
                             (("        win_call(\"}\");\n", ""), {"linux", "windows"})):  # read at the base
            self.repo.commit(f"fix(natives): {want}", {self.MOD: gated.replace(*change)})
            self.assertEqual(self.platforms(), want, change)

    def test_the_rust_diff_id_is_whitespace_exact_and_keeps_across_a_rebase_nearby(self):
        lines = "".join(f"fn f{i}() {{}}\n" for i in range(10))
        self.base = self.repo.commit("seed", {self.MOD: lines})
        self.repo.commit("fix(natives): x", {self.MOD: lines.replace("fn f5() {}", "fn f5() { let x = 1; }")})
        first = PC.rust_diff_id(self.base, "HEAD", self.repo.dir)
        self.repo.commit("fix(natives): space", {self.MOD: lines.replace("fn f5() {}", "fn f5() { let x =  1; }")})
        self.assertNotEqual(PC.rust_diff_id(self.base, "HEAD", self.repo.dir), first, "whitespace counts")
        # main moves a line three above ours: the same change replayed onto it keeps its id.
        moved = lines.replace("fn f2() {}", "fn f2() { main(); }")
        new_base = self.repo.commit("main", {self.MOD: moved})
        self.repo.commit("fix(natives): x again", {self.MOD: moved.replace("fn f5() {}", "fn f5() { let x = 1; }")})
        self.assertEqual(PC.rust_diff_id(new_base, "HEAD", self.repo.dir), first)

    def test_the_rust_diff_id_ignores_the_hosts_git_config(self):
        # 2026-10-20: two hosts keyed #16553's records differently; any config a host sets
        # must leave the id alone.
        self.repo.commit("fix(natives): wayland", {self.WAYLAND: "fn w() { hold(); }\n"})
        self.repo.commit("refactor(natives): move", {self.WAYLAND: "fn w() { hold(); }\n",
                                                     "crates/pi-natives/src/desktop/linux/x.rs": "fn w() {}\n"})
        first = PC.rust_diff_id(self.base, "HEAD", self.repo.dir)
        for key, value in (("core.abbrev", "12"), ("diff.renames", "copies"), ("diff.noprefix", "true"),
                           ("diff.mnemonicPrefix", "true"), ("diff.algorithm", "histogram")):
            sh(self.repo.dir, "git", "config", key, value)
            self.assertEqual(PC.rust_diff_id(self.base, "HEAD", self.repo.dir), first, key)

    def test_a_record_holds_across_a_changelog_commit_not_a_rust_change(self):
        self.repo.commit("fix(natives): wayland", {self.WAYLAND: "fn w() { hold(); }\n"})
        first = PC.rust_diff_id(self.base, "HEAD", self.repo.dir)
        self.repo.commit("docs(natives): link", {"packages/natives/CHANGELOG.md": "# C\n- Fixed it\n"})
        self.assertEqual(PC.rust_diff_id(self.base, "HEAD", self.repo.dir), first)
        manifest = {"rust_checks": {first: {"linux": {"sha": "x", "at": "2026-10-20T00:00:00Z", "host": "linux-box"}}}}
        diff = PC.Diff(self.base, "HEAD", self.repo.dir)
        self.assertEqual(printed(PC.check_rust, diff, self.base, "HEAD", self.repo.dir, manifest), [])
        self.repo.commit("fix(natives): bot round", {self.WAYLAND: "fn w() { hold(held); }\n"})
        diff = PC.Diff(self.base, "HEAD", self.repo.dir)
        out = printed(PC.check_rust, diff, self.base, "HEAD", self.repo.dir, manifest)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("FIX   rust       linux  no rust-check recorded for this Rust diff: run "
                                          "scripts/rust-check in the PR's worktree here"), out[0])

    def rust_message(self, build):
        """check_rust's lines for an unrecorded Wayland change under a config whose [build] is `build`."""
        path = contrib_env.write_config(os.path.join(tempfile.mkdtemp(dir=self.repo.dir), "config.toml"),
                                        f"[build]\n{build}\n")
        with mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": path}):
            omp_config.load(reload=True)
            try:
                if not getattr(self, "_wayland", False):
                    self.repo.commit("fix(natives): wayland", {self.WAYLAND: "fn w() { hold(); }\n"})
                    self._wayland = True
                diff = PC.Diff(self.base, "HEAD", self.repo.dir)
                return printed(PC.check_rust, diff, self.base, "HEAD", self.repo.dir, {})
            finally:
                omp_config.load(reload=True)

    def test_rust_names_the_configured_place_and_notes_an_unchecked_platform(self):
        with mock.patch.object(PC, "host_reachable", return_value=True):
            out = self.rust_message('linux = "ssh:buildbox"')
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[-1].startswith("FIX   rust       linux  no rust-check recorded for this Rust diff: run "
                                           "scripts/rust-check in the PR's worktree on buildbox (`ssh buildbox`)"), out)
        out = self.rust_message('linux = "ci"')
        self.assertIn("scripts/rust-check --ci --platform linux", out[-1])
        self.assertTrue(out[-1].startswith("FIX"), out)
        out = self.rust_message('linux = "none"')
        self.assertTrue(out[-1].startswith("NOTE  rust       linux  unchecked: build.linux is \"none\""), out)
        self.assertIn("## Testing", out[-1])

    def test_rust_notes_instead_of_fixing_when_the_ssh_host_does_not_answer(self):
        with mock.patch.object(PC, "host_reachable", return_value=False):
            out = self.rust_message('linux = "ssh:buildbox"')
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("NOTE  rust       linux  unchecked: build.linux is \"ssh:buildbox\" but "
                                          "`ssh buildbox` does not answer"), out)



if __name__ == "__main__":
    unittest.main()
