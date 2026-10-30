# The queue: what opens when

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`. The rule
this keeps is `shaping.md`, *Open-PR rule*; `../scripts/pr-queue` keeps it, and its `--help` lists
every option. Config keys in `backticks` are defined in [config.md](config.md).

## The manifest

`queue.json` on your fork's queue branch (`github.queue_branch`, default `omp-queue`, reached
through the `github.fork_remote` remote), with stored bodies under `bodies/<id>.md`. Every machine
with that remote reads and writes the same queue, and every change is a commit there
(`git log <fork_remote>/<queue_branch>` is its history). Change it only through `pr-queue`, which
re-applies a write that raced another machine. `--manifest FILE` uses a local file instead, for dry
runs. The branch starts empty the first time `pr-queue` writes to it.

One entry per change of ours that is queued or open; merged and closed ones stay as history.

Every write also renders `QUEUE.md` beside `queue.json`, in the same commit: the page to read the
queue at a glance (`https://github.com/<your fork>/blob/<queue_branch>/QUEUE.md`).
It opens with the opening pause, the hour's ready budget and counts per group, then one table per
group: openable now (with plan's label, `open (over P2 #N)` included), conflict-held (each blocker
a PR link, `main` for a conflict with main), stacked (each unmet need, a link when it is a PR),
held (the reason, a P2 decision waiting for the user included), and open PRs (link, rank, age since
opened, plan's action); an entry queued since the last plan gets a table of its own. Each row has
id, title, area, priority, age since `added`, a compare link of its branch against `main`, and
`owner` when an entry records one. The groups come from the manifest's `plan`, cached by
`pr-queue plan` and the watcher when its rows changed or are an hour old: plan builds merge trees
and asks GitHub for the ready events, too slow for every write, so the page stamps that plan's
time and host, while states come from the manifest as written. The branch is public: the page
carries no stored body and no host path.

| Field | Holds |
|---|---|
| `id` | the branch topic; commands also take the branch or `#N` |
| `branch`, `worktree`, `host` | `<github.branch_prefix><topic>` on the fork; its worktree and host when recorded |
| `title`, `body` | the PR title (Conventional Commit) and the stored body `open` posts |
| `area`, `priority` | `area` labels the change for grouping output (browser, computer, …), never a limit; `priority` orders the plan: roboomp's rank once it has one, our P0-P3 estimate before |
| `needs` | entry ids or `#N` that must merge first |
| `base` | the commit its own commits sit on (its need's tip when it was branched); `advance` replays from there |
| `state`, `pr`, `closed_prs` | `queued`, `open`, `merged` or `closed`; its PR, and PRs `requeue` closed |
| `hold` | why a queued entry must not open yet, as `WHO, DATE: REASON` (`set --hold`); absent when free |
| `p2_decision`, `p2_approved` | for a change that is P2 by design: its one maintainer decision (`add`/`set --p2-decision`), and when the user approved opening it (`approve`; a new decision clears it); see *P2 decisions* |
| `rebases_after` | on an open P2's entry: PRs `open` opened over it (shaping.md, *Open-PR rule* 3), so it rebases onto `main` once one merges; their conflict counts for neither. `requeue` drops it |
| `built` | `pr-queue built` records: the merged tree with `with` was built and tested, at both sides' code (`code`, `with_code`: patch id of the diff past `main` outside CHANGELOGs) |
| `rust_checks` | `rust-check` records per Rust diff id: platform → sha, time, host (`ci` with the run URL) |
| top-level `config` | `ready_budget` (default: roboomp's hourly cap for the fork owner's tier minus 2: 8 for a contributor, 1 for a first-time author, none for a maintainer; a value set here wins), `draft_days` (3), `active_days` (3), `over_p2_days` (3: how long a P2 is open before a P0/P1 opens over it), `areas` (path rules for entries without one; empty by default, set your own), `pause` (the opening pause, below) |
| top-level `opening` | the lock of an `open` in progress: one at a time across machines, released at the end, void after 20 min. A refusal naming it means wait, not delete it |
| top-level `watch` | the watcher's record (below): written by `pr-queue watch` alone |
| top-level `plan` | the last plan's rows, budget, time and host, for QUEUE.md (`plan` and `watch` write it) |

## When to run what

- **A branch is final** (workflow step 3 done, body written): `pr-queue add
  <github.branch_prefix><topic> --title '<type(scope): …>' --body <file> [--needs <id|#N> …]
  [--priority Pn] [--p2-decision "<decision>"]`. Every final branch goes in, whether or not it can open
  today. Work that builds on unmerged work is branched from that work's branch and names it in
  `--needs`; `add` records the branch point as `base`.
- **Starting PR work, and after each merge round** (`pr-trace --summary` lists the merges):
  `pr-queue sync`, `pr-queue advance`, `pr-queue plan`.
  Queue git calls disable rerere: CHANGELOGs are rebuilt from our commits, not old conflict
  resolutions. `advance` reports a failed entry and continues independent entries; completed bases
  are saved even when a later step fails. An entry already on its base still pushes a newer local
  tip (unless `--no-push`).
- **Holding an entry** (the user's OK pending, a dependency outside the queue): `pr-queue set <id>
  --hold "<who>, <date>: <reason>"`, lifted with `--unhold`. `plan` shows it `held`, never `open`,
  and `open` refuses it; `advance` still rebases it. A hold written only in `--note` is invisible to
  both, and the round's opener opens whatever `plan` marks `open`.
- **Pausing all opening** (the user's call, e.g. until a maintainer catches up): `pr-queue pause
  "<who>, <date>: <reason>"`, lifted with `pr-queue unpause`. While it is set `open` refuses before
  taking the lock, `plan` prints the pause on its first line and shows `paused` where it would show
  `open` or `next-hour`, `pr-trace --summary` prints it first, and `precheck N` prints a FIX for a
  draft or closed PR: none turns ready or reopens. Open PRs carry on: bot fixes, rebases and drift
  pushes continue. The pause lives in the manifest, so every session and machine sees it; a pause
  relayed only in one session's notes reaches no other (two PRs once opened during one).
- **Opening**: `pr-queue open <id>` for each entry `plan` marks `open`, in plan order (workflow
  step 5), after the supervised-start OK while one is due (*Supervised start*). One agent, the
  opener, opens every entry of a round: workers stop after `pr-queue add` and take their PR back at
  its bot rounds once the opener names the number. A push to an open PR voids the `built` records
  of every waiting entry in its package, so owners batch bot-round pushes and send the opener each
  new head; it rebuilds once per batch (20 openings once took ~20 tree rebuilds). `open` holds one
  lock across machines, and a tree built per entry misses the entries opened after it: ~15 workers
  each retrying the lock and rebuilding their own tree as others opened once got 3 PRs out in 30
  min, then none for 70. `open` refuses while plan would not open the entry, and while a merged
  tree under it is not recorded as built:
  1. Under each `open` row `plan` prints `build and test the merged tree with #N (crates/x), …,
     then pr-queue built <id> #N …`: each open ready PR, and each other entry `plan` opens, that
     changes a crate (`crates/<name>`) or package (`packages/<name>`) this one changes. Git merges
     such a pair cleanly and each passes alone, yet the pair can fail to compile: #15761 changed
     `worker_with`'s return type and #15762 moved that value (E0507). `precheck` prints the same
     per unit as `NOTE build` for a PR. With many open PRs in `packages/coding-agent`, expect a
     long list: it is still one merge and one build.
  2. Build one tree for the round: `pr-queue tree` lists every unbuilt pair under `open` and
     `next-hour` rows and prints `git worktree add --detach DIR <main>` and one `git merge
     --no-edit <tip> …` by SHA. Run the touched units' build and tests there: `bun run check:ts` at
     the root and the focused `bun test` files of each package, `cargo build` and `cargo test` of
     each crate, wherever `build.*` puts that platform (*Where builds run* below). A
     failure is the pair's bug: fix the branch it belongs to (both if need be); never open past
     it. An entry queued or changed later extends the same tree:
     `pr-queue tree <SHA>` prints the tips it lacks. Name the tree by SHA, never a shared
     worktree's `HEAD`: one was once checked out to a pair build mid-round and others merged onto
     the wrong commit.
  3. `pr-queue tree <SHA> --record` records every pair the tree holds (it refuses while one's
     current tip is missing); a pair sharing a crate only with `--rust`, once cargo passed in that
     tree. `pr-queue built <id> '#N' …` (the plan line's tail) records each pair it can: a WITH
     that merged or closed since the plan, or names nothing, prints `not recorded: <id> with #N:
     merged` (`closed`, `unknown`) and is skipped, the others saved; it exits 1 only when none
     was.
     A record holds both sides' code, so a rebase and the CHANGELOG link commit keep it, and a code
     change on either side voids it. Then `pr-queue open <id>`, each in plan order.

  `open` checks the open ready PRs alone: the same-plan opening listed beside it is one when its
  own turn comes, and one `built` record of the pair covers both opens.
  An open PR that itself conflicts with `main` in code is left out of the build (`not with #N: …`):
  no tree holds it until its own rebase, which is then built with everything open.
- **An open PR `plan` marks `rebase`** (its one break is a conflict with `main`): `pr-queue advance
  #N` rebases its own commits onto `origin/main` and pushes; the PR stays open. A conflict stops as
  below.
- **An open PR `plan` marks `requeue`**: `pr-queue requeue N` stores its entry and body first (the
  write confirmed; a body it cannot read refuses), then closes the PR without a comment, then marks
  the entry queued. A failure before the close leaves the PR open with nothing changed upstream;
  a failed close leaves the entry stored and open (rerun it); a failed last write is finished by
  the next `sync`. The queued entry reopens as a new PR once its needs merge (*Cadence*: re-rank
  through a new PR), after its stored body loses its merge-order lines (`show`, `set --body`).
  Requeuing closes a public PR: the first time `plan` marks a backlog of open PRs (ones opened
  before you started using the queue) for requeue, report the list to the user, grouped by area,
  rather than closing it unasked. From then on, requeue what `plan` marks.
- **Editing a queued change's body**: a closed PR an entry queues reopens with the stored body, so edit
  that (`show`, `set --body`), never GitHub's; `precheck N` prints it as `FIX queue`, and `charts/run.mjs`
  refuses that PR's live body (`pr-queue body-home N`).

## P2 decisions

A change that is **P2 by design** (it changes a default, adds a setting, or reverses a deliberate
contract: shaping.md) carries one decision only a maintainer can make. Name it when queuing:
`pr-queue add … --p2-decision "<the decision, one line>"` (or `set <id> --p2-decision …`, which
replaces it and needs a new approval; `--no-p2-decision` drops it). What
happens next is `autonomy.open_p2`:

- `"hold"` (the default): `plan` shows the entry `held` with the reason `user decision pending:
  <decision>`, lists it under `Awaiting your decision` at its head, and `open` refuses it
  until the user approves opening it. Put the decision to the user in one line with the
  recommendation and what the other choice costs; on their go-ahead, `pr-queue approve <id>`
  records it (`p2_approved`), and the entry opens like any other at its turn. A declined decision
  stays held; reshape the change (split the default change out: shaping.md) or close the entry.
- `"open"`: the entry opens at its turn like any other; the decision rides on the PR (its body
  names it, our answer to roboomp's question argues it).

The `/contribute` status card lists held P2 decisions. A fix or a change we estimate P0/P1 never
waits for this: there is no rank threshold, since roboomp ranks only after opening.

## Supervised start

roboomp reviews each PR number once, ever, so a mistake in an early PR is permanent. While
`autonomy.supervised_opens` is above zero, the opener stops before each `pr-queue open` and shows
the user, in one message: the stored body (`pr-queue show <id>`), a diff summary (files, lines,
what changes for a user) and the own-words sentence. `plan`'s head says how many remain
(`Supervised start: the next N open(s) need your explicit OK`), and `open` refuses without
`--user-approved`, which the opener passes only after the user's explicit OK in the
conversation; each supervised open counts `supervised_opens` down by one in the config file.
At zero, opening is autonomous. Anything posted to a human still needs the user's approval
of its exact text, supervised or not.

## Where builds run

Builds and tests run on this machine first. Each platform's Rust check runs where its
`build.<platform>` placement says:

| Placement | What runs where |
|---|---|
| `local` | here: `../scripts/rust-check` in the PR's worktree (Windows through cargo-xwin, `--windows`) |
| `ssh:<host>` | in a worktree of the PR's branch on that host (recipe below) |
| `ci` | `../scripts/rust-check --ci` pushes a temporary branch to your fork and runs the checks on its GitHub Actions; needs Actions enabled on the fork and a gh login with the `workflow` scope |
| `none` | unchecked: precheck prints a NOTE instead of the `rust` FIX (as it does for an `ssh:` host it cannot reach), and the PR's Testing section says which platform went unchecked |

`rust-check` runs clippy `--all-targets` and rustfmt and records the pass in the queue manifest's
`rust_checks`; precheck and `open` refuse a Rust diff without a record (or a `none` placement) for
each platform it builds on. Run it with its own `CARGO_TARGET_DIR` in the task's scratch and
delete that dir when done.

Many agents building at once exhaust memory: about 25 agents running `bun test` and `check:ts` at
once once took a laptop from 5 GB free to swap in 20 minutes and then took down a 31 GB build
host. Check free memory before a fan-out, and spread a round's builds over the hosts you have.
Per worktree, wherever it builds:

- `bun install --frozen-lockfile --ignore-scripts`, then `bun run prepare` (the root `prepare` the
  install skipped; it builds the export viewer into the ignored
  `packages/coding-agent/export-assets/`, which coding-agent's HTML export tests read). Never
  symlink the main checkout's `node_modules` (workflow step 2): `@oh-my-pi/*`, natives included,
  then resolves to whatever that checkout has checked out.
- Natives: a tree that changes no crate copies (`cp -c` on macOS, `cp --reflink=auto` on Linux;
  never a symlink: a sibling rebuilding the shared file in place SIGBUSed a `bun test` that had it
  mapped) an addon for that platform built from `origin/main` into
  `packages/natives/native/`; one that does runs `bun run build:native` (about 13 min, a shared
  `CARGO_TARGET_DIR` keeps it incremental). Build an addon to copy inside a worktree of
  `origin/main`, never in the main checkout: the build rewrites the tracked
  `packages/natives/native/index.d.ts` and leaves that checkout dirty.

### Running on a configured ssh host

For a platform placed on `ssh:<host>`:

1. The host needs git, bun and a Rust toolchain, a clone of oh-my-pi with your fork as a remote of
   the same name (`github.fork_remote`), and this plugin installed so `scripts/rust-check` is
   there. `scripts/doctor` probes each configured host and says what is missing.
2. Push the branch to the fork, then on the host add a worktree of it
   (`git fetch <fork_remote> && git worktree add <dir> <fork_remote>/<branch>`) and install it as above.
3. Non-interactive ssh often lacks cargo on `PATH` (`PATH=$HOME/.cargo/bin:$PATH`) and drops a long
   command when the connection does: run builds detached with a log, e.g.
   `ssh <host> 'cd <dir> && nohup <command> > <scratch>/build.log 2>&1 &'`, and read the log.
4. A host without git credentials can still push through gh's login (the scripts fall back on it;
   by hand: `git -c credential.helper='!gh auth git-credential' push <fork_remote> …`). A host that
   cannot push at all ends `rust-check` printing a `rust-check record:` line; record it from a
   machine that can: `ssh <host> 'cat <scratch>/rc.log' | ../scripts/rust-check --import`.
5. Delete the host's worktree and target dir when the PR merges (workflow step 9).

## The watcher

`pr-queue watch` runs `sync`, then `plan`, and compares with its last run. With `watch.enabled`,
a timer runs it every 30 minutes (the plugin's `contrib/` holds systemd and launchd templates; the
setup wizard installs one); without one, run it at the start of a round. It reports:

- a PR of ours merged, with the count of commits a maintainer added before merging;
- a queued entry `plan` marks `open` (or `next-hour`) became openable, or stopped being openable
  (opened as #N, merged, or what `plan` now says);
- an open ready PR started conflicting with `main` in code (the rule under *How it decides*);
- a merged PR now ships in a release (the first `v*` tag holding its merge commit);
- a bot finding was posted after one of our merges of the last two days (Codex reviews the head
  the maintainer pushed before merging), kept open until a later `main` commit names the PR or
  rewrites its lines, or its thread is resolved (workflow step 10).

It keeps what it found in the manifest's `watch` record: what is openable and since when, open PRs
conflicting with main, merges still unreleased, open post-merge findings, and a week of events.
`pr-trace --summary` fetches the record and prints it first on any machine (`Ready to open since
10:30Z: a, b`, conflicts, `Post-merge findings open: …`, newly released merges), and `--json`
carries it as `queue_watch`. The record is written only when something changed, or hourly so its
`checked` time shows the watcher is alive; a fetched record older than 2 hours prints `Queue
watcher silent since …`, and a machine that could not fetch says so instead (a stale local copy
once read as a silent watcher). While an `open` holds the lock the run is skipped, with a line
saying so in its log.

It is notice only: it never opens, advances, requeues, rebases or pushes a PR branch, never
comments, and sends no alert; its one GitHub write is the status block of a post listed in your
series-posts file (*Series posts*). Acting on what it found stays with the agent: `pr-queue open`
in plan order, `pr-queue advance #N` for a conflict. Logs: `journalctl --user -u pr-queue-watch`
(systemd) or the plist's log dir (launchd, `contrib/launchd/dev.omp-contrib.pr-queue-watch.plist`). Its first run is a baseline and reports no
events.

## Series posts

A discussion post about a series of our PRs (for example Show and tell #16124, a series of macOS
computer-use PRs) can carry a status block that `scripts/post-status N` keeps current. It sits between
`<!-- series-status prs=15157,15173,… -->` and `<!-- /series-status -->`: a `**Merged M of N**`
headline with a bar (`■` merged, `□` not), counts and `updated <Mon D>`, then a `| status | PR |
what it does |` table. `post-status` rewrites the headline and each PR row's status (`merged <Mon D>`
UTC, `in review` for a ready PR with no unmerged needs, `in review, after #A` for a ready PR with some (needs
as for a draft: `needs`, else its Builds-on line), `after #A, #B` for a draft's unmerged needs, `up next` for a
draft with none left, `closed`) and orders the rows merged (by merge time), in review, waiting, closed. The
headline counts only ready PRs with nothing pending as in review; the others count as waiting. Once merged
PRs ship, the headline names the release (pr-trace's first release: earliest `v*` tag holding the merge
commit): `in omp 18.12.2` when every merged PR is in that one, else `12 of 15 released (omp 18.12.2)`
with the latest release; rows keep their merge date. A row's `what it
does` cell, rows without a PR and everything outside the
markers stay as written, since the post's author edits it by hand. A PR joins the series by adding it to
both `prs=` and the table; they must list the same PRs. A PR not opened yet joins by its queue entry
id (`prs=computer-ui-quiet,15282`, PR cell `<!-- computer-ui-quiet -->`, which renders empty): its row
reads `queued, after #A` until `pr-queue open` records the number, then `#N` and a PR's status; a PR
needing it reads `after the queued PR`. `--dry-run` (or `--body FILE`, a local
copy) prints the block and its diff. A write happens only when more than the date changed, after
re-reading the post (an edit in between refuses), and is read back; missing or repeated markers
refuse too.

The watcher runs it after a run in which one of our PRs merged, closed, opened, turned ready or shipped
(`--if-touched`: a post whose `prs=` lists none of them is left alone), for each discussion listed
in `series-posts` beside your config file (`${XDG_CONFIG_HOME:-~/.config}/omp-contrib/series-posts`;
`../scripts/series-posts` is the template): first word of a line, `#` comments. Each refresh edits
a public post, so add a discussion only after the user has approved its block and its automatic
updates; the next watcher run picks it up. Its output shows in the watcher's log as `post #N: …`.

## When `advance` stops on a conflict

The rebase stays stopped in the entry's worktree and `advance` prints the files. The agent that ran
`advance` resolves them there toward `origin/main`'s version of what the needs landed (a maintainer
may have rewritten it before merging), runs `git rebase --continue`, then `pr-queue
advance <id>` again to rebuild the CHANGELOGs and push. A resolution that needs a design call goes
to the user with both versions. It gets no reviewer round: workflow step 3's round was the review.
The same holds for an open PR advanced by name: `#N` instead of `<id>`.

The rerun rebuilds the CHANGELOGs from the worktree's head as well as the fork's tip, each with the
main it sat on: a worktree an earlier `advance --no-push` or a resolved stop left on a newer main
replays from there. Judged against the fork's older tip alone, the replay's old wording of lines
`main` reworded since came back as ours (about 20 coding-agent lines after main's `2407a34d11`
"chore: rewrite changelog").

A stop in a generated catalog file (`packages/catalog/src/models.json`, `compat/rules.json`, both
`binary`) is resolved by taking `origin/main`'s file and regenerating on top of it: `bun run
gen:compat` for `rules.json`, `bun run gen:models --provider <id>` for each provider the PR's
`models.json` change covers (no `--provider`: every provider, from live sources). Since
`6693ddbfd58` `models.json` is an encoded catalog, not plain JSON, so a JSON diff or
delta of it means nothing. When the generator cannot reach the provider, replay the PR's row changes
on plain JSON: `../scripts/models-json decode` each side (main's file, the PR commit's file and its
parent's, via `git show REF:packages/catalog/src/models.json > f`), apply the PR's delta to main's,
then `../scripts/models-json encode <plain> packages/catalog/src/models.json` (it uses the
worktree's `openModelCatalog`/`encodeModelCatalog`; decode then encode is byte-identical).

## How it decides

- **Own commits**: those above `base`; for an open PR without one, every commit past `main` that no
  other open PR or entry owns and that `main` does not already have. The owner of a shared patch id
  is the change the others carrying it declare as a need (recorded `needs`, else a body's Builds-on),
  never one that needs another carrier: a child stacked on its parent's pre-rebase commits never
  makes the rebased parent carry it. A commit siblings hold at one SHA whose parent's rebased copy
  changed patch id is the parent's too. Otherwise the change with the fewest commits owns it.
  `precheck` reads the manifest for this, as `plan` and `audit` do. A branch that merged `main` (or
  a need) after its base holds what those merges brought in too, so its own commits are then the
  non-merge ones past both `base` and `main`: `plan` lands those alone and `advance` replays those
  alone (`git rebase origin/main` while the base is on `main`'s line, else a rebase todo of its own
  commits), leaving it linear.
  `add`, `set --base` and `sync` warn when the base..tip range holds merge commits; check the
  warning's `git log` lists only the entry's work.
- **Merged**: its PR merged; or its branch is part of `main`, or every own commit's patch id is on
  `main` by our author (a closed PR whose current content landed counts too, so what needs it
  unblocks). `plan` marks an open PR whose commits are all on `main` `close`.
- **Plan order**: a PR with a maintainer comment, review or commit in `active_days` first, then P0 >
  P1 > P2 > P3 > unranked, fixes before other types before features, older first. Open ready PRs go
  first, so a queued change never displaces one; it waits for it to merge.
  - An open PR is `keep` when its needs have merged, it carries no other open PR's commits and it
    conflicts with no open PR kept before it (a pair one opened over, below, excepted: its row
    notes `rebases after #N merges` or `opened over P2 #N`); `rebase` when the only thing left is a
    conflict with `main`; `requeue` otherwise.
  - A queued change then opens when its needs have merged, it lands on `main` alone and it
    conflicts with nothing kept or opened; else it waits. A `hold`, or a P2 decision the user has
    not approved under `autonomy.open_p2 = "hold"`, makes it `held` whatever else holds, and it is
    chosen for nothing. Nothing else holds it back: no count of open
    PRs, per area or overall (shaping.md, *Open-PR rule*). Opens past the hour's ready events show
    as `next-hour`; `advance first` marks a queued entry whose base is not on `main` yet. While a
    need is unmerged, its `conflicts with main` is judged on `main` with the needs' current tips
    merged in: its own commits sit on them, so the needs' lines are not its conflict (#15762 was
    once flagged falsely before this). A path a need itself conflicts with `main` in
    shows as the need's (`its need #N conflicts with main in …`), a draft need included, since a
    draft has no row of its own. The watcher's openable events read these same rows.
  - **Opening over an old P2** (shaping.md, *Open-PR rule* 3): a queued P0 or P1
    whose only blockers are code conflicts with open ready P2s (roboomp's label, else the entry's
    priority) open more than `over_p2_days` opens anyway, shown `open (over P2 #N)`; a conflict
    with `main`, through a need, with a P0/P1 PR or with another opening, an unmet need or a hold
    keeps every conflict a reason to wait. `precheck` prints such a conflict as `NOTE sibling` while
    nothing it can see holds the entry, the build step leaves the pair out (no tree merges a
    conflicting pair: `pr-queue tree` prints one tree per side, each built and recorded), and `open`
    marks each P2 `rebases_after` the new number. From then on `plan`, `audit`, `precheck` and
    `open`'s ready check accept that pair's conflict, `pr-trace --summary` flags each side (`rebases after #N merges`,
    `opened over P2 #N`), and once one merges or closes the other, now conflicting with `main`,
    lands under Needs us as `rebase onto main now` (`pr-queue advance '#N'`; a stop is resolved as in
    *When `advance` stops on a conflict*).
    Left to the maintainer: both merging in one wave, the second resolved by the maintainer.
- **Conflicts** are code conflicts once both changes land on `main`: CHANGELOGs merge with
  `merge=union`, and the generated `models.json` / `rules.json` are listed but not counted, since the
  maintainer regenerates them at merge. `pr-trace`'s `vs main` uses the same rule (`omp_pr.classify`).
- **What GitHub shows** is printed beside it and counts for nothing: GitHub's merge ignores
  `merge=union`, so a kept or opening row whose CHANGELOG lines sit where `main` (or another kept
  or opening row, `once either merges`) added lines reads CONFLICTING there (`GitHub:` lines; JSON
  `github: {main, pairs}`). It is no push of its own: the next needed push rebases onto `main`
  (`advance '#N' --no-push` with it), and a queued entry is rebased by `advance <id>` before
  `open`. Unnamed `advance`, the watcher and `open` never act on it (*Cadence*).
