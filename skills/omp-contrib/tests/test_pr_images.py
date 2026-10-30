"""pr-images' file checks, dark/light pairing and printed Markdown, on real image files in a scratch
dir; its CDP client against a fake relay and Chrome (deadlines, closing its tab on every exit path)
and against the real websockets client with a peer that stops reading; its in-page upload script in
Node with GitHub's page faked; and fork-links' commit sequence against a faked GitHub API. The
uploads themselves need Chrome and GitHub and are not covered here.
Run: python3 -m unittest discover -s tests"""
import contrib_env  # noqa: F401  (before pr-images: a hermetic config)
import base64
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import itertools
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import zlib

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
loader = importlib.machinery.SourceFileLoader("pr_images", os.path.join(SCRIPTS, "pr-images"))
spec = importlib.util.spec_from_loader("pr_images", loader)
PI = importlib.util.module_from_spec(spec)
loader.exec_module(PI)


def png(width, height):
    """A valid one-colour PNG, as a renderer writes it."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def jpeg(width, height):
    """SOI, an APP0 segment, then a baseline SOF0 frame header."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def file(self, name, data):
        path = os.path.join(self.dir.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def main_error(self, *argv):
        """Run main expecting an argument error before any browser work; return its message."""
        def no_relay(*_):
            raise AssertionError("pr-images reached the browser")
        PI.Relay, saved = no_relay, PI.Relay
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as exit_:
                PI.main(list(argv))
        finally:
            PI.Relay = saved
        self.assertEqual(exit_.exception.code, 2)
        return err.getvalue().splitlines()[-1]


class Files(Scratch):
    def test_sizes_of_png_gif_and_jpeg(self):
        self.assertEqual(PI.image_size(png(1560, 524)), (1560, 524))
        self.assertEqual(PI.image_size(b"GIF89a" + struct.pack("<HH", 300, 200) + b"\x00" * 8), (300, 200))
        self.assertEqual(PI.image_size(jpeg(1280, 720)), (1280, 720))
        self.assertIsNone(PI.image_size(b"<svg/>"))

    def test_load_returns_bytes_type_and_size(self):
        data = png(4, 2)
        self.assertEqual(PI.load(self.file("a.PNG", data)), (data, "image/png", (4, 2)))

    def test_unsupported_type_and_oversized_file_are_refused(self):
        with self.assertRaisesRegex(ValueError, "take .gif"):
            PI.load(self.file("a.svg", b"<svg/>"))
        with self.assertRaisesRegex(ValueError, "caps images at 10 MB"):
            PI.load(self.file("big.png", png(1, 1) + b"\x00" * PI.MAX_BYTES))

    def test_chunks_rejoin_to_the_base64_of_the_file(self):
        data = os.urandom(PI.CHUNK)  # base64 is 4/3 longer, so this needs two chunks
        parts = PI.chunks(data)
        self.assertEqual(len(parts), 2)
        self.assertEqual(base64.b64decode("".join(parts)), data)

    def test_a_video_is_taken_as_video_without_a_size(self):
        data = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64
        self.assertEqual(PI.load(self.file("clip.mp4", data)), (data, "video/mp4", None))
        self.assertEqual(PI.load(self.file("clip.MOV", data))[1], "video/quicktime")


class Pairing(Scratch):
    def test_plain_files_keep_argument_order_and_their_names(self):
        self.assertEqual(PI.plan(["x/b-dark.png", "a.png"], themed=False),
                         [("b-dark", {"plain": "x/b-dark.png"}), ("a", {"plain": "a.png"})])

    def test_themed_pairs_dark_and_light_in_order_of_first_appearance(self):
        files = ["B-light.png", "A-dark.png", "B-dark.png", "A-light.png"]
        self.assertEqual(PI.plan(files, themed=True), [
            ("B", {"light": "B-light.png", "dark": "B-dark.png"}),
            ("A", {"dark": "A-dark.png", "light": "A-light.png"}),
        ])

    def test_themed_refuses_unpaired_untagged_and_doubled_files(self):
        with self.assertRaisesRegex(ValueError, "A: no light file"):
            PI.plan(["A-dark.png"], themed=True)
        with self.assertRaisesRegex(ValueError, "needs NAME-dark"):
            PI.plan(["A.png"], themed=True)
        with self.assertRaisesRegex(ValueError, "two dark files for A"):
            PI.plan(["A-dark.png", "x/A-dark.png"], themed=True)

    def test_narrow_pair_joins_its_wide_pair_and_needs_both_halves(self):
        files = ["A-dark.png", "A-light.png", "A-narrow-dark.png", "A-narrow-light.png"]
        self.assertEqual(PI.plan(files, themed=True), [("A", {
            "dark": "A-dark.png", "light": "A-light.png", "narrow-dark": "A-narrow-dark.png", "narrow-light": "A-narrow-light.png"})])
        with self.assertRaisesRegex(ValueError, "A: no narrow-light file"):
            PI.plan(files[:3], themed=True)
        with self.assertRaisesRegex(ValueError, "A: no dark file"):
            PI.plan(files[1:], themed=True)

    def test_pair_of_different_sizes_and_wrong_alt_count_stop_before_the_browser(self):
        dark = self.file("A-dark.png", png(4, 2))
        light = self.file("A-light.png", png(4, 3))
        self.assertIn("A: the dark and light files differ in size",
                      self.main_error("upload", "--themed", dark, light))
        self.assertIn("2 --alt for 1 images",
                      self.main_error("upload", "--alt", "x", "--alt", "y", dark))
        self.assertIn("1 --alt for 2 images",
                      self.main_error("upload", "--themed", "--alt", "x", dark,
                                      self.file("A-light.png", png(4, 2)), self.file("B-dark.png", png(4, 2)),
                                      self.file("B-light.png", png(4, 2))))

    def test_narrow_pair_of_different_sizes_stops_before_the_browser(self):
        files = [self.file("A-dark.png", png(8, 2)), self.file("A-light.png", png(8, 2)),
                 self.file("A-narrow-dark.png", png(960, 6)), self.file("A-narrow-light.png", png(960, 5))]
        self.assertIn("A: the narrow-dark and narrow-light files differ in size", self.main_error("upload", "--themed", *files))

    def test_narrow_pair_too_small_to_stay_sharp_at_440_px_stops_before_the_browser(self):
        # A 320 px layout at 2x (640 px) blurs once a half-width window shows it 440 px wide.
        files = [self.file("A-dark.png", png(8, 2)), self.file("A-light.png", png(8, 2)),
                 self.file("A-narrow-dark.png", png(640, 6)), self.file("A-narrow-light.png", png(640, 6))]
        self.assertIn("A: the narrow files are 640 px wide", self.main_error("upload", "--themed", *files))

    def test_uploaded_file_must_be_one_of_the_files(self):
        a = self.file("a.png", png(4, 2))
        self.assertIn("not among the files", self.main_error("upload", "--uploaded", "b.png=https://x", a))
        self.assertIn("expected FILE=https://", self.main_error("upload", "--uploaded", "a.png", a))

    LOOP = ["A.gif", "A-narrow.gif", "A-still.png", "A-narrow-still.png"]

    def test_loop_groups_its_gifs_and_stills_under_one_name(self):
        self.assertEqual(PI.plan([f"x/{f}" for f in self.LOOP], loop=True), [("A", {
            "loop": "x/A.gif", "narrow-loop": "x/A-narrow.gif", "still": "x/A-still.png", "narrow-still": "x/A-narrow-still.png"})])

    def test_loop_needs_all_four_files_and_the_right_kinds(self):
        for i, missing in enumerate(["loop", "narrow-loop", "still", "narrow-still"]):
            with self.assertRaisesRegex(ValueError, f"A: no {missing} file"):
                PI.plan(self.LOOP[:i] + self.LOOP[i + 1:], loop=True)
        with self.assertRaisesRegex(ValueError, "PNG or JPEG for the -still"):
            PI.plan(["A.gif", "A-narrow.gif", "A-still.gif", "A-narrow-still.png"], loop=True)
        with self.assertRaisesRegex(ValueError, "--loop takes NAME.gif"):
            PI.plan(["A.png", "A-narrow.gif", "A-still.png", "A-narrow-still.png"], loop=True)

    def test_still_groups_a_recordings_two_end_frames_and_takes_nothing_else(self):
        self.assertEqual(PI.plan(["x/A-still.png", "x/A-narrow-still.png"], still=True),
                         [("A", {"still": "x/A-still.png", "narrow-still": "x/A-narrow-still.png"})])
        with self.assertRaisesRegex(ValueError, "A: no narrow-still file"):
            PI.plan(["A-still.png"], still=True)
        with self.assertRaisesRegex(ValueError, "--still takes NAME-still"):
            PI.plan(["A.png", "A-narrow-still.png"], still=True)

    def test_a_video_has_no_variants(self):
        for kw in ({"themed": True}, {"loop": True}, {"still": True}):
            with self.assertRaisesRegex(ValueError, "a video has no theme, phone or still variant"):
                PI.plan(["A-dark.mp4"], **kw)
        self.assertEqual(PI.plan(["run.mp4"]), [("run", {"plain": "run.mp4"})])

    def test_loop_files_of_mismatched_sizes_or_a_blurry_phone_layout_stop_before_the_browser(self):
        def gif(w, h):
            return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00" * 8
        files = {"A.gif": gif(1560, 456), "A-narrow.gif": gif(880, 1026),
                 "A-still.png": png(1560, 456), "A-narrow-still.png": png(880, 1026)}
        paths = lambda fs: [self.file(n, d) for n, d in fs.items()]
        self.assertIn("A: the loop and still files differ in size",
                      self.main_error("upload", "--loop", *paths({**files, "A-still.png": png(1560, 450)})))
        self.assertIn("A: the narrow-loop and narrow-still files differ in size",
                      self.main_error("upload", "--loop", *paths({**files, "A-narrow-still.png": png(880, 1000)})))
        self.assertIn("A: the narrow files are 640 px wide",
                      self.main_error("upload", "--loop", *paths({**files, "A-narrow.gif": gif(640, 746),
                                                                  "A-narrow-still.png": png(640, 746)})))
        self.assertIn("not allowed with argument --themed", self.main_error("upload", "--themed", "--loop", *paths(files)))


class Markdown(unittest.TestCase):
    def test_plain_image_is_githubs_own_tag_scaled_for_2x(self):
        self.assertEqual(PI.markdown("A-dark", {"plain": "U"}, (1560, 524), 1),
                         '<img width="1560" alt="A-dark" src="U" />')
        self.assertEqual(PI.markdown('a "b" <c>', {"plain": "U"}, (1560, 524), 2),
                         '<img width="780" alt="a &quot;b&quot; &lt;c>" src="U" />')

    def test_no_height_so_a_narrow_column_keeps_the_aspect_ratio(self):
        # GitHub caps images at max-width: 100% without height: auto; a height attribute stretched
        # #15434's chart to 324 x 334 at a 390 px window (2026-10-15).
        for urls in ({"plain": "U"}, {"dark": "D", "light": "L"},
                     {"dark": "D", "light": "L", "narrow-dark": "ND", "narrow-light": "NL"}):
            self.assertNotIn("height", PI.markdown("x", urls, (1560, 668), 2))

    def test_unknown_size_leaves_the_size_to_the_renderer(self):
        self.assertEqual(PI.markdown("x", {"plain": "U"}, None, 2), '<img alt="x" src="U" />')

    def test_themed_pair_is_a_picture_with_the_light_image_as_fallback(self):
        self.assertEqual(PI.markdown("Chart A", {"dark": "D", "light": "L"}, (1560, 524), 2), "\n".join([
            "<picture>",
            '  <source media="(prefers-color-scheme: dark)" srcset="D">',
            '  <source media="(prefers-color-scheme: light)" srcset="L">',
            '  <img width="780" alt="Chart A" src="L" />',
            "</picture>",
        ]))

    def test_phone_layout_comes_after_the_wide_pair_at_most_440_px_wide(self):
        urls = {"dark": "D", "light": "L", "narrow-dark": "ND", "narrow-light": "NL"}
        self.assertEqual(PI.markdown("Chart A", urls, (1560, 668), 2), "\n".join([
            "<picture>",
            '  <source media="(min-width: 1244px) and (prefers-color-scheme: dark)" srcset="D">',
            '  <source media="(min-width: 1244px) and (prefers-color-scheme: light)" srcset="L">',
            '  <source media="(prefers-color-scheme: dark)" width="440" srcset="ND">',
            '  <source media="(prefers-color-scheme: light)" width="440" srcset="NL">',
            '  <img width="780" alt="Chart A" src="L" />',
            "</picture>",
        ]))

    def test_loop_is_a_picture_with_reduced_motion_stills_first_and_no_colour_scheme_term(self):
        # GitHub doesn't pause a GIF inside <picture> under reduced motion (2026-10-15), so the stills
        # carry that; with no prefers-color-scheme term, <themed-picture> leaves every source as written.
        urls = {"loop": "W", "narrow-loop": "N", "still": "WS", "narrow-still": "NS"}
        self.assertEqual(PI.markdown("Loop A", urls, (1560, 456), 2), "\n".join([
            "<picture>",
            '  <source media="(prefers-reduced-motion: reduce) and (min-width: 1244px)" srcset="WS">',
            '  <source media="(prefers-reduced-motion: reduce)" width="440" srcset="NS">',
            '  <source media="(min-width: 1244px)" srcset="W">',
            '  <source width="440" srcset="N">',
            '  <img width="780" alt="Loop A" src="W" />',
            "</picture>",
        ]))
        self.assertNotIn("prefers-color-scheme", PI.markdown("x", urls, (1560, 456), 2))
        self.assertNotIn("height", PI.markdown("x", urls, (1560, 456), 2))

    def test_still_is_a_picture_of_two_layouts_with_no_theme_or_motion_term(self):
        self.assertEqual(PI.markdown("End A", {"still": "WS", "narrow-still": "NS"}, (1560, 456), 2), "\n".join([
            "<picture>",
            '  <source media="(min-width: 1244px)" srcset="WS">',
            '  <source width="440" srcset="NS">',
            '  <img width="780" alt="End A" src="WS" />',
            "</picture>",
        ]))



class FakeChrome:
    """Chrome behind the relay: tabs outlive the connection that made them; a creation the relay
    has started completes after `create_delay` seconds whatever happens to that connection, and
    may still be answered with `create_error` (the extension went away after Chrome made the tab,
    with `create_error_after_tab`); `close_errors` answer the next closes without closing; with
    `apple_events`, Chrome's AppleScript closes tabs whatever the relay does."""

    def __init__(self, create_delay=0.0, fail_attach=False, create_error=None, create_error_after_tab=False,
                 close_errors=(), apple_events=False, tabs=None):
        self.create_delay, self.fail_attach = create_delay, fail_attach
        self.create_error, self.create_error_after_tab = create_error, create_error_after_tab
        self.close_errors, self.apple_events = list(close_errors), apple_events
        self.tabs = dict(tabs or {})
        self.pending, self.sockets, self.ids, self.assets = [], [], itertools.count(1), itertools.count(1)

    def apple_close(self, marker):
        """Chrome's AppleScript, a snapshot like the real one: (matched, left) or None if unavailable."""
        self.tick()
        if not self.apple_events:
            return None
        kept = {t: u for t, u in self.tabs.items() if marker not in u}
        matched, self.tabs = len(self.tabs) - len(kept), kept
        return matched, 0

    def connect(self):
        self.sockets.append(FakeSocket(self))
        return self.sockets[-1]

    def tick(self):
        for job in [p for p in self.pending if p[0] <= time.monotonic()]:
            self.pending.remove(job)
            _, sock, msg_id, url = job
            target = f"PAGE.{next(self.ids)}"
            self.tabs[target] = url
            sock.queue.append({"id": msg_id, "error": {"message": self.create_error}} if self.create_error
                              else {"id": msg_id, "result": {"targetId": target}})

    def settled_tabs(self):
        """The tabs once every creation the relay started has reached Chrome."""
        if self.pending:
            time.sleep(max(0, max(p[0] for p in self.pending) - time.monotonic()))
        self.tick()
        return self.tabs


class FakeShutdown:
    def __init__(self, sock):
        self.sock = sock

    def shutdown(self, how):
        self.sock.alive = False
        self.sock.unblock.set()


class FakeSocket:
    """One relay connection: answers the Target commands and GitHub-page evaluations, floods
    events in between, and can die, stall its next write for `stall_send` seconds (cut short by a
    shutdown), or deliver a Ctrl-C into the next receive."""

    def __init__(self, chrome):
        self.chrome, self.sent, self.queue, self.alive = chrome, [], [], True
        self.stall_send, self.interrupt, self.die_on_interrupt = 0, False, False
        self.unblock = threading.Event()
        self.socket = FakeShutdown(self)

    def send(self, text):
        if self.stall_send:
            self.unblock.wait(self.stall_send)
            self.stall_send = 0
        if not self.alive:
            raise ConnectionError("connection closed")
        msg = json.loads(text)
        self.sent.append(msg)
        method, params, chrome = msg["method"], msg["params"], self.chrome
        answer = lambda result: self.queue.append({"id": msg["id"], "result": result})  # noqa: E731
        error = lambda message: self.queue.append({"id": msg["id"], "error": {"message": message}})  # noqa: E731
        chrome.tick()
        if method == "Target.createTarget":
            if chrome.create_error and not chrome.create_error_after_tab:
                return error(chrome.create_error)
            chrome.pending.append((time.monotonic() + chrome.create_delay, self, msg["id"], params["url"]))
            chrome.tick()
        elif method == "Target.attachToTarget":
            error("cannot attach") if chrome.fail_attach else answer({"sessionId": "S1"})
        elif method == "Target.getTargets":
            answer({"targetInfos": [{"targetId": t, "url": u} for t, u in chrome.tabs.items()]})
        elif method == "Target.closeTarget":
            if chrome.close_errors:
                error(chrome.close_errors.pop(0))
            elif chrome.tabs.pop(params["targetId"], None) is None:
                error(f"No target with id {params['targetId']}")
            else:
                answer({"success": True})
        elif method == "Runtime.evaluate":
            expression = params["expression"]
            value = (contrib_env.FORK_OWNER if "user-login" in expression else
                     {"href": f"https://github.com/user-attachments/assets/{next(chrome.assets)}", "repo": "1"}
                     if "/upload/policies/assets" in expression else None)
            answer({"result": {"value": value}})

    def recv(self, timeout):
        if self.interrupt:
            self.interrupt, self.alive = False, not self.die_on_interrupt
            raise KeyboardInterrupt
        if not self.alive:
            raise ConnectionError("connection closed")
        self.chrome.tick()
        if self.queue:
            return json.dumps(self.queue.pop(0))
        time.sleep(min(timeout, 0.01))
        return json.dumps({"method": "Runtime.consoleAPICalled", "params": {}})

    def close(self):
        self.alive = False


RELAY = PI.Relay  # tests swap PI.Relay out; fakes build on the real class


def fake_relay(chrome, repo="can1357/oh-my-pi"):
    relay = RELAY(repo)
    relay.connect = chrome.connect
    relay.apple_close = lambda: chrome.apple_close(relay.marker)
    return relay


USER_TABS = {"USER": "https://github.com/can1357/oh-my-pi/pull/1",
              "OTHER": "https://github.com/can1357/oh-my-pi#omp-pr-images-000000000000"}


class Cdp(unittest.TestCase):
    def setUp(self):
        grace, PI.CREATE_GRACE = PI.CREATE_GRACE, 3
        self.addCleanup(setattr, PI, "CREATE_GRACE", grace)

    def test_a_missing_reply_times_out_although_events_keep_arriving(self):
        relay = fake_relay(FakeChrome())
        relay.ws = relay.connect()
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "Page.navigate: no reply in time"):
            relay.call("Page.navigate", "S1", 0.2)
        self.assertLess(time.monotonic() - start, 1)

    def test_a_relay_that_stops_reading_is_cut_off_at_the_deadline(self):
        relay = fake_relay(FakeChrome())
        relay.ws = relay.connect()
        relay.ws.stall_send = 3  # a client that never cuts the write off fails the test, not hangs
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "Runtime.evaluate: the relay stopped reading"):
            relay.call("Runtime.evaluate", "S1", 0.2, expression="x" * PI.CHUNK)
        self.assertLess(time.monotonic() - start, 1)
        self.assertFalse(relay.ws.alive)

    def test_the_tab_is_closed_after_a_normal_run(self):
        chrome = FakeChrome(tabs=USER_TABS)
        with fake_relay(chrome) as relay:
            self.assertIn(relay.target, chrome.tabs)
        self.assertEqual(chrome.settled_tabs(), USER_TABS)

    def test_a_failed_attach_closes_the_tab_it_just_created(self):
        chrome = FakeChrome(fail_attach=True, tabs=USER_TABS)
        with self.assertRaisesRegex(PI.CdpError, "cannot attach"):
            with fake_relay(chrome):
                pass
        self.assertEqual(chrome.settled_tabs(), USER_TABS)

    def test_a_dropped_connection_closes_the_tab_over_a_new_one(self):
        chrome = FakeChrome(tabs=USER_TABS)
        with fake_relay(chrome):
            chrome.sockets[0].alive = False
        self.assertEqual(chrome.settled_tabs(), USER_TABS)
        self.assertEqual(len(chrome.sockets), 2)

    def interrupt_creation(self, chrome, drop_connection):
        """Ctrl-C while Target.createTarget waits for its reply, on the first connection only."""
        def connect():
            sock = chrome.connect()
            if len(chrome.sockets) == 1:
                sock.interrupt, sock.die_on_interrupt = True, drop_connection
            return sock
        relay = fake_relay(chrome)
        relay.connect = connect
        with self.assertRaises(KeyboardInterrupt):
            with relay:
                pass

    def test_ctrl_c_during_a_slow_creation_waits_for_its_reply_and_closes_the_tab(self):
        chrome = FakeChrome(create_delay=0.3, tabs=USER_TABS)
        self.interrupt_creation(chrome, drop_connection=False)
        self.assertEqual(chrome.settled_tabs(), USER_TABS)
        self.assertEqual(len(chrome.sockets), 1)

    def test_ctrl_c_that_also_drops_the_connection_finds_the_tab_once_it_appears(self):
        chrome = FakeChrome(create_delay=0.5, tabs=USER_TABS)
        self.interrupt_creation(chrome, drop_connection=True)
        self.assertEqual(chrome.settled_tabs(), USER_TABS)
        self.assertEqual(len(chrome.sockets), 2)

    def test_a_creation_refused_before_chrome_leaves_every_tab_alone_without_waiting(self):
        chrome = FakeChrome(create_error=PI.NOT_CREATED, tabs=USER_TABS)
        start = time.monotonic()
        with self.assertRaisesRegex(PI.CdpError, "extension is not connected"):
            with fake_relay(chrome):
                pass
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(chrome.settled_tabs(), USER_TABS)

    def test_a_creation_error_after_chrome_made_the_tab_still_closes_it(self):
        chrome = FakeChrome(create_error="Extension RPC timed out", create_error_after_tab=True,
                            tabs=USER_TABS)
        with self.assertRaisesRegex(PI.CdpError, "timed out"):
            with fake_relay(chrome):
                pass
        self.assertEqual(chrome.settled_tabs(), USER_TABS)

    def test_a_failed_close_is_retried_over_a_new_connection(self):
        chrome = FakeChrome(close_errors=["relay extension is not connected"], tabs=USER_TABS)
        with fake_relay(chrome):
            pass
        self.assertEqual(chrome.settled_tabs(), USER_TABS)
        self.assertEqual(len(chrome.sockets), 2)

    def test_a_close_the_relay_cannot_do_falls_back_to_chromes_applescript(self):
        chrome = FakeChrome(close_errors=["relay extension is not connected"] * 2, apple_events=True,
                            tabs=USER_TABS)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with fake_relay(chrome):
                pass
        self.assertEqual(chrome.settled_tabs(), USER_TABS)
        self.assertIn("Chrome's AppleScript did", err.getvalue())

    def test_a_relay_gone_for_good_falls_back_to_chromes_applescript(self):
        chrome = FakeChrome(apple_events=True, tabs=USER_TABS)
        relay = fake_relay(chrome)

        def connect():
            if chrome.sockets:
                raise RuntimeError("omp browser relay is not reachable")
            return chrome.connect()
        relay.connect = connect
        with contextlib.redirect_stderr(io.StringIO()):
            with relay:
                chrome.sockets[0].alive = False
        self.assertEqual(chrome.settled_tabs(), USER_TABS)

    def test_applescript_waits_for_a_creation_still_on_its_way(self):
        """Ctrl-C cuts the creation short and drops the connection, the relay is gone for good,
        and the tab reaches Chrome only after the first AppleScript look."""
        chrome = FakeChrome(create_delay=0.6, apple_events=True, tabs=USER_TABS)
        relay = fake_relay(chrome)

        def connect():
            if chrome.sockets:
                raise RuntimeError("omp browser relay is not reachable")
            sock = chrome.connect()
            sock.interrupt = sock.die_on_interrupt = True
            return sock
        relay.connect = connect
        with self.assertRaises(KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()) as err:
            with relay:
                pass
        self.assertEqual(chrome.settled_tabs(), USER_TABS)
        self.assertIn("Chrome's AppleScript did", err.getvalue())

    def test_a_close_nothing_can_do_is_reported(self):
        chrome = FakeChrome(close_errors=["relay extension is not connected"] * 2, tabs=USER_TABS)
        with self.assertRaisesRegex(PI.CdpError, "Target.closeTarget: relay extension is not connected"):
            with fake_relay(chrome):
                pass

    @unittest.skipUnless(shutil.which("osacompile"), "macOS only")
    def test_the_applescript_fallback_compiles_against_chromes_dictionary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run(["osacompile", "-o", os.path.join(tmp, "close.scpt"), "-e",
                                  PI.APPLE_CLOSE.replace("MARKER", "omp-pr-images-000000000000")],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_ctrl_c_during_cleanup_waits_for_the_tab_to_close(self):
        chrome = FakeChrome(tabs=USER_TABS)
        relay, handler = fake_relay(chrome), signal.getsignal(signal.SIGINT)
        with self.assertRaises(KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()) as err:
            with relay:
                relay.ws.stall_send = 1  # the close waits on the socket while Ctrl-C arrives
                threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGINT)).start()
        self.assertEqual(chrome.settled_tabs(), USER_TABS)
        self.assertFalse(relay.ws.alive)
        self.assertIn("closing its tab first", err.getvalue())
        self.assertIs(signal.getsignal(signal.SIGINT), handler)


class Main(Scratch):
    def run_main(self, chrome, *files):
        saved = PI.Relay
        PI.Relay = lambda repo: fake_relay(chrome, repo)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    PI.main(["upload", *files])
                    code = 0
                except SystemExit as exit_:
                    code = exit_.code
        finally:
            PI.Relay = saved
        return code, out.getvalue(), err.getvalue()

    def test_uploads_print_markdown_and_close_the_tab(self):
        chrome = FakeChrome(tabs=USER_TABS)
        code, out, _ = self.run_main(chrome, self.file("a.png", png(4, 2)))
        self.assertEqual((code, out), (0, '<img width="4" alt="a" '
                                           'src="https://github.com/user-attachments/assets/1" />\n'))
        self.assertEqual(chrome.settled_tabs(), USER_TABS)

    def test_already_uploaded_wide_pair_is_reused_and_only_the_narrow_pair_goes_up(self):
        chrome = FakeChrome(tabs=USER_TABS)
        dark, light = self.file("A-dark.png", png(8, 2)), self.file("A-light.png", png(8, 2))
        ndark, nlight = self.file("A-narrow-dark.png", png(960, 6)), self.file("A-narrow-light.png", png(960, 6))
        code, out, err = self.run_main(chrome, "--themed", "--scale", "2", "--uploaded", f"{dark}=https://x/WD",
                                       "--uploaded", f"{light}=https://x/WL", dark, light, ndark, nlight)
        self.assertEqual(code, 0)
        self.assertIn("uploaded 2 file(s)", err)
        self.assertIn('(min-width: 1244px) and (prefers-color-scheme: dark)" srcset="https://x/WD"', out)
        self.assertIn('(prefers-color-scheme: light)" width="440" srcset="https://github.com/user-attachments/assets/', out)

    def test_nothing_to_upload_never_opens_a_tab(self):
        a = self.file("a.png", png(4, 2))
        def no_relay(*_):
            raise AssertionError("pr-images reached the browser")
        PI.Relay, saved = no_relay, PI.Relay
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                PI.main(["upload", "--uploaded", f"{a}=https://x/A", a])
        finally:
            PI.Relay = saved
        self.assertEqual(out.getvalue(), '<img width="4" alt="a" src="https://x/A" />\n')

    def test_a_tab_that_will_not_close_still_prints_the_uploads_and_fails(self):
        chrome = FakeChrome(close_errors=["relay extension is not connected"] * 2, tabs=USER_TABS)
        code, out, _ = self.run_main(chrome, self.file("a.png", png(4, 2)))
        self.assertIn("assets/1", out)
        self.assertRegex(str(code), r"could not close its tab \(#omp-pr-images-[0-9a-f]{12}\)")

    def test_a_video_prints_as_its_bare_url_which_github_renders_as_its_player(self):
        clip = self.file("run.mp4", b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64)
        def no_relay(*_):
            raise AssertionError("pr-images reached the browser")
        out = io.StringIO()
        PI.Relay, saved = no_relay, PI.Relay
        try:
            with contextlib.redirect_stdout(out):
                PI.main(["upload", "--uploaded", f"{clip}=https://x/V", clip])
        finally:
            PI.Relay = saved
        self.assertEqual(out.getvalue(), "https://x/V\n")


class FakeGitHub:
    """The git data API calls fork-links makes, on one fork: an optional branch head, blobs, trees
    (a tree's sha is its sorted paths, so an unchanged tree keeps its sha), commits and refs."""

    def __init__(self, head_tree=None):
        self.calls, self.blobs = [], {}
        self.head = "c0" if head_tree else None
        self.trees = {"c0": head_tree} if head_tree else {}

    def __call__(self, path, method="GET", body=None, missing_ok=False):
        self.calls.append((method, path, body))
        if path.endswith("/git/ref/heads/omp-contrib-assets"):
            return {"object": {"sha": self.head}} if self.head else None
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": self.trees[path.rsplit("/", 1)[1]]}}
        if path.endswith("/git/blobs"):
            sha = hashlib.sha1(base64.b64decode(body["content"])).hexdigest()
            self.blobs[sha] = body["content"]
            return {"sha": sha}
        if path.endswith("/git/trees"):
            paths = {e["path"] for e in body["tree"]} | set(filter(None, body.get("base_tree", "").split(",")))
            return {"sha": ",".join(sorted(paths))}
        if method == "POST" and path.endswith("/git/commits"):
            self.trees["c1"] = body["tree"]
            return {"sha": "c1"}
        return {}


class ForkLinks(Scratch):
    """images.upload = "fork-links": one commit on the fork's asset branch through the GitHub API, the
    same <picture> printed with raw.githubusercontent.com URLs, and never the browser."""

    def run_fork(self, gh, *argv):
        saved = PI.gh_api, PI.wait_loads, PI.Relay
        loaded = []
        PI.gh_api, PI.wait_loads = gh, loaded.append
        PI.Relay = lambda *_: self.fail("fork-links reached the browser")
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                PI.main(["upload", *argv])
        finally:
            PI.gh_api, PI.wait_loads, PI.Relay = saved
        return out.getvalue(), err.getvalue(), loaded

    def test_first_use_creates_the_branch_without_history_and_prints_raw_urls(self):
        dark, light = self.file("A-dark.png", png(8, 2)), self.file("A-light.png", png(8, 2) + b"\x00")
        gh = FakeGitHub()
        out, err, loaded = self.run_fork(gh, "--mode", "fork-links", "--folder", "pr-1", "--themed", "--scale", "2", dark, light)
        fork = f"{contrib_env.FORK_OWNER}/oh-my-pi"
        paths = [PI.asset_path("pr-1", p, PI.load(p)[0]) for p in (dark, light)]
        urls = [f"https://raw.githubusercontent.com/{fork}/omp-contrib-assets/{p}" for p in paths]
        self.assertIn(f'(prefers-color-scheme: dark)" srcset="{urls[0]}"', out)
        self.assertIn(f'<img width="4" alt="A" src="{urls[1]}" />', out)
        self.assertEqual(loaded, urls)  # every URL is checked to load before it is printed
        commit = next(b for m, p, b in gh.calls if m == "POST" and p.endswith("/git/commits"))
        self.assertEqual(commit["parents"], [])
        tree = next(b for m, p, b in gh.calls if p.endswith("/git/trees"))
        self.assertNotIn("base_tree", tree)
        self.assertIn(("POST", f"repos/{fork}/git/refs", {"ref": "refs/heads/omp-contrib-assets", "sha": "c1"}), gh.calls)
        self.assertIn("committed 2 file(s)", err)

    def test_an_existing_branch_gets_one_commit_on_top_of_its_head(self):
        a = self.file("a.png", png(4, 2))
        gh = FakeGitHub(head_tree="old/1-x.png")
        self.run_fork(gh, "--mode", "fork-links", "--folder", "t", a)
        commit = next(b for m, p, b in gh.calls if m == "POST" and p.endswith("/git/commits"))
        self.assertEqual(commit["parents"], ["c0"])
        tree = next(b for m, p, b in gh.calls if p.endswith("/git/trees"))
        self.assertEqual(tree["base_tree"], "old/1-x.png")
        self.assertEqual([m for m, p, _ in gh.calls if "/git/refs" in p], ["PATCH"])

    def test_files_already_on_the_branch_make_no_commit(self):
        a = self.file("a.png", png(4, 2))
        gh = FakeGitHub(head_tree=PI.asset_path("t", a, PI.load(a)[0]))
        out, _, _ = self.run_fork(gh, "--mode", "fork-links", "--folder", "t", a)
        self.assertFalse([c for c in gh.calls if c[0] in ("PATCH",) or (c[0] == "POST" and c[1].endswith("/git/commits"))])
        self.assertIn("raw.githubusercontent.com", out)

    def test_the_mode_and_fork_come_from_the_config(self):
        path = contrib_env.write_config(os.path.join(self.dir.name, "cfg", "config.toml"),
                                        '[github]\nfork_owner = "someone"\nfork_remote = "fork"\n[images]\nupload = "fork-links"\n')
        saved = os.environ["OMP_CONTRIB_CONFIG"]
        os.environ["OMP_CONTRIB_CONFIG"] = path
        PI.omp_config.load(reload=True)
        try:
            out, _, _ = self.run_fork(FakeGitHub(), self.file("a.png", png(4, 2)))
        finally:
            os.environ["OMP_CONTRIB_CONFIG"] = saved
            PI.omp_config.load(reload=True)
        self.assertIn("https://raw.githubusercontent.com/someone/oh-my-pi/omp-contrib-assets/", out)

    def test_a_files_path_carries_its_git_blob_hash(self):
        a = self.file("a.png", png(4, 2))
        blob = subprocess.run(["git", "hash-object", a], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(PI.asset_path("pr-7/", a, PI.load(a)[0]), f"pr-7/{blob[:10]}-a.png")


class RealSocket(unittest.TestCase):
    """The deadline against the real websockets client and a peer that stops reading. Runs
    through `uv` when this Python lacks websockets, as the script itself does."""

    def test_a_send_to_a_peer_that_stops_reading_ends_at_the_deadline(self):
        if importlib.util.find_spec("websockets") is None:
            if not shutil.which("uv"):
                self.skipTest("needs websockets or uv")
            here = os.path.dirname(os.path.abspath(__file__))
            test = "test_pr_images.RealSocket.test_a_send_to_a_peer_that_stops_reading_ends_at_the_deadline"
            run = subprocess.run(["uv", "run", "--quiet", "--with", "websockets>=13", "python3", "-m",
                                  "unittest", test], cwd=here,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr)
            return
        from websockets.sync.client import connect
        server = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(server.close)
        peers = []

        def handshake():
            peer, _ = server.accept()
            peers.append(peer)
            request = b""
            while b"\r\n\r\n" not in request:
                request += peer.recv(4096)
            key = re.search(rb"Sec-WebSocket-Key: (\S+)", request, re.I)[1]
            accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            peer.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")  # and never reads again
        threading.Thread(target=handshake, daemon=True).start()
        relay = PI.Relay("can1357/oh-my-pi")
        relay.ws = connect(f"ws://127.0.0.1:{server.getsockname()[1]}", max_size=None, close_timeout=1).__enter__()
        self.addCleanup(lambda: [p.close() for p in peers])
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "the relay stopped reading"):
            for _ in range(8):  # the kernel buffers take the first few MiB
                relay.call("Runtime.evaluate", "S1", 0.5, expression="x" * PI.CHUNK)
        self.assertLess(time.monotonic() - start, 8)


class UploadScript(unittest.TestCase):
    """UPLOAD_JS in Node with GitHub's page faked: it must not send a request for a file a reload
    cut short, or from a page of another repo."""

    def run_js(self, chunks, size, nwo="can1357/oh-my-pi", page_nwo="can1357/oh-my-pi"):
        node = shutil.which("node") or shutil.which("bun")
        if not node:
            self.skipTest("needs node or bun")
        harness = f"""
const metas = {{'fetch-nonce': 'N', 'octolytics-dimension-repository_id': '1',
               'octolytics-dimension-repository_nwo': {json.dumps(page_nwo)}}};
globalThis.document = {{querySelector: s => {{ const m = /name="([^"]+)"/.exec(s);
  return m && metas[m[1]] ? {{content: metas[m[1]]}} : null; }}}};
globalThis.location = {{href: 'https://github.com/' + {json.dumps(page_nwo)}}};
const calls = [];
globalThis.fetch = async url => {{ calls.push(String(url)); return {{ok: false, status: 500, text: async () => 'stub'}}; }};
if ({json.dumps(chunks)} !== null) globalThis.__prImages = {{k: {json.dumps(chunks)}}};
const result = await ({PI.UPLOAD_JS})({{key: 'k', name: 'a.png', type: 'image/png', size: {size}, nwo: {json.dumps(nwo)}}});
console.log(JSON.stringify({{result, calls}}));
"""
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as fh:
            fh.write(harness)
        self.addCleanup(os.unlink, fh.name)
        out = subprocess.run([node, fh.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_a_file_cut_short_by_a_reload_sends_nothing(self):
        data = base64.b64encode(os.urandom(3000)).decode()
        out = self.run_js([data[:2000]], 3000)
        self.assertEqual(out["calls"], [])
        self.assertIn("the page reloaded during the upload (1500 of 3000 bytes)", out["result"]["error"])

    def test_chunks_lost_to_a_reload_send_nothing(self):
        out = self.run_js(None, 3000)
        self.assertEqual(out["calls"], [])
        self.assertIn("(0 of 3000 bytes)", out["result"]["error"])

    def test_a_page_of_another_repo_sends_nothing(self):
        data = base64.b64encode(os.urandom(30)).decode()
        out = self.run_js([data], 30, page_nwo=f"{contrib_env.FORK_OWNER}/oh-my-pi")
        self.assertEqual(out["calls"], [])
        self.assertIn("not can1357/oh-my-pi", out["result"]["error"])

    def test_a_whole_file_from_the_right_repo_asks_for_an_upload_policy(self):
        data = base64.b64encode(os.urandom(30)).decode()
        out = self.run_js([data[:20], data[20:]], 30, nwo="Can1357/Oh-My-Pi")
        self.assertEqual(out["calls"], ["/upload/policies/assets"])
        self.assertIn("upload policy: HTTP 500", out["result"]["error"])

    def test_an_uploaded_video_counts_as_there_when_its_url_redirects_to_storage(self):
        # A <video> in pr-images' background tab never loads (it hung a real upload, 2026-10-15), so a
        # video is checked by its redirect; a missing asset answers 404.
        node = shutil.which("node") or shutil.which("bun")
        if not node:
            self.skipTest("needs node or bun")
        data = base64.b64encode(os.urandom(30)).decode()
        for head, expected in (("{type: 'opaqueredirect', status: 0}", {"href": "https://github.com/user-attachments/assets/v", "repo": "1"}),
                               ("{type: 'basic', status: 404}", {"error": "https://github.com/user-attachments/assets/v does not load after the upload"})):
            harness = f"""
const metas = {{'fetch-nonce': 'N', 'octolytics-dimension-repository_id': '1',
               'octolytics-dimension-repository_nwo': 'can1357/oh-my-pi'}};
globalThis.document = {{querySelector: s => {{ const m = /name="([^"]+)"/.exec(s);
  return m && metas[m[1]] ? {{content: metas[m[1]]}} : null; }}, createElement: () => {{ throw new Error('no <video>'); }}}};
globalThis.Image = class {{ set src(v) {{ throw new Error('no <img>'); }} }};
globalThis.location = {{href: 'https://github.com/can1357/oh-my-pi'}};
const json = {{upload_url: 'S3', header: {{}}, form: {{}}, asset_upload_url: 'FIN', asset_upload_authenticity_token: 'T',
               href: 'https://github.com/user-attachments/assets/v'}};
globalThis.fetch = async (url, opts) => opts?.redirect === 'manual' && opts.method === 'HEAD' ? {head}
  : ({{ok: true, status: 200, json: async () => json, text: async () => ''}});
globalThis.__prImages = {{k: [{json.dumps(data)}]}};
console.log(JSON.stringify(await ({PI.UPLOAD_JS})({{key: 'k', name: 'run.mp4', type: 'video/mp4', size: 30, nwo: 'can1357/oh-my-pi'}})));
"""
            with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as fh:
                fh.write(harness)
            self.addCleanup(os.unlink, fh.name)
            out = subprocess.run([node, fh.name], capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout), expected)


if __name__ == "__main__":
    unittest.main()
