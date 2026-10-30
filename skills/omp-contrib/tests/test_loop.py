"""charts/loop.py on a synthetic side-by-side clip, through ffmpeg and uv as in use: the four files and
their sizes, the frame count of cut plus hold, the phone layout's stacked panes, and the progress ring
(empty on the first frame, full on the last, absent from the stills and under --no-ring).
Run: python3 -m unittest discover -s tests"""
import contrib_env  # noqa: F401  (a hermetic config, like every test module)
import json
import os
import shutil
import subprocess
import tempfile
import unittest

LOOP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "charts", "loop.py")


def frame(path, index, crop=None):
    """(width, height, rgb bytes) of one frame of an image or GIF, optionally cropped (w:h:x:y)."""
    vf = f"select=eq(n\\,{index})" + (f",crop={crop}" if crop else "")
    probe = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", vf, "-frames:v", "1", "-f", "image2pipe",
                            "-vcodec", "ppm", "-"], check=True, capture_output=True).stdout
    header = probe.split(b"\n", 3)
    w, h = map(int, header[1].split())
    return w, h, header[3]


def bright(rgb, at_least=200):
    return sum(1 for i in range(0, len(rgb), 3) if min(rgb[i:i + 3]) >= at_least)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("uv"), "needs ffmpeg and uv")
class Loop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.src = os.path.join(cls.dir, "clip.mp4")
        # 4 s, 1920x560: a red left pane (main), a grey right pane (the PR) with a white bar along its top
        # that moves 200 px a second (x = 200 t), so the cut and the still can be told apart in time.
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0xb03030:s=960x560:d=4:r=30",
                        "-f", "lavfi", "-i", "color=c=0x808080:s=960x560:d=4:r=30",
                        "-f", "lavfi", "-i", "color=c=white:s=20x40:d=4:r=30", "-filter_complex",
                        "[1:v][2:v]overlay=x='200*t':y=20[r];[0:v][r]hstack", "-pix_fmt", "yuv420p", cls.src], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def build(self, name, *extra):
        out = os.path.join(self.dir, name)
        subprocess.run([LOOP, self.src, "--from", "1", "--to", "3", "--hold", "0.5", "--out", out, *extra],
                       check=True, capture_output=True)
        return out

    def test_four_files_at_the_column_and_phone_widths_with_cut_plus_hold_frames(self):
        out = self.build("a")
        self.assertEqual(frame(f"{out}.gif", 0)[:2], (1560, 456))
        self.assertEqual(frame(f"{out}-still.png", 0)[:2], (1560, 456))
        self.assertEqual(frame(f"{out}-narrow.gif", 0)[:2], (880, 1026))
        self.assertEqual(frame(f"{out}-narrow-still.png", 0)[:2], (880, 1026))
        count = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_read_frames", "-of", "csv=p=0", f"{out}.gif"], check=True,
                               capture_output=True, text=True).stdout
        self.assertEqual(int(count), 30)  # (3 - 1 + 0.5) s at 12 fps

    def test_the_cut_starts_at_from_and_the_still_is_its_last_frame(self):
        out = self.build("f", "--no-ring")
        # the bar's centre at t: source x 960 + 200 t + 10, y 40; the wide layout is 0.8125 of the source
        at = lambda t: f"4:4:{round((970 + 200 * t) * 0.8125) - 2}:{round(40 * 0.8125) - 2}"
        self.assertEqual(bright(frame(f"{out}.gif", 0, at(1))[2]), 16)
        self.assertEqual(bright(frame(f"{out}-still.png", 0, at(2.967))[2]), 16)
        self.assertEqual(bright(frame(f"{out}-still.png", 0, at(1))[2]), 0)

    def test_a_ring_on_a_one_frame_loop_is_refused(self):
        run = subprocess.run([LOOP, self.src, "--from", "1", "--to", "1.05", "--hold", "0", "--out",
                              os.path.join(self.dir, "g")], capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("a ring needs 2 or more", run.stderr)

    def test_the_phone_layout_stacks_main_over_the_pr(self):
        out = self.build("b")
        _, _, top = frame(f"{out}-narrow-still.png", 0, "1:1:440:200")
        _, _, bottom = frame(f"{out}-narrow-still.png", 0, "1:1:440:800")
        self.assertGreater(top[0], top[2] + 60)          # red: main
        self.assertLess(abs(bottom[0] - bottom[2]), 12)  # grey: the PR

    def test_the_ring_fills_from_empty_to_full_and_stays_out_of_the_stills(self):
        out = self.build("c")
        for layout, side, x, y in (("", 60, 1500, 396), ("-narrow", 72, 808, 954)):
            crop = f"{side}:{side}:{x}:{y}"
            self.assertEqual(bright(frame(f"{out}{layout}.gif", 0, crop)[2]), 0, layout)
            self.assertGreater(bright(frame(f"{out}{layout}.gif", 29, crop)[2]), 150, layout)
            # the still's corner is the PR pane's grey throughout: no backing disc, no ring
            self.assertEqual(bright(frame(f"{out}{layout}-still.png", 0, crop)[2], 100), side * side, layout)

    def test_no_ring_leaves_the_corner_as_filmed(self):
        out = self.build("d", "--no-ring")
        self.assertEqual(bright(frame(f"{out}.gif", 29, "60:60:1500:396")[2]), 0)

    def test_ring_above_lifts_it_over_the_caption_bar_in_both_layouts(self):
        out = self.build("e", "--ring-above", "80")  # 80 source rows: 65 px wide, 73 px narrow
        for layout, side, x, bar_y, lifted_y in (("", 60, 1500, 396, 330), ("-narrow", 72, 808, 954, 870)):
            self.assertEqual(bright(frame(f"{out}{layout}.gif", 29, f"{side}:{side}:{x}:{bar_y}")[2]), 0, layout)
            self.assertGreater(bright(frame(f"{out}{layout}.gif", 29, f"{side}:{side}:{x}:{lifted_y}")[2]), 150, layout)

    def test_make_still_and_mp4_write_the_end_frame_and_a_small_h264_copy_of_the_whole_clip(self):
        out = os.path.join(self.dir, "h")
        subprocess.run([LOOP, self.src, "--make", "still,mp4", "--out", out], check=True, capture_output=True)
        self.assertEqual(sorted(f for f in os.listdir(self.dir) if f.startswith("h")), ["h-narrow-still.png", "h-still.png", "h.mp4"])
        # no --to: the end frame is the clip's last, the bar at x = 200 * 3.967
        self.assertEqual(bright(frame(f"{out}-still.png", 0, f"4:4:{round((970 + 200 * 3.967) * 0.8125) - 2}:24")[2]), 16)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width:format=duration",
                                "-of", "json", f"{out}.mp4"], check=True, capture_output=True, text=True).stdout
        info = json.loads(probe)
        self.assertEqual([(s["codec_name"], s["width"]) for s in info["streams"]], [("h264", 1920)])
        self.assertAlmostEqual(float(info["format"]["duration"]), 4, delta=0.1)

    def test_make_refuses_an_unknown_output(self):
        run = subprocess.run([LOOP, self.src, "--make", "gif", "--out", os.path.join(self.dir, "i")], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("--make takes", run.stderr)


if __name__ == "__main__":
    unittest.main()
