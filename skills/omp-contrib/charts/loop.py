#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Cut a motion loop for a PR body from a screen recording: a GIF that plays and loops on its own.

usage: loop.py SRC --out PREFIX [--from S] [--to E] [--make loop,still,mp4] [--hold 1.5] [--single] [--no-ring | --ring-above PX]
  SRC       the recording; by default a side-by-side clip, `main` in the left half and the PR in the
            right, each half with its own caption (as the series-1 demo clips are)
  --from/--to  the cut, in seconds of SRC (default: all of it): for a loop, the tightest span that
            still shows the behaviour
  --make    what to write, comma-separated (default loop):
              loop   PREFIX.gif, PREFIX-narrow.gif and their stills (below)
              still  only PREFIX-still.png and PREFIX-narrow-still.png, the cut's last frame in both
                     layouts: a whole task's result in view (`pr-images upload --still`)
              mp4    PREFIX.mp4, the cut re-encoded small for the collapsed full run (H.264 CRF 28,
                     at most 1920 px wide, no audio, faststart): `pr-images upload PREFIX.mp4`
  --hold    seconds the last frame is held before the loop restarts, so its result can be read
  --single  SRC is one pane (a short moment, not a before/after); the phone layout is SRC scaled
  --no-ring leave out the progress ring
  --ring-above  lift the ring above the bottom PX rows of SRC (its caption bar: 80 on the series-1
            clips), for a clip whose caption runs into the bottom-right corner
  --out     writes PREFIX.gif (1560 px wide: GitHub's 780 px column at 2x), PREFIX-narrow.gif (the
            phone layout, 880 px wide: the left half over the right half, or SRC scaled with --single),
            and PREFIX-still.png / PREFIX-narrow-still.png (each layout's last frame, without the ring:
            what a reader who asked for reduced motion sees). `../scripts/pr-images upload --loop
            --scale 2 PREFIX*.gif PREFIX*-still.png` uploads the four as one <picture>.

The cut is real footage only: trimmed, scaled, the panes stacked for phones, the last frame held. The
progress ring (on by default, about 22 CSS px at display size) sits in the bottom-right corner, empty
on the first frame and full on the last, filling clockwise from 12 o'clock, so a viewer can tell how
far through the loop they are; a soft dark disc behind it keeps it legible on any footage. On a
side-by-side clip it lands in the PR caption bar, right of the caption, unless that caption runs into
the corner (`--ring-above`); look at the first frames to check it covers nothing. Needs ffmpeg and
ffprobe.
"""
import argparse
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

FPS = 12
WIDE, NARROW = 1560, 880   # 2x GitHub's 780 px column; 2x the 440 px phone layout (pr-images' NARROW_MIN_PX)
RING = {"wide": 44, "narrow": 56}  # px in the file: 22 CSS px at 780, 20-28 at the phone layout's 324-440
SUPERSAMPLE = 4


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def width(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                          "-of", "csv=p=0", path], check=True, capture_output=True, text=True)
    return int(out.stdout.strip())


def frame_count(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_frames", "-of", "csv=p=0", path], check=True, capture_output=True, text=True)
    return int(out.stdout.strip())


def ring_frame(fraction, diameter):
    """One RGBA ring, `fraction` of it filled clockwise from 12 o'clock."""
    d = diameter * SUPERSAMPLE
    stroke, inset = max(SUPERSAMPLE, round(d * 0.13)), round(d * 0.16)
    box = (inset, inset, d - 1 - inset, d - 1 - inset)
    im = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.ellipse((0, 0, d - 1, d - 1), fill=(13, 17, 23, 170))               # backing disc
    draw.arc(box, 0, 360, fill=(255, 255, 255, 70), width=stroke)           # track
    if fraction > 0:
        draw.arc(box, -90, -90 + 360 * fraction, fill=(255, 255, 255, 240), width=stroke)
    return im.resize((diameter, diameter), Image.LANCZOS)


def layout_filter(name, single):
    if name == "wide":
        return f"scale={WIDE}:-2:flags=lanczos"
    if single:
        return f"scale={NARROW}:-2:flags=lanczos"
    return (f"split[a][b];[a]crop=iw/2:ih:0:0[l];[b]crop=iw/2:ih:iw/2:0[r];[l][r]vstack,"
            f"scale={NARROW}:-2:flags=lanczos")


def build(args, name, gif, still, tmp):
    cut = f"trim=start={args.start}:end={args.end},setpts=PTS-STARTPTS,{layout_filter(name, args.single)}"
    frames = os.path.join(tmp, f"{name}.mkv")
    ffmpeg("-i", args.src, "-filter_complex", f"{cut},tpad=stop_mode=clone:stop_duration={args.hold},fps={FPS}",
           "-c:v", "ffv1", frames)
    ffmpeg("-i", args.src, "-filter_complex", cut, "-update", "1", still)
    inputs, head = ["-i", frames], "[0:v]"
    if args.ring:
        n, d = frame_count(frames), RING[name]
        if n < 2:
            raise SystemExit(f"loop.py: the loop is {n} frame long; a ring needs 2 or more (lengthen the cut or --no-ring)")
        rings = os.path.join(tmp, f"ring-{name}")
        os.makedirs(rings)
        for i in range(n):
            ring_frame(i / (n - 1), d).save(os.path.join(rings, f"{i:05d}.png"))
        # SRC rows map to output rows at the output width over the width of the pane it shows
        pane = width(args.src) / (1 if name == "wide" or args.single else 2)
        lift = round(args.ring_above * (WIDE if name == "wide" else NARROW) / pane)
        margin = d // 4
        inputs += ["-framerate", str(FPS), "-i", os.path.join(rings, "%05d.png")]
        head = f"[0:v][1:v]overlay=x=W-w-{margin}:y=H-h-{margin}-{lift}:eof_action=pass,"
    palette = ("split[x][y];[x]palettegen=stats_mode=diff[p];"
               "[y][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
    ffmpeg(*inputs, "-filter_complex", head + palette, "-loop", "0", gif)


def still_only(args, name, still):
    cut = f"trim=start={args.start}:end={args.end},setpts=PTS-STARTPTS,{layout_filter(name, args.single)}"
    ffmpeg("-i", args.src, "-filter_complex", cut, "-update", "1", still)


def mp4(args, out):
    ffmpeg("-ss", str(args.start), "-to", str(args.end), "-i", args.src, "-vf", "scale='min(1920,iw)':-2",
           "-c:v", "libx264", "-crf", "28", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-an", out)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


MAKE = ("loop", "still", "mp4")


def main(argv):
    parser = argparse.ArgumentParser(usage=__doc__.split("\n\n", 2)[1].removeprefix("usage: "))
    parser.add_argument("src")
    parser.add_argument("--from", dest="start", type=float, default=0.0)
    parser.add_argument("--to", dest="end", type=float)
    parser.add_argument("--make", default="loop")
    parser.add_argument("--hold", type=float, default=1.5)
    parser.add_argument("--out", required=True)
    parser.add_argument("--single", action="store_true")
    ring = parser.add_mutually_exclusive_group()
    ring.add_argument("--no-ring", dest="ring", action="store_false")
    ring.add_argument("--ring-above", type=int, default=0, metavar="PX")
    args = parser.parse_args(argv)
    make = args.make.split(",")
    if not make or not set(make) <= set(MAKE):
        parser.error(f"--make takes a comma-separated list of {', '.join(MAKE)}")
    if not os.path.isfile(args.src):
        parser.error(f"{args.src}: no such file")
    if args.end is None:
        args.end = duration(args.src)
    if not 0 <= args.start < args.end:
        parser.error("--from must be at least 0 and before --to")
    if args.hold < 0:
        parser.error("--hold must be 0 or more")
    if args.ring_above < 0:
        parser.error("--ring-above must be 0 or more")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, gif, still in (("wide", f"{args.out}.gif", f"{args.out}-still.png"),
                                 ("narrow", f"{args.out}-narrow.gif", f"{args.out}-narrow-still.png")):
            if "loop" in make:
                build(args, name, gif, still, tmp)
                written += [gif, still]
            elif "still" in make:
                still_only(args, name, still)
                written.append(still)
    if "mp4" in make:
        mp4(args, f"{args.out}.mp4")
        written.append(f"{args.out}.mp4")
    for f in written:
        print(f"{f}\t{os.path.getsize(f)} bytes")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except subprocess.CalledProcessError as err:
        sys.exit(f"loop.py: {err.cmd[0]} failed ({err.returncode})")
