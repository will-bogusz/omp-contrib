"""The chart toolkit's pure parts, run in Bun: look.mjs's text wrapping for the phone layout, draw.mjs's
diagram helpers, where page.mjs finds Chrome on each platform, config.mjs's file and key rules, and the
source run.mjs --verify expects a browser to pick from the <picture> pr-images prints (wide pair from
a 1244 px window up, phone pair below it, by theme). Needs bun and charts/node_modules.
Run: python3 -m unittest discover -s tests"""
import contrib_env  # noqa: F401  (before pr-images: a hermetic config)
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CHARTS = os.path.join(ROOT, "charts")
loader = importlib.machinery.SourceFileLoader("pr_images", os.path.join(ROOT, "scripts", "pr-images"))
spec = importlib.util.spec_from_loader("pr_images", loader)
PI = importlib.util.module_from_spec(spec)
loader.exec_module(PI)


def bun(code):
    """Evaluate `code` (an ES module that prints JSON) inside charts/, return the parsed output."""
    run = subprocess.run(["bun", "-e", code], capture_output=True, text=True, cwd=CHARTS, timeout=60)
    if run.returncode:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout)


FAKE_GH = """#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
if args[:2] == ["api", "graphql"]:
    numbers = [int(n) for n in re.findall(r"n(\\d+):issueOrPullRequest", " ".join(args))]
    state = json.loads(os.environ["FAKE_STATES"])
    print(json.dumps({"data": {"repository": {f"n{n}": {"number": n, "state": state[str(n)]} for n in numbers}}}))
else:
    sys.exit("FAKE-GH reached: " + " ".join(args[:2]))
"""


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class StoredBodyRefusal(unittest.TestCase):
    """run.mjs refuses to draft from or upload for the live body of a closed PR whose change is queued:
    `pr-queue open` posts the stored body, so GitHub's edit would be lost (#15569, 2026-10-15). An open PR,
    a closed PR no entry queues, and a draft from --body FILE go on (here, to the fake gh or the missing body.md)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="run-mjs-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        git = lambda *a: subprocess.run(["git", "-C", self.repo, *a], check=True, capture_output=True)
        self.repo = os.path.join(self.tmp, "omp")
        os.makedirs(self.repo)
        git("init", "-q", "-b", "omp-queue")
        entry = {"id": "relay-turn-end-detach", "branch": f"{contrib_env.BRANCH_PREFIX}relay-turn-end-detach", "state": "queued",
                 "pr": None, "closed_prs": [15569], "needs": []}
        with open(os.path.join(self.repo, "queue.json"), "w") as f:
            json.dump({"version": 1, "entries": [entry]}, f)
        git("add", "queue.json")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "queue")
        git("remote", "add", "fork", self.repo)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "gh"), "w") as f:
            f.write(FAKE_GH)
        os.chmod(os.path.join(self.bin, "gh"), 0o755)

    def run_mjs(self, number, state, *args, manifest=None):
        chart = os.path.join(self.tmp, f"c{number}")
        os.makedirs(os.path.join(chart, "out"), exist_ok=True)
        with open(os.path.join(chart, "chart.mjs"), "w") as f:
            f.write(f"export const meta = {{ pr: {number} }};\nexport const charts = {{}};\nexport const place = b => b;\n")
        if manifest is not None:
            with open(os.path.join(chart, "out", "manifest.json"), "w") as f:
                json.dump({"pr": number, "repo": "can1357/oh-my-pi", "placed": [], "drafts": {}, "charts": {}, **manifest}, f)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "OMP_REPO": self.repo,
               "FAKE_STATES": json.dumps({str(number): state})}
        return subprocess.run(["bun", os.path.join(CHARTS, "run.mjs"), chart, *args], capture_output=True, text=True,
                              env=env, timeout=120)

    MESSAGE = ("#15569 is closed, queued as relay-turn-end-detach; edit its stored body (pr-queue show / set --body), "
               "not GitHub's")

    def test_draft_and_upload_refuse_a_closed_queued_prs_live_body(self):
        for args, manifest in (((), None), (("--upload",), {})):
            r = self.run_mjs(15569, "CLOSED", *args, manifest=manifest)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn(self.MESSAGE, r.stderr)
            self.assertNotIn("FAKE-GH reached", r.stderr)

    def test_open_unqueued_and_body_file_drafts_go_on(self):
        for number, state, args, manifest, reached in (
                (15601, "OPEN", (), None, "FAKE-GH reached: pr view"),
                (15602, "CLOSED", (), None, "FAKE-GH reached: pr view"),
                (15569, "CLOSED", ("--upload",), {"bodyFile": "/stored.md"}, "body.md")):
            r = self.run_mjs(number, state, *args, manifest=manifest)
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("is closed, queued as", r.stderr)
            self.assertIn(reached, r.stderr)

    # A run.mjs that re-execs itself without end forks hundreds of processes a second (2026-10-18): the
    # child gets its own process group, which is SIGKILLed once more than RUNS_CAP run.mjs processes are
    # alive in it or after RUN_SECONDS, so a red run on the old code stops within a few processes.
    RUNS_CAP, RUN_SECONDS = 4, 5.0

    def run_dangling(self, extra_env=None):
        """run.mjs on an open PR's chart dir whose node_modules/omp-charts points at a removed checkout.
        -> (exit code or None when killed, stderr, link, most run.mjs processes alive at once)."""
        chart = os.path.join(self.tmp, "c15601")
        os.makedirs(os.path.join(chart, "node_modules"))
        with open(os.path.join(chart, "chart.mjs"), "w") as f:
            f.write("export const meta = { pr: 15601 };\nexport const charts = {};\nexport const place = b => b;\n")
        link = os.path.join(chart, "node_modules", "omp-charts")
        os.symlink(os.path.join(self.tmp, "removed-checkout", "charts", "lib"), link)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "OMP_REPO": self.repo,
               "FAKE_STATES": json.dumps({"15601": "OPEN"}), **(extra_env or {})}
        script = os.path.realpath(os.path.join(CHARTS, "run.mjs"))
        with tempfile.TemporaryFile("w+") as err:
            p = subprocess.Popen(["bun", script, chart], stdout=subprocess.DEVNULL, stderr=err, env=env,
                                 start_new_session=True)
            alive = lambda: len(subprocess.run(["pgrep", "-g", str(p.pid), "-f", f"run.mjs {chart}"], capture_output=True,
                                               text=True).stdout.split())
            peak, start, killed = 0, time.monotonic(), False
            while p.poll() is None:
                peak = max(peak, alive())
                if peak > self.RUNS_CAP or time.monotonic() - start > self.RUN_SECONDS:
                    for _ in range(3):
                        try:
                            os.killpg(p.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            break
                        time.sleep(0.05)
                    killed = True
                    break
                time.sleep(0.01)
            p.wait()
            err.seek(0)
            return None if killed else p.returncode, err.read(), link, peak

    def test_a_dangling_charts_link_is_replaced_and_the_run_goes_on(self):
        code, err, link, peak = self.run_dangling()
        self.assertLessEqual(peak, 2, "run.mjs re-exec'd more than once on a dangling omp-charts link")
        self.assertIsNotNone(code, "run.mjs did not finish")
        self.assertIn("FAKE-GH reached: pr view", err)
        self.assertEqual(os.path.realpath(link), os.path.realpath(os.path.join(CHARTS, "lib")))

    def test_a_link_still_dangling_after_the_re_exec_is_an_error_not_a_loop(self):
        code, err, _, peak = self.run_dangling({"OMP_CHARTS_RELINKED": "1"})
        self.assertLessEqual(peak, 1, "run.mjs re-exec'd after its one relink")
        self.assertNotIn(code, (None, 0))
        self.assertIn("still does not resolve after relinking", err)


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class VideoPlayer(unittest.TestCase):
    """A draft puts GitHub's own player markup, taken from GitHub's rendering of a real upload on every
    run, in place of a placeholder video URL; when GitHub renders no player, the draft stops."""

    PLAYER = ('<details open="" class="details-reset border rounded-2">\n  <summary class="tmp-px-3 py-2">'
              '<svg></svg>\n    <span class="m-1">15185-background-drag.mp4</span>\n  </summary>\n\n'
              '  <video src="https://private-user-images.githubusercontent.com/1/2.mp4?jwt=J" '
              'data-canonical-src="https://private-user-images.githubusercontent.com/1/2.mp4?jwt=J" controls="controls" '
              'muted="muted" style="max-height:640px; min-height: 200px">\n\n  </video>\n</details>\n')

    def render(self, gh_output):
        tmp = tempfile.mkdtemp(prefix="video-player-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, "gh"), "w") as f:
            f.write(f"#!/bin/sh\ncat <<'EOF'\n{gh_output}EOF\n")
        os.chmod(os.path.join(tmp, "gh"), 0o755)
        return subprocess.run(["bun", "-e", """import { videoPlayer } from "./lib/page.mjs";
            const player = await videoPlayer();
            console.log(JSON.stringify(player("https://github.com/user-attachments/assets/P", "run.mp4")));"""],
            capture_output=True, text=True, cwd=CHARTS, timeout=60, env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"})

    def test_the_placeholder_and_the_file_name_go_into_githubs_markup(self):
        r = self.render(self.PLAYER)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out.count('"https://github.com/user-attachments/assets/P"'), 2)  # src and data-canonical-src
        self.assertIn('<span class="m-1">run.mp4</span>', out)
        self.assertNotIn("private-user-images", out)
        self.assertNotIn("15185-background-drag", out)

    def test_a_draft_stops_when_github_renders_no_player(self):
        r = self.render('<p dir="auto"><a href="https://github.com/user-attachments/assets/X">link</a></p>\n')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GitHub no longer renders a video URL line as its player", r.stderr)


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class Wrap(unittest.TestCase):
    TEXT = "One real 1,300-turn session per model, replayed with only the image limit changed; recall after 1, 3 and 5 compactions."

    def test_lines_fit_keep_every_word_and_come_out_even(self):
        out = bun(f"""import {{ wrap, textWidth, NARROW }} from "./lib/look.mjs";
            const s = {json.dumps(self.TEXT)};
            const greedy = []; for (const w of s.split(" ")) {{ const l = greedy.length ? greedy.at(-1) + " " + w : w;
              if (greedy.length && textWidth(l, 11.5) <= NARROW) greedy[greedy.length - 1] = l; else greedy.push(w); }}
            const lines = wrap(s, NARROW, 11.5);
            console.log(JSON.stringify({{ lines, widths: lines.map(l => textWidth(l, 11.5)), greedy: greedy.length, NARROW }}));""")
        self.assertEqual(" ".join(out["lines"]), self.TEXT)
        self.assertEqual(len(out["lines"]), out["greedy"])  # balancing never adds a line
        self.assertTrue(all(w <= out["NARROW"] for w in out["widths"]))
        self.assertLess(max(out["widths"]) - min(out["widths"]), 0.5 * out["NARROW"])  # no one-word last line

    def test_bold_text_is_measured_wider(self):
        out = bun('import { textWidth } from "./lib/look.mjs"; console.log(JSON.stringify([textWidth("main", 14), textWidth("main", 14, 600)]))')
        self.assertLess(out[0], out[1])


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class ExpectedSource(unittest.TestCase):
    def pick(self, pic, cases):
        return bun(f"""import {{ expectedSource }} from "./lib/page.mjs";
            const pic = {json.dumps(pic)};
            console.log(JSON.stringify({json.dumps(cases)}.map(([w, s, m]) => expectedSource(pic, w, s, m))));""")

    def test_phone_pair_below_the_breakpoint_wide_pair_from_it(self):
        pic = PI.markdown("x", {"dark": "WD", "light": "WL", "narrow-dark": "ND", "narrow-light": "NL"}, (1560, 668), 2)
        cases = [[1280, "dark"], [1280, "light"], [PI.WIDE_MIN, "dark"], [PI.WIDE_MIN - 1, "light"], [430, "dark"], [390, "light"]]
        self.assertEqual(self.pick(pic, cases), ["WD", "WL", "WD", "NL", "ND", "NL"])

    def test_theme_pair_alone_follows_the_theme_at_any_width(self):
        pic = PI.markdown("x", {"dark": "D", "light": "L"}, (1560, 668), 2)
        self.assertEqual(self.pick(pic, [[390, "dark"], [1440, "light"]]), ["D", "L"])

    def test_loop_shows_its_stills_under_reduced_motion_and_its_gifs_otherwise_by_width(self):
        pic = PI.markdown("x", {"loop": "W", "narrow-loop": "N", "still": "WS", "narrow-still": "NS"}, (1560, 456), 2)
        cases = [[1280, "dark"], [PI.WIDE_MIN - 1, "light"], [390, "dark"],
                 [1280, "light", "reduce"], [PI.WIDE_MIN - 1, "dark", "reduce"], [390, "light", "reduce"]]
        self.assertEqual(self.pick(pic, cases), ["W", "N", "N", "WS", "NS", "NS"])

    def test_a_source_with_no_media_matches_any_window(self):
        pic = PI.markdown("x", {"still": "WS", "narrow-still": "NS"}, (1560, 456), 2)
        self.assertEqual(self.pick(pic, [[1440, "dark"], [PI.WIDE_MIN - 1, "light"], [390, "dark", "reduce"]]), ["WS", "NS", "NS"])


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class ChromePath(unittest.TestCase):
    """page.mjs's defaultChrome on a faked file system: --chrome, then CHROME_PATH or
    PUPPETEER_EXECUTABLE_PATH, then omp's Chrome for Testing in @puppeteer/browsers' layout for this
    platform (newest version first; on Linux $XDG_CACHE_HOME/omp/puppeteer before ~/.omp/puppeteer),
    then a system Chrome off macOS."""

    def resolve(self, files, platform, arch="x64", env=None, flag=None):
        return bun(f"""import {{ defaultChrome }} from "./lib/page.mjs";
            const files = {json.dumps(files)};
            const exists = p => files.some(f => f === p || f.startsWith(p + "/"));
            const list = d => [...new Set(files.filter(f => f.startsWith(d + "/")).map(f => f.slice(d.length + 1).split("/")[0]))];
            let out;
            try {{ out = defaultChrome({{ flag: {json.dumps(flag)}, env: {json.dumps(env or {})}, platform: {json.dumps(platform)},
              arch: {json.dumps(arch)}, home: "/home/u", exists, list }}); }}
            catch (e) {{ out = "ERROR " + e.message; }}
            console.log(JSON.stringify(out));""")

    LINUX = "/home/u/.omp/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome"

    def test_linux_finds_omps_chrome_for_testing(self):
        self.assertEqual(self.resolve([self.LINUX], "linux"), self.LINUX)

    def test_linux_takes_the_newest_version_with_an_executable(self):
        newer = "/home/u/.omp/puppeteer/chrome/linux-151.0.10.2/chrome-linux64/chrome"
        broken = "/home/u/.omp/puppeteer/chrome/linux-152.0.1.1/chrome-linux64/README"
        self.assertEqual(self.resolve([self.LINUX, newer, broken], "linux"), newer)

    def test_linux_looks_under_xdg_cache_first(self):
        xdg = "/x/cache/omp/puppeteer/chrome/linux-149.0.1.0/chrome-linux64/chrome"
        self.assertEqual(self.resolve([self.LINUX, xdg], "linux", env={"XDG_CACHE_HOME": "/x/cache"}), xdg)

    def test_linux_arm_uses_the_linux64_folder_under_its_own_platform_name(self):
        arm = "/home/u/.omp/puppeteer/chrome/linux_arm-150.0.1.0/chrome-linux64/chrome"
        self.assertEqual(self.resolve([self.LINUX, arm], "linux", "arm64"), arm)

    def test_linux_falls_back_to_a_system_chrome(self):
        self.assertEqual(self.resolve(["/usr/bin/chromium"], "linux"), "/usr/bin/chromium")

    def test_mac_and_windows_layouts(self):
        mac = "/home/u/.omp/puppeteer/chrome/mac-150.0.1.0/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        arm = "/home/u/.omp/puppeteer/chrome/mac_arm-150.0.1.0/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        win = "/home/u/.omp/puppeteer/chrome/win64-150.0.1.0/chrome-win64/chrome.exe"
        self.assertEqual(self.resolve([mac, arm, win], "darwin"), mac)
        self.assertEqual(self.resolve([mac, arm, win], "darwin", "arm64"), arm)
        self.assertEqual(self.resolve([mac, arm, win], "win32"), win)

    def test_flag_then_env_win_over_the_managed_chrome(self):
        env = {"CHROME_PATH": "/c", "PUPPETEER_EXECUTABLE_PATH": "/p"}
        self.assertEqual(self.resolve([self.LINUX], "linux", flag="/f", env=env), "/f")
        self.assertEqual(self.resolve([self.LINUX], "linux", env=env), "/c")
        self.assertEqual(self.resolve([self.LINUX], "linux", env={"PUPPETEER_EXECUTABLE_PATH": "/p"}), "/p")

    def test_no_chrome_says_how_to_get_one(self):
        out = self.resolve([], "darwin", "arm64")
        self.assertTrue(out.startswith("ERROR no Chrome found"), out)
        self.assertIn("--chrome PATH", out)


@unittest.skipUnless(shutil.which("bun"), "needs bun")
class ChartsConfig(unittest.TestCase):
    """config.mjs reads the same file omp_config.py does (references/config.md)."""

    def run_js(self, code, env):
        run = subprocess.run(["bun", "-e", f'import * as C from "./lib/config.mjs";\n{code}'], capture_output=True,
                             text=True, cwd=CHARTS, timeout=60, env={**os.environ, **env})
        if run.returncode:
            raise AssertionError(run.stderr)
        return json.loads(run.stdout)

    def test_path_rules_and_dotted_keys(self):
        tmp = tempfile.mkdtemp(prefix="charts-config-")
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = contrib_env.write_config(os.path.join(tmp, "xdg", "omp-contrib", "config.toml"),
                                       '[models]\ncold_read = ""\n[images]\nupload = "fork-links"\n[paths]\ncheckout = "~/omp"\n')
        env = {"OMP_CONTRIB_CONFIG": "", "XDG_CONFIG_HOME": os.path.join(tmp, "xdg"), "OMP_REPO": ""}
        out = self.run_js("""const c = C.loadConfig();
            console.log(JSON.stringify([C.configPath(), C.configPath({ APPDATA: "A" }, "win32"), C.get(c, "images.upload", "relay"),
              C.get(c, "models.cold_read", "@smol"), C.get(c, "no.such", 1), C.ompCheckout(c, { HOME: "/h" }), C.ompCheckout(c, { OMP_REPO: "/r" })]));""", env)
        self.assertEqual(out, [cfg, os.path.join("A", "omp-contrib", "config.toml"), "fork-links", "@smol", 1, "/h/omp", "/r"])

    def test_a_missing_file_is_valid_and_empty(self):
        out = self.run_js('console.log(JSON.stringify(C.loadConfig()))', {"OMP_CONTRIB_CONFIG": "/nonexistent/config.toml"})
        self.assertEqual(out, {})


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class Draw(unittest.TestCase):
    def test_arrow_head_ends_on_the_target_in_any_direction(self):
        out = bun("""import { arrow } from "./lib/draw.mjs";
            const tips = [[0, 0, 100, 0], [50, 80, 50, 10], [0, 0, 30, 40]].map(([a, b, c, d]) =>
              arrow(a, b, c, d, "#000").match(/points="([\\d.-]+),([\\d.-]+)/).slice(1).map(Number));
            console.log(JSON.stringify(tips));""")
        self.assertEqual(out, [[100, 0], [50, 10], [30, 40]])

    def test_box_grows_with_its_text_and_kicker(self):
        out = bun("""import { box } from "./lib/draw.mjs"; import { THEMES } from "./lib/look.mjs";
            const t = THEMES.light, s = "Is it loaded from omp's install folder, and are the files there not from a newer omp?";
            console.log(JSON.stringify([box(0, 0, 400, { text: "short" }, t).h, box(0, 0, 160, { text: s }, t).h,
              box(0, 0, 160, { text: s, kicker: "this PR", who: "pr" }, t).h]));""")
        self.assertLess(out[0], out[1])
        self.assertLess(out[1], out[2])

    def test_code_boxes_every_occurrence_behind_plain_text_and_says_where(self):
        out = bun("""import { code } from "./lib/draw.mjs"; import { THEMES } from "./lib/look.mjs";
            console.log(JSON.stringify(code(0, 0, ['  - textbox "Password": hunter2', 'button "hunter2" hunter2'], { size: 10, mark: ["hunter2"] }, THEMES.dark)));""")
        self.assertEqual(out["svg"].count("<rect"), 3)
        self.assertLess(out["svg"].rindex("<rect"), out["svg"].index("<text"))  # boxes under the text
        self.assertNotIn("<tspan", out["svg"])
        self.assertIn('xml:space="preserve">  - textbox', out["svg"])
        self.assertEqual([(m["row"], round(m["x"], 2)) for m in out["marks"]], [(0, round(24 * 6.02, 2)), (1, round(8 * 6.02, 2)), (1, round(17 * 6.02, 2))])

    def test_code_wraps_after_the_colon_indents_the_rest_and_never_splits_a_mark(self):
        out = bun("""import { code } from "./lib/draw.mjs"; import { THEMES } from "./lib/look.mjs";
            const r = code(0, 0, ['  - textbox "Password" [ref=e6]: Fake-Secret-9931', 'a b c d e f g hunter two h i'],
              { size: 10, width: 10 * 0.602 * 34, mark: ["Fake-Secret-9931", "hunter two"] }, THEMES.dark);
            const rows = [...r.svg.matchAll(/preserve">([^<]*)</g)].map(m => m[1]);
            console.log(JSON.stringify({ rows, marks: r.marks.map(m => [m.s, m.line, m.row]), n: r.rows }));""")
        self.assertEqual(out["rows"][:2], ['  - textbox &quot;Password&quot; [ref=e6]:'.replace("&quot;", '"'), "      Fake-Secret-9931"])
        self.assertTrue(all(len(r) <= 34 for r in out["rows"]))
        self.assertIn(["Fake-Secret-9931", 0, 1], out["marks"])
        self.assertIn("hunter two", [m[0] for m in out["marks"]])  # not split across rows
        self.assertEqual(out["n"], len(out["rows"]))

    def test_code_gap_adds_room_only_under_marked_rows(self):
        out = bun("""import { code } from "./lib/draw.mjs"; import { THEMES } from "./lib/look.mjs";
            const lines = ["a", "b secret", "c", "secret d"], o = { size: 10, mark: ["secret"] };
            const a = code(0, 0, lines, o, THEMES.dark), b = code(0, 0, lines, { ...o, gap: 12 }, THEMES.dark);
            const c = code(0, 0, lines, { ...o, gap: ms => (ms[0].line === 1 ? 5 : 20) }, THEMES.dark);
            console.log(JSON.stringify([b.h - a.h, b.marks.map(m => m.y - a.marks[0].y), c.h - a.h]));""")
        self.assertEqual(out, [24, [0, 2 * 15 + 12], 25])  # a function sizes each marked row's room


FIGURES = {"figures": [
    {"shape": "timeline", "id": "tl", "at": "<!-- figure: timeline -->", "title": "Bar <gone> while you read",
     "takeaway": "t", "alt": "a", "note": "Not to scale & illustrative.",
     "steps": ["Agent's turn", "Hands back", "You read & wait", "Next <call>"],
     "lanes": [{"who": "main", "label": "main", "cells": ["Tab attached", "", {"text": "Bar stays up <all> the time", "outcome": "bad"}, None]},
               {"who": "pr", "label": "this PR", "cells": ["Tab attached", "Released & bar leaves",
                                                          {"text": "No bar while you read", "outcome": "good"}, "Reattaches in ~330 ms"]}]},
    {"shape": "flow", "id": "fl", "replaces": "| Case |", "details": "Each case", "title": "Reloads itself",
     "takeaway": "t", "alt": "a", "note": "Drawing of the code.",
     "questions": [{"q": "Does it speak the <relay> protocol?", "exit": "no", "out": {"text": "Fails & says so", "who": "both"}},
                   {"q": "Is a client connected?", "exit": "yes", "out": {"main": "Keeps the old one", "pr": "Waits for it to leave"}}],
     "end": {"main": "Old extension runs on", "pr": "Rewritten & reloaded"}}]}


def figures(change):
    """A copy of FIGURES with fields of figure i changed: {i: {field: value, or None to drop it}}."""
    out = json.loads(json.dumps(FIGURES))
    for i, fields in change.items():
        for k, v in fields.items():
            if v is None:
                out["figures"][i].pop(k, None)
            else:
                out["figures"][i][k] = v
    return out


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class Shapes(unittest.TestCase):
    """lib/shapes.mjs: a timeline and a decision flow drawn from a figures.json spec, placed by fromFigures."""

    @staticmethod
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def test_both_shapes_draw_every_text_at_both_widths_in_both_themes(self):
        out = bun(f"""import {{ fromFigures }} from "./lib/shapes.mjs"; import {{ THEMES }} from "./lib/look.mjs";
            const {{ charts }} = fromFigures({json.dumps(FIGURES)});
            const out = {{}};
            for (const [id, c] of Object.entries(charts)) for (const th of ["dark", "light"])
              out[`${{id}}-${{th}}`] = [c.fn({{}}, THEMES[th]), c.narrow({{}}, THEMES[th])];
            console.log(JSON.stringify(out));""")
        tl, fl = FIGURES["figures"]
        texts = {"tl": tl["steps"] + [c if isinstance(c, str) else c["text"] for lane in tl["lanes"] for c in lane["cells"] if c],
                 "fl": [q["q"] for q in fl["questions"]] + [fl["questions"][0]["out"]["text"]]
                 + [fl["questions"][1]["out"][k] for k in ("main", "pr")] + [fl["end"][k] for k in ("main", "pr")]}
        self.assertEqual(sorted(out), ["fl-dark", "fl-light", "tl-dark", "tl-light"])
        for key, layouts in out.items():
            for svg, width in zip(layouts, (780, 320)):
                where = f"{key} at {width}"
                self.assertEqual(re.match(r'<svg[^>]*\swidth="([\d.]+)"', svg)[1], str(width), where)
                sizes = [float(s) for s in re.findall(r'font-size="([\d.]+)"', svg)]
                self.assertGreaterEqual(min(sizes), 11.5, where)
                drawn = " ".join(re.findall(r"<text[^>]*>(.*?)</text>", svg))
                for s in texts[key.split("-")[0]]:
                    self.assertIn(self.esc(s), drawn, where)

    def test_place_swaps_the_marker_and_moves_the_table_verbatim_into_details(self):
        table = "| Case | main | this PR |\n|---|---|---|\n| old | fails | fails |"
        body = f"Intro.\n\n<!-- figure: timeline -->\n\n## Cases\n\n{table}\n\nEnd."
        placed = bun(f"""import {{ fromFigures }} from "./lib/shapes.mjs"; import * as B from "./lib/body.mjs";
            const {{ place }} = fromFigures({json.dumps(FIGURES)});
            console.log(JSON.stringify(place({json.dumps(body)}, {{}}, {{ ...B, picture: id => `[picture ${{id}}]` }})));""")
        self.assertEqual(placed, f"Intro.\n\n[picture tl]\n\n## Cases\n\n[picture fl]\n\n"
                                 f"<details><summary>Each case</summary>\n\n{table}\n\n</details>\n\nEnd.")

    def check_error(self, spec, message):
        r = subprocess.run(["bun", "-e", f'import {{ fromFigures }} from "./lib/shapes.mjs"; fromFigures({json.dumps(spec)});'],
                           capture_output=True, text=True, cwd=CHARTS, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(message, r.stderr)

    def test_a_lane_whose_cells_miss_a_step_is_refused(self):
        spec = figures({})
        spec["figures"][0]["lanes"][1]["cells"].pop()
        self.check_error(spec, "figures[0] (tl): lanes[1] (this PR) has 3 cells for 4 steps")

    def test_a_figure_needs_exactly_one_of_at_and_replaces(self):
        msg = "needs exactly one of at (a line in the body) or replaces (a table's header start)"
        self.check_error(figures({0: {"at": None}}), "figures[0] (tl): " + msg)
        self.check_error(figures({1: {"at": "<!-- x -->"}}), "figures[1] (fl): " + msg)

    def test_unknown_shape_and_missing_field_are_refused(self):
        self.check_error(figures({0: {"shape": "gantt"}}), 'unknown shape "gantt"')
        self.check_error(figures({1: {"note": None}}), "figures[1] (fl): note is missing")


@unittest.skipUnless(shutil.which("bun") and os.path.isdir(os.path.join(CHARTS, "node_modules")), "needs bun and charts/node_modules")
class NoPrYet(unittest.TestCase):
    """A figures.json body drafted before its PR exists (no `pr`): run.mjs drafts only from --body FILE, and
    --upload never asks pr-queue about a PR number, then says to queue the body instead of `gh pr edit`."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="no-pr-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = os.path.join(self.tmp, "fig")
        os.makedirs(os.path.join(self.dir, "out"))
        with open(os.path.join(self.dir, "figures.json"), "w") as f:
            json.dump(FIGURES, f)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "gh"), "w") as f:
            f.write("#!/bin/sh\necho FAKE-GH reached >&2\nexit 9\n")
        os.chmod(os.path.join(self.bin, "gh"), 0o755)

    def run_mjs(self, *args, manifest=None):
        if manifest is not None:
            with open(os.path.join(self.dir, "out", "manifest.json"), "w") as f:
                json.dump({"repo": "can1357/oh-my-pi", "placed": [], "drafts": {}, "charts": {}, **manifest}, f)
            for name in ("body.md", "live.md"):
                with open(os.path.join(self.dir, "out", name), "w") as f:
                    f.write("## What\n\nA drafted body.")
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "OMP_REPO": os.path.join(self.tmp, "no-checkout")}
        return subprocess.run(["bun", os.path.join(CHARTS, "run.mjs"), self.dir, *args], capture_output=True, text=True,
                              env=env, timeout=120)

    def test_upload_of_a_drafted_body_says_to_queue_it(self):
        r = self.run_mjs("--upload", manifest={"bodyFile": "/draft.md"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pr-queue add <branch> --title … --body ", r.stdout)
        self.assertIn("out/body-final.md", r.stdout)
        self.assertNotIn("gh pr edit", r.stdout)
        self.assertNotIn("FAKE-GH", r.stderr)

    def test_draft_and_upload_without_a_body_file_refuse(self):
        for args, manifest, msg in (((), None, "draft with --body FILE"), (("--upload",), {}, "draft with --body FILE first")):
            r = self.run_mjs(*args, manifest=manifest)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn(f"no PR number yet, so no live body: {msg}", r.stderr)
            self.assertNotIn("FAKE-GH", r.stderr)


if __name__ == "__main__":
    unittest.main()
