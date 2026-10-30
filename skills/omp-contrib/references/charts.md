# Charts and drawn figures in a PR body

Which form an idea takes is decided in [framing.md](framing.md), *Visuals*. This file is how to make a
chart or a drawn figure (decision flow, routing diagram, timeline, turn strip, literal text): the toolkit
in `../charts/`, the reader rules, and the checks before it goes in a body. The chart rules come from a
review of 14 published charts across #15434, #15402, #15291, #15447, #15446, #15275 and #15604; the
figure rules from drawn figures published in #15402, #15105, #15569, #15489, #15562 and #15502. Paths
here are relative to this skill's `references/` folder.

## Workflow

1. **Find the source.** Drawing for a body you are writing, it is the runs and code you just worked from.
   Redrawing a published table, find its run files in your omp sessions: `grep` a distinctive number
   with its unit across `~/.omp/agent/sessions/` ("43.5 steps", not "210 s", which matched 24 sessions;
   the eval `archive` namespace lists sessions and searches their prompts and recaps), then `read` the
   calls of the session it finds (a `.jsonl`, filtered with `?q=<jq>`): they name the paths. Hits in
   other agents' studies cite the run dirs too; follow those paths. Run files can sit outside the
   scratch dirs; a worktree's scratch `HANDOFF.md` often lists them. If the per-run data no longer
   exists, chart only what survives and say so in the footer, or keep the table. For a diagram, the PR's
   code at its head: every branch, route and step is something a function does, and numbers on it come
   from the body's Testing or its run files.
2. **Work in the task scratch dir**, one folder per PR: `source/` (copied run files, or for a diagram
   the code excerpts, plus a README naming where each came from: file and symbol at a commit). A
   timeline or decision flow needs only a `figures.json` (its fields are in `../charts/lib/shapes.mjs`'s
   header; it is placed at a marker line in the draft or in a table's place). Any other figure is a
   `chart.mjs` with both layouts of each image (*Phone layout* below), and a chart adds a derive script
   (`derive.py` or `.mjs`) that writes `data.json`; the contract is in `../charts/run.mjs`'s header.
   `../charts/examples/` has two published ones to read for the API, not to copy as a form: lines over
   repeated steps with every run as a ring (15434, whose `narrow()` reuses the wide panels stacked), and
   a decision flow drawn with `draw.mjs` (15105). Each has its `body-before.md`, so `--body` drafts it.
3. **Derive every number.** Each value in `data.json` records its source (file and key). Values the reader
   sees (percent change, "x times faster", "clear") are computed there with their formula and verdict rule
   ("clear" = the 95% interval excludes no change). Recompute the published table's numbers and compare: if
   they disagree with the run files, stop and report it; never silently pick one. An arm's numbers come
   from one build's runs: #15293's first draft counted an early build's success for the PR and its
   reviewer failed it. Check which build each arm actually ran (its run metadata): if it is not the
   merged head, name the commit in `<details>` and check that the diff between them can't change the
   result; reading the diff is that check when the rig can't rerun, so the body says it wasn't rerun.
   A diagram that disagrees with the body's own text is the same case: the code wins, and the body's
   text is corrected (*Placing it*).
4. **Draft:** `bun ../charts/run.mjs DIR` (first run: `bun install` in `charts/`).
   It fetches the live body (or takes `--body FILE`: a body being written, or a queued one), renders each
   image's wide layout at 2x and phone layout at 3x, dark and light, writes `out/body.md` from `place()`
   and `out/body.diff`, and runs the page check: the draft body swapped into the real PR page, signed out,
   at 1280, 1100, 430 and 390 px windows, dark and light (`out/page-<width>-<scheme>.png`), where every
   picture must show the source its media picks, keep its shape, render its smallest text at 11 px or
   more and stay sharp (2 image pixels per CSS pixel), and the page must not scroll sideways. With
   `--body` there is no PR page yet: it renders the body at a desktop and a phone width instead
   (`out/context{,-phone}-{dark,light}.png`), and `--verify` runs the page check once the PR is open.
   Then precheck's body checks (in your oh-my-pi checkout: `$OMP_REPO`, else `paths.checkout`, else
   the clone you run from; without one they are skipped and say so).
   It renders in a headless Chrome, never your own profile: `--chrome PATH`, else `$CHROME_PATH`, else
   omp's Chrome for Testing (`~/.omp/puppeteer/chrome/`, installed the first time omp opens a `browser`
   tab), else on Linux and Windows a system Chrome. pngquant and oxipng shrink the PNGs; without them
   it warns once and the files stay larger.
   Look at every PNG and every page shot: nothing clipped, colliding or illegible. (`read` can return the
   earlier image for a path that was overwritten; if a redraw looks unchanged, view a copy under a new
   name.) An image adds nothing to precheck's 3,000-character count; the table it replaces never counted
   either.
5. **Cold read:** `python3 ../charts/cold-read.py DIR`, both layouts against the
   same takeaway (see *Takeaway* below).
6. **Independent review** by a fresh `reviewer` (another model family than the author), read-only,
   given: every number on the image, in the alt text and in the new `<details>` traces to `source/` at
   the printed rounding; derived values follow their rule; every branch, route, step or quoted line of a
   diagram matches the code at the PR's head (file and symbol); no over-claim (title or verdict stronger
   than the data or code, the wrong arm called `main` or "this PR", pooled cohorts not named); the rest
   of the body unchanged (`out/body.diff`) except reported corrections; dark and light PNGs of both
   layouts legible, the phone layout showing the same values and words as the wide one. Fix, then have
   the same criteria re-checked.
7. **Publish:** `bun run.mjs DIR --upload` uploads the placed images with `../scripts/pr-images`
   (`--themed --scale 2`, alt text from the chart, the way `images.upload` says: *Uploading* below; a
   file uploaded before, by its hash in `out/uploads.json` or in
   `${XDG_CACHE_HOME:-~/.cache}/omp-contrib/uploads.json`, shared by every body folder, is reused, not
   uploaded again) and writes `out/body-final.md`. A body not yet opened is what you queue
   (`pr-queue add … --body out/body-final.md`, or `pr-queue set` for a queued entry); `pr-queue open`
   posts it. For an open PR whose live body still equals `out/live.md`,
   `../scripts/pr-body N out/body-final.md` (`--dry-run` first). Then
   `bun run.mjs DIR --verify` (with `pr` in `figures.json` or `meta`): it reads the body back and runs the
   page check on the live page (`out/live-<width>-<scheme>.png`). A body rewrite keeps the own-words line
   and the images already in the body byte for byte ([framing.md](framing.md)).

## Write for a reader who hasn't seen our benches

The reader is a maintainer skimming with no context: no bench names, no arm names, no idea what the tasks
do. The chart makes its point without the PR text; the detail stays one click away in `<details>`.

1. **Title = the takeaway**, in plain words, readable alone: "At 17 history images (Opus on main), recall
   falls to 18% by the 5th compaction; at 40 it stays at 97%". Never a metric name ("Recall per cap").
2. **Name things by what they are**, never by our shorthand: "17 history images (main)", not "cap 17";
   "to-do reminders on (omp's default)", not "omp defaults"; "main" / "this PR", not "base" / "c3". Units
   are the reader's ("model turns to finish a task", "% fewer"), and every count says what it counts
   ("150–157 keystrokes": a bare "150–180" was read as milliseconds).
3. **Baseline visible, change as the hero:** before → after in the reader's unit, the change in the
   biggest text ("20.0 → 15.7 turns, 22% fewer"). Never a delta from an invisible zero.
4. **Uncertainty, quietly.** Small n: every run as a mark (the #15184 paste strip is the model: counts beat
   statistics), and every mark stays separable: runs closer than a mark's width are offset, not drawn
   over each other. Large n: a light band or a plain verdict ("clear", "within run-to-run noise").
   Bracketed intervals, "bootstrap", "p10–p90" go to `<details>`. A band means one thing: never draw an
   interval of the change around one arm's value.
5. **One point per chart.** Secondary arms, metrics and conditions go to `<details>` unless they are the
   point.
6. **Every label names the cohort it counts.** A count beside a timeline covers the build that timeline
   shows; a series-stack or rerun arm is labelled as such, never "this PR"; pooled runs from different
   builds or setups name each.
7. **One plain sentence of what was run** as the footer ("12 coding tasks, 3 runs each, GPT-6.1 Sol").
   Shas, run ids, guest names and scripts go to `<details>`. When shown numbers don't combine the obvious
   way (before → after medians beside a median paired saving), the footer says why.

## Look (`../charts/lib/look.mjs`)

- 780 px wide (the body's content width at a 1440 px window), height as needed, 2x. System font stack.
  The phone layout is `NARROW` (320 px) wide in the same type sizes, rendered at 3x (*Phone layout*).
- Title 15 px 600; panel labels 14 px 600; other text 11.5–14 px in `t.fg` or `t.muted` only, which pass
  4.5:1 on the canvas. No text on a coloured fill unless it passes 4.5:1.
- Colour roles from `THEMES`, never hex in chart code: `t.main` (orange) is `main` today, `t.pr` (blue)
  this PR, `t.alt` (purple) a third arm, `t.ref` reference lines, `t.good`/`t.bad` outcome marks only.
  Colour is never the only key: label every series at its mark or line end.
- Magnitudes start at 0; ratios centre on 1.0 and deltas on 0, with the reference as a 1 px `t.ref` line
  and a label. A log scale only in its own panel, labelled. Gridlines 0.6 px dashed, baselines 1 px.
- Lines join only measured points, and the footer says where measurements were taken.
- Print the values that carry the point beside their marks, rounded as the body rounds them.

## Phone layout

Every image also draws `narrow(data, theme)`, 320 px wide, and the `<picture>` shows it below a 1244 px
window. GitHub's PR column is 780 px only from a 1278 px window up and shrinks with the
window (324 px at 390), so a wide chart's 11.5 px text falls under 11 px below 1244 and to about 5 px on a
phone; at 320 px the phone layout keeps it at 11.5 px from a 375 px window up. The GitHub iOS app
shows the phone layout too (#15434). Same data, same printed
values and roundings, same words, same type sizes and rules as the wide chart, never a new claim:
- side-by-side panels stack, one under the other, at full width; a left label column becomes a header
  line above its row or strip; a left-to-right flow or timeline turns to run top to bottom;
- the title, subtitle, notes and footer wrap (`para` / `wrap` in look.mjs; its width estimate errs wide,
  so check the PNG for a cut-off last character all the same);
- a plot narrows before its end labels shrink: every value printed on the wide chart is on the phone one.

In a half-width desktop window (768–1243 px, a 350–745 px column) the phone layout grows to at most
440 px rather than sitting at 320 beside empty space: its sources carry
`width="440"`, and a phone's narrower column shrinks it back. That is why it renders at 3x (960 px):
at 440 px that is still 2 image pixels per CSS pixel, and pr-images refuses a phone layout under 880 px.
The order of the sources is pr-images' job too: the wide pair carries `(min-width: 1244px)` and comes
first, because for a viewer with a fixed GitHub theme `<themed-picture>` rewrites every source to match
that theme at any width, and the first one then wins: such viewers see the wide image at every width,
never the phone one on a desktop. The tags carry a width and no height, or GitHub's CSS stretches them.

## Opening image

When What's table is a measured `main`-vs-PR comparison ([framing.md](framing.md), *Visuals*), an image
drawn for that spot takes its place. It carries the whole summary, where a Testing chart carries one
piece of evidence:

1. **Every measured row of the table, at its grain**: one value or range per condition, as the table
   gave it. Per-load, per-run and interval detail stays with the Testing chart, which makes a different
   point (where the effect holds, how sure it is) under a different title. If both would draw the same
   numbers at the same grain, there is one chart, in What, and the Testing chart drops that part,
   redrawn from the same data; its `<details>` keeps every row. #15291: the
   off-screen result (3,831 → 165 ms, 23×) is the PR's most striking number, so the opening image
   carries the whole off-screen story (2,000 and 8,000 windows) beside the Mac and VM ranges, and
   the Testing chart keeps only the per-load, per-window detail of the everyday rows.
2. **Title = the headline sentence's claim** with its numbers, never beyond the own-words line. At
   1280 × 800, signed out, the first screen showed only the image's top 144–227 px on the four PRs tried,
   and on a 390 px phone the image began at or below the bottom of the first screen: the sentence above it
   carries the claim on its own (framing.md, rule 1), and the title repeats it for the reader who scrolls.
3. **Each row's change in the reader's terms** as its hero ("32–37 ms faster", "39–49% less time"),
   never a signed delta: "−32 to −37 ms" came back as an unclear label in the cold read.
4. **Magnitudes that don't share an axis get their own panels** (an everyday capture in ms beside a
   stress case in seconds), not one log axis.
5. **A row that isn't a measurement leaves the image** and becomes one bold line right under it in the
   row's own words (`**Cost:** a minimized window pays a second, full fetch (+10 to +27 ms).`). Its
   characters count toward precheck's 3,000; the picture and the `<details>` table don't.
6. **The exact table follows**, verbatim, in `<details>` (*Placing it*); roboomp's `fetch_pr` hands the
   reviewer the raw Markdown, so alt text and `<details>` reach the bots wherever the image sits.

## Drawn figures (`../charts/lib/shapes.mjs`, `../charts/lib/draw.mjs`)

A drawn figure follows the reader rules and the look above. A decision flow or a timeline (steps as
columns, `main`'s lane and the PR's) is drawn from `figures.json` by `shapes.mjs`, both layouts included;
a figure that needs another layout uses the parts in `draw.mjs`: `title`, `note` (the footer), `box`
(wrapped text, a kicker line, the party's stroke, an outcome mark), `arrow`, `label` (an edge's "yes" or
"on main"), `swatch`, and `code` (monospace lines, the change marked). Each returns the height it took,
so a layout stacks parts by adding heights. What each form needs:

- **Turn strip** (#15402): one box per model turn of a real recorded run on each side, labelled with
  the tools called in it, the boxes that disappear drawn dashed. One run shows how, not how much: the
  headline number goes in the footer, from the same cohort as the body's. It fits about 10 turns in
  780 px; the phone layout stacks the two runs as columns, turn numbers down the side.
- **Decision flow** (#15105): the questions down one spine in the order the reader can follow,
  outcomes to the side, `main`'s path and the PR's in their colours, the outcome that changed as the
  last box. Shared outcomes ("left alone, with a note") are drawn once and joined. If the code asks in
  another order with the same outcomes, the footer says so.
- **Timeline** (#15569, #15562): lanes for `main` and the PR on one clock, the gap or stop that is the
  point visible at a glance. Durations that can't share a scale (5 s, minutes, 330 ms) make it "not to
  scale" with each duration as a label. Exceptions go to `<details>`, not onto the lanes.
- **Routing diagram** (#15489): one check, its routes, each route's cost on the route. Name what decides
  the route (the check), not lists of cases that only happen to take it; a case that applies to both
  routes is a row under the fork, not a third branch.
- **Literal text** (#15502): the real text, generated from the run (a snapshot, a prompt), before and
  after, with `code()` boxing what `main` leaks or gets wrong in `t.bad` and the fix in `t.good`.
  The phone layout passes `code()` a `width`: about 46 characters fit 320 px at 11.5 px, so longer
  lines wrap after their last `: ` or space, never inside a mark, and the footer says "long lines
  wrapped". GitHub's `diff` code block reads well on a desktop but scrolls sideways on a phone and
  shows the text's own leading dashes as deletions.

The footer says what the figure is ("Drawing of the PR's routing code; times from its Testing table").
Every branch, route, step and quoted line is reviewed against the code (*Workflow*, step 6).

## Motion (`../charts/loop.py`)

Behaviour on screen goes in as a GIF loop, because GitHub's video player loses the skimming reader. Measured on
live pages, 2026-10-15:

- An uploaded MP4 becomes GitHub's player. It doesn't autoplay or loop, and its controls cover the bottom of
  the paused first frame, where the clips' captions sit. On an iPhone, Safari shows a blank box until it's
  tapped, and a tap forces fullscreen (in the GitHub app too). It has no phone or theme variant
  and no alt text. In cold reads, the paused player matched 1 of 8; the first frame of a loop cut from the
  same clip matched 7 of 8.
- A GIF autoplays and loops inline, in the GitHub iOS app too (#14160). Inside `<picture>` it gets a phone
  layout that the app honours (#15434) and alt text. GitHub pauses a bare GIF for a reader who asked for
  reduced motion, but not one inside `<picture>`, so the loop's picture shows that reader its end frame.

| Content | Form |
|---|---|
| One moment, a single pane, under about 6 s | A loop (`--single`) |
| Behaviour, `main` against the PR | One side-by-side loop, as the opening visual. One file keeps both sides on one clock; two GIFs drift apart |
| A whole task | Its result in view: the headline sentence, a chart, the run's end frame (`--make still`), or a loop of the moment that decides it. The full MP4 goes under it, collapsed; in view only where the user picks it (below) |

GIF only. WebP uploads and animates, but GitHub doesn't document it, and it saves little at loop length.
APNG ran 13 MB for 7 s at 780 px.

**Cut** the tightest span that still shows the behaviour, and end on the proof. #15185's 4.7 s cut stopped
before the point that the lost typing never comes back; the 9 s loop ends on it. Then:

    ../charts/loop.py CLIP --from S --to E --out DIR/NAME      # NAME.gif, NAME-narrow.gif, NAME-still.png, NAME-narrow-still.png
    ../charts/loop.py RUN --make still,mp4 --out DIR/RUN       # a whole task: its end frame in both layouts, and RUN.mp4 re-encoded small

- **Hold:** the last frame is held 1.5 s, so the result can be read.
- **Phone layout:** stacks `main` over the PR.
- **Ring:** a progress ring fills over the loop, so a reader can tell how far in they are and what they
  have already seen; it stays on. It sits in the caption bar's corner. Where a
  caption runs into that corner (3 of the 10 series-1 clips), `--ring-above 80` lifts it over the
  80 px caption bar.
- **Look and cold read:** look at the frames and at the end still, and cold-read the first frame and the
  end frame against the takeaway (*Takeaway and cold read*).
- **Size:** #15185's 9 s loop is 713 KB wide and 876 KB narrow; GitHub's cap is 10 MB.
- **Placing it:** in `place()`, `h.loop("DIR/NAME", alt)` or `h.still("DIR/RUN", alt)` goes where the clip or
  the table it replaces was (paths relative to the chart folder). The alt text states the takeaway, as for a
  chart. The draft's page check then covers it at every width, and again with reduced motion, which must
  show the end frame; it skips the 11 px text check, since footage text isn't drawn to our sizes. `--upload`
  uploads it with the charts (`pr-images --loop` / `--still`).

**The full run**, when a body keeps it: in `place()`, `h.video("DIR/RUN.mp4")` returns its placeholder URL, which
goes on a line of its own, with blank lines around it, inside `<details><summary>Full run (56 s video)</summary>`.
There GitHub renders it as its player, the draft's page check measures it, and `--upload` uploads it. It is
for a desktop reviewer who wants to scrub. Chrome still downloads it with the page, so keep it small:
`--make mp4` re-encodes it (H.264 CRF 28, at most 1920 px wide, no audio), which took #15185's 9 s clip from
231 KB to 138 KB.

**A video in view** only where the user picks it (e.g. to open a showcase post). The same
`h.video` line, outside `<details>`. What the reader gets, and what to make of it:

- **Paused first frame:** most readers see only this, with the controls drawn over its bottom. Make the first
  frame carry the result, with its captions at the top.
- **File name:** the player's header shows the uploaded file's name, so name the file for the reader
  (`series-1-reminders-task.mp4`, not `headline-reminders-add.mp4`).
- **Phone:** a wide clip is letterboxed into the player's 200 px minimum height. At a 390 px window a
  1920×816 clip plays at 322×137 px, which the page check reports as the footage size. On an iPhone, a tap
  opens it fullscreen.

## Uploading

`images.upload` in the config ([config.md](config.md)) picks how a file gets its URL; the printed
`<picture>`, with its theme and phone sources, is the same either way.

- **`relay`, the ideal:** real GitHub attachments, uploaded from a background tab of the PR's repo in
  your Chrome, signed in to GitHub, through omp's browser relay. They are what dragging a file into a
  comment box makes (`github.com/user-attachments/assets/…`): hosted by GitHub apart from any branch, so
  they outlive your fork and its branches, the form maintainers and bots expect, and an MP4 renders as
  GitHub's player. It needs the relay extension connected (`omp browser-relay install`) and that Chrome
  signed in to github.com; `pr-images` checks both and says which is missing. Nothing is typed or
  submitted. On macOS, Chrome's AppleScript closes the tab if the relay drops mid-run (optional).
- **`fork-links`:** for a machine without that Chrome. `pr-images` commits the files in one commit to the
  branch `omp-contrib-assets` of your fork (`github.fork_repo`), under `pr-<N>/<hash>-<name>` (the chart
  folder's name before the PR has a number), through `gh api`, and prints
  `raw.githubusercontent.com/<fork>/omp-contrib-assets/…` URLs, after each answers 200. GitHub's PR page
  renders them in the themed `<picture>` like attachments. The costs: they show only while that branch
  and your fork exist and stay public, and a video's URL renders as a link, not a player. The content
  hash in the path means a URL never changes what it shows.

## Placing it

`place(body, data, h)` returns the whole body: the table or text the image replaces becomes `h.picture(id)`
followed by `h.details("Exact numbers (n …)", h.table(body, first))`, the original table verbatim, plus
whatever was moved off the chart. When the image shows only some of a table's rows (#15608's literal
reads beside its refusals), the rows it shows move into `<details>` verbatim under the original header
and the rest stay a visible table. Everything else stays byte for byte, with three exceptions made
through `h.replace` and reported to the user: corrections the run files or the code force, a lead-in sentence
that would now misdescribe what follows it (it named a column the chart leaves to `<details>`), changed
as little as it takes, and the headline sentence's number as before → after (framing.md, rule
1). The alt text states the takeaway with its headline numbers in one or two sentences: bots and screen
readers get the point from it, and the exact numbers from `<details>`.

## Takeaway and cold read

Each chart carries `takeaway`: the one sentence the chart must convey, naming what is compared, the
direction, the headline numbers, and a secondary point only if the chart shows it on purpose (Opus "no
clear change" beside Sol's gain). Write it before drawing; it is what the cold read grades against.

`cold-read.py` gives a small vision model (`models.cold_read`, default omp's `@smol` role; it must take
images) only the light PNG, no context, and grades its takeaway against yours by majority of three. A miss, a misread number or unit, or the same partial twice means the chart says
something else to a stranger: read the answers in `out/cold-read.json` to see what, fix the title or labels,
and rerun. Listed unclear labels are candidates for rule 2. Matches on both reads are enough; a small
model's partials on a deliberately secondary point are not a reason to add it to the title. The cold read doesn't
test whether a reader over-reads the evidence ("significant gains" from two runs); the reviewer's
over-claim criterion covers the chart's own wording.
