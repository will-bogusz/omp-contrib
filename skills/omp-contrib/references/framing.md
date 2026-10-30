# Framing a PR body for a maintainer outside the area

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

## Frame the body for the reader

The reader knows OMP as a harness (roles, tools, providers, `/usage`, the model picker,
sessions) and does not know the mechanics of the area being changed. Everything below exists so
that reader can judge the change without learning the area first. This is a direction, not a
template: derive each body from these questions, never by copying an earlier PR's shape.

1. **Open with what an OMP user saw, in OMP terms.** Stakes come before any area jargon. "A
   subscriber saw one stale SWE-1.6 entry" beats a description of the discovery endpoint
   (#8590). When What has a measured headline, the sentence right after the own-words
   line (the headline sentence) carries it as before → after ("68–94 ms → 34–56 ms, about 35 ms
   faster"), never as a bare saving ("cuts about 35 ms"): one such line lifted cold skim reads of
   #15291's effect from 6 to 13 of 15. A capability with no measurement in What keeps its sentence;
   Testing's counts stay there.
2. **Frame capabilities within OMP as a harness, not as internal logs.** Say what a user can now
   do or see (usage shown where it was missing, a model that now completes a turn), not which
   call sends which token. Mechanism goes to *Review first* or `<details>`: a first draft of
   #8590 that listed which call sends which token read as internal logs to its own author.
3. **Give a short primer, only when the area has vocabulary the reader lacks.** Define only the
   terms needed to judge this diff, each once, mapped onto an OMP concept the reader already has
   (a blockquote headed "**<Area> context.**"). Example: Devin's Fusion is "a strong model
   delegating to a cheap one, which is what OMP's roles already do" (#13527).
4. **Use a before -> now table when several user-visible capabilities change.** Rows are OMP
   surfaces (`/usage`, `/models`, the picker), cells are what the user sees. Keep it even when no
   number is involved: a rewrite of #8577 that dropped it read worse. This extends
   `rule://omp-pr-authoring`, which reserves tables for measurable claims.
5. **Show decisions as decisions.** For each real choice, one sentence naming the alternative
   rejected and why. A change to what users or resources see beyond the
   title's promise usually belongs in its own PR (*Write the code*). When one stays, it gets its
   own bold line right under the What table (`**Beyond the <fix>:** … on main it …`), stating
   `main`'s behaviour and how small it is to drop, never a bullet inside Decisions: #14420's
   was the second Decisions bullet and the one part the maintainer reverted (`825806e402`). The
   maintainers' own bodies lead with "Behavior changes:" the same way (#14454, #14331).
   The body carries no merge-order text (`Builds on #A`, `merge #A first`, `Overlaps #N`): a PR
   that needs another is not open until that one merges (`shaping.md`, *Open-PR rule*). Related
   work by someone else is a `Related: #N` mention under Why.
6. **Name the maintenance cost.** What breaks when the external thing changes (provider backend,
   CLI version, OS API), how anyone would notice, and what the one-line fix is.
7. **Name non-goals up front**, so nobody wonders what is missing (#8590, #11740).
8. **Give a reading order for diffs past a few files:** concept -> file -> symbol, in review order,
   never line numbers.
9. **Testing is the scenario you ran and its result,** then the command that re-proves it.
   CONTRIBUTING requires exercising the changed path yourself: reproduce the bug and show the
   same reproduction passing, use the feature end to end, or inspect the rendered UI. "`bun check`
   passes" alone is not verification. Include a negative control: with the fix reverted, the test
   fails (#13527 Testing; #11386 gives RED/GREEN counts). Every claim in the body ("unchanged",
   "stays conservative") is something we checked; a case we noticed that matters gets tested or
   fixed, not listed. Only a path we cannot run here gets a `Not run:` line saying what and why
   (another OS, a backend or account we lack), as #14485 ("Windows was not run") and the
   maintainer's own #14519 do.
10. **Keep private context out.** Account deals, partner authorization, decompile or
    reverse-engineering provenance, "mirrors X exactly" wording, fork credits the user declined,
    and private motivation. Re-check these exclusions after every context compaction: excluded
    context has come back after one and been posted (#8577's partner authorization).

**Template and length.** Use OMP's headings in order: `## What`, `## Why`, `## Testing`, then the
checklist. The four questions of `rule://omp-pr-authoring` fill them. What holds the claim and the
shape, Why holds the problem, decisions and maintenance cost, and Testing holds the evidence. The
risk and review-first line close Testing or Why. Stay under 3,000 characters excluding tables,
`<details>`, images and the checklist, and measure it (`scripts/precheck`; #13527 went from 3,469
to 2,792). Merged bodies have a median of about 2,000 characters.

**Visuals.** Each idea in a body takes the one form that shows it best to a human reviewer. While
writing each idea, ask whether a figure would show it better than the text or table you are about
to write, and if so make it in this draft, not in a later pass. Don't force an image every time,
but whenever one would be more useful than the text it replaces, make it. An idea left as
text needs no stated reason. An idea is what the reader must
grasp, not the block that holds it: #16202's What table lists where a stop can land in a call (between
keys, during the wait after the last key, during a read), which is one call's timeline, `main`'s lane
against the PR's. The exact numbers and details stay as collapsed text for bots and agents. What
follows the own-words line is the densest, easiest read in the body. Every visual is true to the code
and the runs, readable cold, readable on a phone, and the only form its idea takes.

The rows are in order: take the first that fits the idea.

| The idea | Its form |
|---|---|
| A lookup (ids, exact limits, error strings, config values), or measurements of about six numbers or fewer (#15607's 0/20 → 20/20) | A **table**, with the rig and command behind its numbers (#13063, #11740); its headline goes in the headline sentence (rule 1) |
| A measured `main`-vs-PR comparison across several conditions or magnitudes, as What's table | An **opening image** in that table's place ([charts.md](charts.md), *Opening image*); a row that isn't a measurement or doesn't change (a fallback's cost, "unchanged", 20/20 on both) becomes one bold line under it (`**Cost:** …`) |
| A shape in measurements: a trend over steps or a limit, a spread or interval against a reference, one effect across conditions whose cells all differ, every run when n is small | A **chart** in the table's place, wherever the table is |
| A mechanism: where turns, calls or steps go | A **turn strip** of real recorded runs, one box per turn |
| A decision with branches the PR changes: three or more rows or sentences that are branches of one decision (`main`'s column repeats "same") | A **decision flow** |
| An order of events whose timing the PR changes: a window or timeout it moves or adds, a wait, what happens at one point of a sequence, `main` against the PR | A **timeline**, `main`'s lane and the PR's on one clock |
| One check that sends work down routes with different costs | A **routing diagram**, the cost on each route |
| A change to literal text the model or user reads | That **text before and after**, the change marked; rows of the same table that aren't text (a refusal, an error) stay a visible table under it |
| A UI, TUI or rendered display | **Screenshots**, before and after (below) |
| Behaviour on screen: one moment, `main` against the PR, or a whole task | A **GIF loop**, side by side for `main` against the PR; a whole task's full recording as an MP4 collapsed under its result, in view only where the user picks it ([charts.md](charts.md), *Motion*) |

- A figure carries what the PR changes that text leaves the reader to rebuild: a shape, a mechanism,
  an order of events, branches. Text wins where the idea reads at once: a single number, exact
  values a table already lists, an all-or-nothing result (#15607's 0/20 → 20/20), the same at every
  run or sample even when it was sampled over time ("none on `main` at any sample, held for the
  whole turn with the PR"), a check with two outcomes, a changed phrase short enough to quote whole
  in the sentence (a longer change to text the model reads is the literal-text row), and whatever the PR leaves
  as it was: how a bug comes about, a race the fix removes without changing any timing, and code a
  test-only PR describes (`main` and the PR behave the same, so there is no change to draw). On
  #15604 a good sentence read as well as drawn lanes (8 against 6 of 15 Haiku reads): a figure that
  only restates a clear sentence adds nothing.
- A figure replaces what it shows (the table or paragraph moves, verbatim, into `<details>` under
  it) rather than adding to it. One that adds (#15402's turn strip) must show what nothing else in
  the body shows.
- A merged or closed PR's visuals change only when the user asks; new visuals belong to bodies
  being drafted or rewritten.
- No number is drawn twice. The headline sentence and Testing's prose may state a number an image
  shows; two images never show the same numbers, nor an image's footer another image's. A chart that
  is evidence for Why or Testing stays there and never moves up to open the body. Where an opening
  image and a Testing chart would draw the same numbers at the same grain, the opening image keeps
  them and the Testing chart drops them ([charts.md](charts.md), *Opening image*).
- Diagrams are drawn by us, never GitHub Mermaid: on a phone GitHub scales the whole diagram into
  the column (labels about 5 px; 0 of 4 phone cold reads matched, against 10 of 12 for our drawn
  phone layouts), and its pan and zoom buttons stay drawn over the outcome node, desktop too.
- How to draw, check and publish each form: [charts.md](charts.md).
- New provider or large feature: full-width terminal screenshots of the major surfaces (model
  browser filtered to the provider, one live interactive turn with a tool call, redacted usage)
  right after the What table (#8590, #8577). UI, TUI or a rendered display changed: before and
  after screenshots side by side in a table (#8337, #9995, #6652).
- Images are GitHub attachments (`user-attachments` URLs) when `images.upload` is `relay`, the
  ideal set up by `/contribute` (the image-upload decision in [setup.md](setup.md)); with
  `fork-links` they are raw links to files committed on your fork's `omp-contrib-assets` branch,
  which break if that branch or fork goes and show video as a link, not a player. Why the relay is
  the ideal and what each mode costs: [charts.md](charts.md), *Uploading*. `gh` ≥ 2.99 has
  `--attach` on `issue`/`pr` `create`/`edit`/`comment`, but it requires write access to the
  repository, so it fails on the upstream repo ("attaching files requires write access").
  Screenshots are never committed to the upstream repo. Prepare PNGs in the task scratch dir, mark
  where each goes, and upload them with `../scripts/pr-images` (below). **Every body rewrite keeps
  the existing images.**
- **Composition that worked (#11613).** Every image is one before -> after pair of
  the same OMP surface, captured from `main` and from the branch in the same window, size and
  demo project, with a caption bar above each half that states the claim and its number
  (`main: 130 rows, one per effort tier` / `this PR: 79 account lanes, effort as a ladder`).
  One image per What-table row that a picture can prove, placed together right after the table.
  Full-window surfaces (model browser, `omp models`) go side by side; a single row or panel
  (one model's price, the usage meters) is cropped tight and stacked, with its detail footer
  cropped from the bottom of the window and appended under it. A live turn is one full-window
  shot, cropped to the transcript. Build them with `../scripts/compose-shots` (`side` or `stack`
  with crop geometries); it reproduces the #11613 images pixel for pixel.
- Capture setup: run `main` as `omp` and the branch from its worktree (omp runs from source:
  `bun <worktree>/packages/coding-agent/src/cli.ts`, after the worktree's own `bun install`),
  from a scratch demo git repo with a few tiny files, so tool turns have something to read. Both
  runs use the same window size, font and theme, so the pair lines up. On macOS with Tern
  installed, render offscreen rather than in a window: it opens nothing, leaves your screen and
  terminals alone, and running the same steps for `main` and the branch gives a before/after pair
  with identical size, font and framing. Shots are 2x PNGs plus a layout JSON. `tern help dev`
  lists every command.
  - CLI output (`omp usage`, `omp models`): a scenario file, one command per line (`ready`,
    `run "cd <demo dir> && omp usage …"`, `expect "<text on screen>"`, `shot <name>`), then
    `tern shot <scenario> --out <scratch>/shots --size 1500x900 --theme dark`.
  - The interactive omp app: Tern draws it as native UI, so `expect` can't see its text and a
    scenario's `wait` doesn't pause in real time. Run `tern serve --control <sock> --out <dir>` as
    a background service, then send one step at a time with real sleeps between:
    `tern ctl --control <sock> 'run "cd <demo dir> && omp"'`, `'type "/usage"'`, `key Enter`,
    `shot <name>`, and `quit` at the end. Quote each command as one argument. `serve` renders the
    light appearance unless told otherwise.
  Use `omp usage --provider <id> --redact` after `omp usage invalidate --provider <id>` (the report is
  cached), never the `/usage` overview or details (they show emails, org ids and total spend).
  Check each composite with `read` before uploading.
- Upload: `../scripts/pr-images upload FILE...` prints the Markdown to paste, about 4 s for two
  charts. `--themed` turns `NAME-dark`/`NAME-light` pairs into one `<picture>` that follows the
  viewer's theme (GitHub renders it as `<themed-picture>`, signed in or not), with
  `NAME-narrow-dark`/`-light` as its phone layout (shown below a 1244 px window, up to 440 px wide); `--scale 2` halves the width of 2x renders; the tag
  never carries a height, since GitHub shrinks images to the column without `height: auto` and a
  height stretched #15434's chart to 2.3 times its height on a phone; `--alt` sets alt text;
  `--uploaded FILE=URL` reuses an upload; `--mode relay|fork-links` overrides `images.upload` and
  `--folder NAME` groups fork-links files. With the relay it opens a tab of the repo
  through the omp browser relay, makes the three requests a drag-and-drop makes, and closes the tab
  (through Chrome's AppleScript on macOS if the relay can't): no composer, nothing to clear,
  nothing submitted. If the tab still can't be closed it prints the Markdown anyway and exits 1
  naming the tab's `#omp-pr-images-…` marker. The tab stays in the background only with the relay
  extension of omp 18.8.8 or later; an older one opens it in front of you (`omp browser-relay
  install`, then reload the extension). Then put the Markdown in the body with
  `../scripts/pr-body N FILE`: `--dry-run` first shows
  the diff; the script refuses a queued PR and reads the body back against FILE. Check how a body renders
  without posting it with
  `gh api markdown -f mode=gfm -f context=<github.upstream_repo> -F text=@body.md`.
  An uploaded asset loads only for signed-in viewers (anonymous: 404) until a posted body
  references it; then anyone can load it, `<picture>` sources included (#11613's images, uploaded
  in a composer that was cleared and placed by `gh pr create --body-file`).
  If the tool breaks after a GitHub change, the composer route still works through the relay:
  PR pages keep the classic composer (`uploadFile("#fc-new_comment_field", png)`, read
  `#new_comment_field`), issue pages the React one ("Add Files" paired with
  `page.waitForFileChooser()` and `chooser.accept([png])`); clear the textarea with the native
  value setter plus an `input` event. Uploading a local path needs the relay extension's "Allow
  access to file URLs" turned on in Chrome until #15489 ships.
- Re-derive the body from the questions when it changes materially; never patch sentences into
  a stale body (#8577, below).

## The own-words sentence

CONTRIBUTING.md § *Pull request requirements*: every PR body "**MUST include at least one sentence
written by you, in your own words**, explaining what changed and why. A generated summary, pasted
agent transcript, or checklist alone does not satisfy this requirement." Upstream `AGENTS.md`
§ *Pull requests*: an agent "MUST obtain at least one sentence written by the contributor in their
own words explaining what changed and why, as required by `CONTRIBUTING.md`. If it is missing, ask
the contributor; NEVER generate a substitute. Preserve that sentence during edits."

So the agent never writes this line. For every PR, ask the user for it (through `ask`, with the
What table and headline sentence already drafted so they can react to the change, not reconstruct
it), and put their words first under `## What`, unedited apart from a typo they approve.

- A body without the user's sentence does not open: the queue entry waits for it. Never ship a
  placeholder or a drafted stand-in (#8577's final body had none).
- Don't propose wording for them to accept; a sentence the agent wrote and the user approved is
  still generated. Asking what they would tell a maintainer about the change is fine.
- Preserve the sentence through every body edit and rewrite.
- No claims in the rest of the body about what the user personally ran beyond what the Testing
  section shows.

The reasoning below comes from how #8590 and #13527 were written and received.

## The reader

A maintainer who knows OMP as a harness: roles, the task system, providers, `/usage`, `/models`,
the model picker, sessions, the KDL policy tree. They do not know the vocabulary or wire behavior
of the area being changed (a provider's backend, a macOS accessibility API, a TUI renderer
detail). A second reader is an agent doing archaeology months later with only the body and diff
(`rule://omp-pr-authoring`).

## What worked in #8590 (keep)

1. It opens with the user's problem in OMP terms: a subscriber saw one stale entry. The stakes
   arrive before any area jargon.
2. A before -> now table by capability, where every row is something a user sees.
3. Non-goals named up front.
4. Verification states results with numbers, not a test plan.
5. The risk part says what to review first.

## What it lacked (fix)

1. **Area terms never explained.** Add a primer with only the concepts needed to judge this
   diff, each defined once, in OMP terms.
2. **No guide to the diff.** Add a short reading order that maps concepts to files and symbols,
   never line numbers.
3. **Decisions not shown as decisions.** A maintainer's real question is "why this approach?".
   State each rejected alternative in one sentence.
4. **No answer to "what breaks when the upstream changes, and how would we notice?"** That is the
   maintenance cost the maintainer takes on; do not bury it.
5. **Too long.** One claim per sentence, under 3,000 characters.
6. **Evidence you cannot re-run.** Give the command for each number.
7. **Not on the repo template.** Use What / Why / Testing plus the checklist, with the own-words
   sentence.

## The earlier steer: capabilities, not logs

An early draft of #8590's feature description read like internal logs: a `Surface | Behavior`
table of mechanism rows (a router calls one endpoint, then sends a token to another). The fix
framed capabilities within OMP as a harness: a `Capability | Before -> now` table of user-visible
deltas (`/usage` showed nothing, now shows plan tier, credit balance and quota windows). The
mechanism moved to *Review first*. #8590 merged with that shape.

## Where this sharpens `rule://omp-pr-authoring`

- **Capability tables stay even without numbers.** A rewrite of #8577 that followed the
  authoring rule and dropped the feature table was harder to digest; the table came back. Rows
  are grouped by capability, not by commit or file.
- **Map the new thing onto an existing OMP concept.** #13527 explains Devin's Fusion as "a
  strong model delegating to a cheap one", which is what OMP's roles already do with a frontier
  default and a cheap model on the `task` role. The reader judges the removal without learning
  Fusion.
- **Private context is not the user's problem.** Leave out upgraded-vs-free account musings,
  partner authorization, decompile provenance, and "mirroring X exactly" wording. Re-check after
  compaction, because excluded context has come back after one.

## Worked example: #13527

https://github.com/can1357/oh-my-pi/pull/13527 (2,792 characters after cutting from 3,469).

- `## What`: the own-words sentence first ("Fusion was cluttering the Devin model picker with 335
  pairings that all just ran the lead model in omp, ..."). Next, one sentence with the
  user-visible number (the list drops from 401 rows to 66). Then a "**Devin context.**" blockquote
  defining the two entry kinds the diff depends on, and a four-bullet reading order anchored on
  symbols (`isExcludedModel`, `devinModelCost`).
- `## Why`: why the rows were duplicates. What Fusion does, mapped to OMP roles. Rejected
  alternatives in one sentence. Why the client version matters, with the maintenance cost: a
  hand-maintained constant, a warning when it goes stale, a one-line fix.
- `## Testing`: a regression test with a negative control (remove the KDL rule and the test
  fails, listing all three), suite counts, a replay of a captured live list, and a live-account
  run.

What happened next is also a lesson. roboomp ranked the PR P2 because it bundled a default-model
change. Can took only the version bump into his own commit `30f532944f`. The framing was fine;
the scope was not.

## Worked example of the opposite: #8577 before its rewrite

The Factory Droid body grew by string patches as features changed. It ended up describing
removed features and needed a full re-derivation. It still carried a partner authorization that
had been meant to come out, and it had no own-words sentence. Re-derive from the questions; never
patch.
