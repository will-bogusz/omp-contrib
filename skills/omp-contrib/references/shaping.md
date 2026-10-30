# Shape the change before writing the body

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

- **A PR merges in the next round when it is easy to merge; shape every PR so no round is lost.**
  Maintainers merge in rounds about daily and clear the queue in one sitting, then go quiet: one
  contributor's 133 merges 2026-09-12..10-12 came in 16 rounds (median gap 1.1 days, longest 14; 42 PRs in 2 h
  44 min on 10-05). Median open-to-merge was 19 h at P0, 20 h at P1, 26 h at P2, and size barely
  moved it below about 1,500 changed lines (19 h under 150, 25 h at 500-1,500, 60 h above, n=5).
  What costs a round is the maintainer's own work on a PR: a body or evidence he must reconstruct,
  logic that is hard to follow, conflicts to resolve.
  One logical change per PR, sized so its reasoning and evidence read in one pass: split by
  decision and by what a reviewer can hold, not by line count.
- **Open-PR rule.** A PR of ours is open on GitHub only while
  1. it targets `main` and carries only its own commits,
  2. it merges onto current `origin/main` by itself, and
  3. it has no code conflict with any other open ready PR of ours (CHANGELOGs merge with
     `merge=union`; the generated `models.json` / `rules.json` are regenerated at merge). One
     exception: a queued P0 or P1 whose only blockers are code conflicts with
     open P2s of ours (roboomp's `review:p2`, else the entry's priority) open more than 3 days
     opens over them, if nothing else holds it (no unmet need, no conflict with `main`, none with
     a P0/P1 PR or another opening). `open` marks each such P2 `rebases_after` the new PR; neither
     counts the conflict after that, and whichever survives the other's merge rebases onto `main`
     at once. Why: merge waves take P0 and P1 first. 10-20 17:00Z merged 33 of ours (10 P0, 16
     P1, 7 P2) and 10-22 09:00Z merged 9, all P0; with 5 P0 / 15 P1 / 30 P2 open now, a P1 held
     behind an old P2 misses waves. The risk left: when both merge in one wave, the maintainer
     resolves the conflict himself.

  Its body carries no merge-order text (`Builds on #N`, `merge #N first`, `Merge after`,
  `Overlaps #N`). Work that needs another PR, or conflicts with one of ours, waits on the fork in
  the queue and opens once what it needs has merged ([queue.md](queue.md)). A draft exists only
  while the user is still deciding a PR's shape.
  - **Open whatever merges alone and clashes with none of our open ready PRs; nothing else holds a
    change back** except the user-decision hold below: no count of open PRs, per area or overall.
  - The only pacing is roboomp's: it silently skips a contributor's review events past 10 an hour,
    so at most 8 ready events go out an hour (workflow step 6) and an open past that goes out the
    next hour (`next-hour`), never later.
  - An open PR whose only break is a conflict with `main` is rebased in place and stays open
    (*Cadence*). It is closed back to the queue only when it needs an open PR, carries one's
    commits, or conflicts with an open ready PR of ours that ranks above it, other than a pair
    opened under rule 3's exception.

  `../scripts/pr-queue plan` applies all of this (keep, rebase, requeue, open, wait); `pr-queue
  audit`, `precheck` (FIX) and `pr-trace` (`rule:`) flag a break. GitHub's native stacked PRs are
  out: they need every branch in one repository, and ours come from a fork.
  Why: all 1,346 PRs merged 09-13..10-13 targeted `main`, merged one at a time through the API or
  in a local bulk merge, so a body's merge order is invisible to both (#14251, "Depends on
  #14249", merged six days before it). A child PR's diff carries its parent, so roboomp ranked the
  child on the parent's code and turned the order into a P2 maintainer call (#15554, #15590). None
  of our six merged "Overlaps" PRs merged as sent, and draft-gated series sat a median 83 h.
  Maintainers resolved real conflicts on 18% of our merged PRs (24 of 135), about as often as on
  other contributors' (17%); the cost is elsewhere: they merged `main` into 50% of our branches
  (19% of others') and pushed code fixups to 35% (20%) (`evidence.md`).
- **Overlapping work: pick the shape by how the changes couple.**
  1. **Both add or change the same code for one purpose (a shared helper, the same fix's two
     halves): one PR**, its commits kept as review steps, helper first; or ship the helper alone
     first and queue each user behind it. Never two copies of the same code. #15446 and #15447 each
     carried a copy of the same reader-identity helpers and conflicted in six files.
  2. **One needs the other's code, or both change the same lines for different reasons: the second
     waits in the queue.** Branch it from the first and `pr-queue add --needs` it; it opens with
     only its own commits once the first merges. A fix never waits behind a feature or a P2
     decision: make it independent of them, or put it first.
  3. **Different files, or only the generated catalog files** (`models.json`, `rules.json`, binary
     in `.gitattributes`): separate PRs off `main`, each regenerated against `main` (`bun run
     gen:compat`, `bun run gen:models --provider <id>`; queue.md *When `advance` stops on a
     conflict*). The maintainer regenerates at merge in one commit (`65124278f7`, `4627619e2e`, `babcbf4ce9`, 2026-10-12), so
     the queue does not count those files as a conflict.
- **Contribute what an OMP user needs, not what our own setup needs.** Tuning knobs for our
  experiments, measurement scaffolding, and vendor coverage beyond the change (rules for models
  the fix never touches) stay out. They can follow as their own PR once a user need exists.
- **Ship a large feature or new provider as a series of chunks, each mergeable on its own.**
  1. Fixes and refactors in shared code that the feature needs, one PR each.
  2. The smallest end-to-end slice a user can use. For a provider: login, one model, one chat
     turn with a tool call, its policy in KDL.
  3. One PR per further capability: discovery or catalog, usage or quota, extra lanes.

  Each chunk meets the bar of a fix: its own CHANGELOG line and test, useful on `main` alone, no
  code waiting for a later PR. Queue each chunk once it is final, behind the chunk it builds on
  (*Overlapping work* 2); chunks that need nothing of each other open side by side. Queue the first
  without waiting on any design conversation (*Pick the path*).
  Why chunks: a large PR is hard to review whole. #8577 (11k lines) sat 45 days and merged only
  after the maintainer moved 1,020 lines into KDL (`2b6c159408`); #11613 (4k) needed four maintainer
  commits. Merged external PRs have a median of 114 changed lines; closed-unmerged ones reach
  3,046 at p90.
  Before the first chunk opens, run the checks on the series integrated: the last queued chunk's
  branch, or a throwaway local merge of chunks that meet only in `main` (series 1's combined branch
  caught 2 integration bugs). The throwaway merge is a test rig: never pushed, never a PR's base,
  never kept fresh (keeping one fresh spends agent usage on every `main` move and buys no review).
- **Split any default-behavior, pricing or default-model change into its own PR** and name it as
  the one maintainer decision. #8590 merged only after its default flip was reverted (roboomp:
  "needs an explicit maintainer call"). #10234 changes a default for every Devin turn and has sat
  since 2026-08-30. #13527 was partly cherry-picked for the same reason.
- **A new setting or capability, opt-in included, and any reversal of a deliberate contract also
  rank P2.** #7197, #13826, #14235, #14237 and #14244 were off by default and still ranked P2;
  #14233 ranked P2 for loosening a fail-closed check the maintainers added in `07f23b6dcc`. 7 of
  12 closed P2s in one contributor's history never merged. Build and queue them anyway, each naming
  its one maintainer decision; *Which PRs open on their own* below says when they open, and the PR
  carries the decision from there (*Pick the path*).
  Before deleting or loosening a guard, fallback or check, find the commit that added it
  (`git log -S '<line>'`) and the issue it answered: removing it reverses that decision, so name
  it as the decision.
- **Output a tool adds to the model's context is a default change.** Text or images appended to
  every result cost tokens on every call, wanted or not, so the evidence is tokens per task and
  task success against `main`, not calls saved: a saved call that returns the same bytes saves
  nothing. Report what changed, sized to the change, with the full view one call away, and first
  remove whatever forces the large output. #14343 appended up to 16 KB per input cell because
  element refs expired on every read; refs that stay stable across reads shrink it to the
  changed rows.
- Model- and provider-conditional policy goes in the KDL rule tree, never TypeScript
  (`AGENTS.md`), fallbacks and defaults included (`on-api … priority=-1` for an API fallback). A
  TS table or constant repeating KDL numbers is the same breach (`3bd6038e09`). An estimate that
  must not undercount defaults to the expensive tier and lists known-cheaper revisions as
  exceptions; test it against real bundled ids (`-latest` aliases, gateway ids, collapsed
  revisions like `claude-opus-45`), not only canonical ones (`26615adc6e`). roboomp flags
  convention breaches as findings, not nits. This includes prices:
  never read a vendor web page at runtime for rates or policy. #11613 scraped Cursor's pricing
  page during discovery; the maintainer deleted it before merging (`a6179d1a4f`, KDL rate card
  only) and accepted two unpriced lanes rather than keep it. When a vendor's page has rates the
  card lacks, send a small KDL PR instead.
- After splitting a PR, diff what stays behind against every split branch. #11613 kept a copy
  of the cached-token fix that #13723 owned, and the maintainer had to remove it (`fb0a01afae`).
- **Which PRs open on their own.** roboomp ranks a PR only after it opens, so the priority here is
  our own estimate, made when the entry is queued:
  - A fix, or a change estimated P0/P1, opens through the queue as soon as the Open-PR rule
    allows (`pr-queue plan` / `open`), with no further question.
  - A change that is P2 **by design** (it changes a default, pricing or default model, adds a
    setting or capability, or reverses a deliberate contract, as the two bullets above define)
    is queued with a hold until the user approves its one maintainer decision: `pr-queue set <id>
    --hold "user, <date>: P2 decision: <the decision>"`, lifted with `--unhold` once they agree.
    Put the decision and our pick in one or two sentences so the user can answer in one reply.
    With `autonomy.open_p2 = "open"` ([config.md](config.md)) no hold is set and it opens like a
    fix.
  - Supervised start: while `autonomy.supervised_opens` is above zero, every PR stops before
    `pr-queue open` for the user's explicit OK on its body, a diff summary and the own-words
    sentence; each approved open counts it down.
  - Whatever opens, anything posted to a human (a comment, a reply, an issue, a message to a
    maintainer) needs the user's approval of its exact text.
