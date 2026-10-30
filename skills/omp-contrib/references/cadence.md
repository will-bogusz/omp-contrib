# Cadence

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

- **Never tag Codex, never request reviews, never bump a stalled PR**: no
  `@codex review`, even after a Codex usage-limit message. Codex reviews by itself when its plans
  have usage (`bots.md`, Availability). Answering a thread a bot already opened is fine, as a
  plain reply with no @-mention. Tagging a maintainer happens only through *Asking a maintainer*.
- Expect bursts. can1357's merge gaps reach 11 days, and #10233 landed in a 240-merge session.
  Silence is not rejection; wait. After each merge round, run `../scripts/pr-trace --summary --open
  --fetch`, then `../scripts/pr-queue sync`, `advance` and `plan` ([queue.md](queue.md)): what
  merged moves `main` under every open PR and frees queued work; then the post-merge sweep of the
  merged PRs' late bot findings (workflow step 10).
- **Wait with `../scripts/pr-trace --wait-change N... --state FILE`, never by polling by hand**:
  it blocks until one of the named PRs merges or closes, turns ready or draft, gets a
  new head (naming each commit a maintainer wrote), a comment, review or thread reply from a person,
  a Codex pass ending on its head, or (ready PRs) a new GitHub mergeability or merge-tree class
  against `main`, and prints one line per change. Name the drafts too: maintainers merge drafts
  directly (#15174). Keep `--state` in the task's scratch so a change that lands while you act
  wakes the next wait; the default bound is 55 min, one `bash` call.
- **Every wait and scan spends your token's 5000 GraphQL points an hour**, shared by every agent
  and the queue watcher using that gh login (about 18 agents once drained them twice in an hour).
  One wait per agent, naming all its PRs: `--wait-change` and `--wait-codex` share one poll per
  machine (a gate of 1 point for up to ~30 PRs each interval, a full read only of a PR that moved).
  After the initial gate + full read, unchanged `--wait-change` costs about 30 points/hour at its
  120 s interval; `--wait-codex`'s 60 s interval costs about 60/hour. Measured live on one
  unchanged PR: 2 initial points, then 1 point 121 s later during a 3 min wait, with no second full
  read. These are steady idle rates, not a ceiling: new waits, changed PRs, and other callers
  add cost. A scan is not a wait: `pr-trace --summary --open` costs about 2 points per open PR
  (58 for 28), `pr-queue plan`/`tree` 6, `precheck N` 2; run them once
  per round, never in a loop, and never loop `gh pr view`/`gh api` to wait. Price a command before
  looping it: `../scripts/gh-cost -- <command>`. Read the points left with
  `gh api graphql -f query='{rateLimit{remaining resetAt}}'` (not charged), not `gh api rate_limit`:
  its `graphql` bucket once read 4300 left while GraphQL refused every query. The
  scripts log each call's cost to `${XDG_CACHE_HOME:-~/.cache}/omp-contrib/gh-spend.jsonl` on each
  machine.
- **Rebase the branch onto `origin/main` for a real conflict with `main`**: `pr-trace`
  `conflict`, `pr-queue plan` `rebase`, cleared the day it appears
  (`pr-queue advance #N` does the steps below for an open PR). **CHANGELOG drift gets one push of
  its own per release, once the PR's bot rounds have settled**: when a release has cut since our
  entry was written, so
  one of our lines lands outside `## [Unreleased]` once `main` is merged in (or a `###` heading
  repeats inside `[Unreleased]`; both `precheck` FIXes and `pr-trace` `changelog` lines), and
  roboomp has reviewed and Codex's pass on the head is over (clean, failed, never started, or its
  findings handled per workflow step 7), push the CHANGELOG fix by itself: `pr-queue advance '#N'`
  rebases onto `main` and moves our entries under the current `[Unreleased]`. `pr-trace` makes it
  the next step (`push the CHANGELOG fix now`). Before the bot rounds settle, drift still rides
  with a push we need anyway (a Codex fix, a maintainer request, a real conflict), since every
  push wakes a Codex pass; a head the maintainer has pushed to is the maintainer's to fix. Why:
  drift left alone cost the maintainer 27 CHANGELOG commits on 20 of 78 PRs merged over three days
  ("move entry to Unreleased", "fold Unreleased sections after merging main"): releases cut while
  the PRs waited a median 15.8 h (p90 36 h) to merge, and upstream's release script promotes only
  lines already on `main`, not ours on a branch.
  Keep a `backup/<branch>-pre-rebase-<date>` ref, then run `../scripts/changelog-to-unreleased
  --tip <backup ref> --old-base <its merge-base with the old main>` (`pr-queue advance` passes both, and a
  second pair for a worktree head past the fork's tip):
  it rebuilds each touched CHANGELOG as `origin/main`'s file plus only the entries our own
  non-merge commits added, under `[Unreleased]` in the `###` section they had (lines `main` already
  has never move; a `main` line a merge of `main` kept after `main` deleted it stays gone, #14759).
  Without the two refs, an old-main line a release has reworded since counts as ours,
  and a replayed line keeps whatever `###` the union merge left it under (#14235, #15496). Fold that
  into the commit that owns the entry, run `../scripts/quiet-refs` (the replayed messages name PRs
  as `PR N`; they are new SHAs anyway), and push once with the other fixes of the round:
  `git push --force-with-lease=<branch>:<old sha> <github.fork_remote> <branch>`. For an open PR,
  `../scripts/pr-queue advance '#N' --no-push` after committing the round's fixes does the rebase
  and the CHANGELOG rebuild with those unpushed commits included; never `git rebase origin/main`
  by hand first, which makes `advance` resume from the fork's tip and drop CHANGELOG lines only
  the local commits add (#15130).
  - **Queued work** is rebased by `../scripts/pr-queue advance` once its needs merge:
    `git rebase --onto origin/main <base>` replays only its own commits. A plain `git rebase
    origin/main` would replay the need's old commits too, and once a maintainer has rebased and
    fixed up the need they no longer match `main` and conflict.
  - GitHub's CONFLICTING badge alone is not a reason: it ignores the `merge=union` that
    `.gitattributes` sets for `packages/*/CHANGELOG.md` (#13681), so it fires whenever `main` gains
    an `[Unreleased]` line next to ours. `pr-trace` names that state apart from a real conflict
    (`vs main  clean; GitHub: conflicting (CHANGELOG only: …)`), and `pr-queue plan`/`audit` print it
    as `GitHub:` lines, also for two of our PRs adding to one CHANGELOG (`once either merges`). With
    no drift it is no push of its own: the next push we need anyway (a drift fix included) rebases
    onto `main` (`pr-queue advance '#N' --no-push`, which rebases a named PR for it). Of 154 merged
    PRs whose pushed head is known, 98 read CONFLICTING on GitHub in a CHANGELOG
    alone when merged, and a maintainer merged `main` into 39 of those (40%) against 7 of 31 clean
    ones (#15574 twice). Placement inside the subsection does not avoid it (evidence.md).

  Why rebase: maintainers used to merge `main` into our branches (`85b3332415`,
  `51a7d6086c`); later the maintainer rebased #15434, #15442, #15444 and #15448 before merging
  (becoming the committer of our commits, adding a regenerate commit to the first three and a
  Cursor policy fix, `dd400fef75`, to #15448) and asked for #15419 to be rebased. A merge commit of
  ours does nothing for a maintainer's rebase: git drops it and replays our commits, so the
  conflict comes back to the maintainer. Why the CHANGELOG has to be right before the merge: every
  one of seven change requests in one round opened with "After merging main, the CHANGELOG
  entry has to go under `## [Unreleased]`, not into a released section", after four releases in a
  day.
- A P2 stall is a scope problem, not a cadence problem: split the default change out.
- **Re-rank by opening a new PR, never by reopening.** Same number, same rank forever (workflow
  step 6). When rework removes the reason for a rank (a split, a default change taken out), open the
  reworked change as a new PR whose body says `Supersedes #N`, point its CHANGELOG links at the
  new number, and close the old PR without a comment. A PR that is P2 by design (it changes a
  default or adds a setting) re-ranks the same; it waits for a maintainer round, with its decision
  carried by the PR itself (*Pick the path*), and under `autonomy.open_p2 = "hold"` the new PR
  waits for the user's approval before it opens (queue.md, *P2 decisions*).
- Before relying on the bots, check they are running: recent issues should carry the `triaged`
  label. roboomp was down about 09-14..09-19. Codex is intermittent (it posts when its plans have
  usage); go without it until it reviews a PR, then wait on it per push (workflow step 7).
