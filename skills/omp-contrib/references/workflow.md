# Workflow: a fix we have already patched

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`. Config keys
in `backticks` (`paths.worktrees`, `github.branch_prefix`, `build.linux`, …) are defined in
[config.md](config.md).

Two omp settings this workflow needs, both set up by the wizard ([setup.md](setup.md)):
`task.maxRecursionDepth` of at least 3, so a worker under a lead can spawn its own reviewer, and a
reviewer of another model family than the session's (the plugin's reviewer-family extension, or
`models.reviewer`).

1. **Check the ground.** Run the duplicate scan (*First: scan for duplicates*) again right before
   branching, then sort the matching issues into ones this PR resolves and ones it only relates
   to (see *Linking issues*).
2. **Branch.** Worktree `<paths.worktrees>/<topic>` on `<github.branch_prefix><topic>` from
   `origin/main`, then in it `bun install --frozen-lockfile --ignore-scripts` and
   `bun run prepare`; never link the main checkout's (`paths.checkout`) `node_modules`. A linked
   one resolves `@oh-my-pi/*`, the natives addon included, to that checkout: a live run skips our
   change in any other package, an addon copied into `<worktree>/packages/natives/native/` is
   ignored, and a Rust change's live check tests `main`.
   `bun run prepare` only generates the export viewer's tool views; the natives addon
   (`packages/natives/native/pi_natives.<platform>.node`) is gitignored, so a fresh worktree has
   none and anything loading `@oh-my-pi/pi-natives` fails. Copy the checkout's built addon into
   `<worktree>/packages/natives/native/` (a copy, never a symlink: the checkout's file changes
   under you on its next build). A workspace load skips the version check, but an addon older
   than the worktree's JS fails on a missing export ("export `X` is missing … rebuild it"): then,
   and for any change in Rust, build it in the worktree with `bun run build:native`.
   Conventional commits scoped to the package (`fix(catalog):`, `feat(ai,catalog):`), each with
   its tests and changelog line. A commit message names other work as "PR N" or by title,
   never `#N`, since each fork push of a commit naming `#N` lands on that upstream PR's timeline
   (`../scripts/hooks/commit-msg` rewrites it on `<github.branch_prefix>*` branches). Remotes:
   `origin` = can1357/oh-my-pi, `github.fork_remote` = your fork.
   Never `git stash` in a worktree: every worktree of the repo shares one stash list, and a
   `stash pop` after a no-op `stash push` once applied another branch's stash. Save a temporary
   revert as a patch (`git diff > <scratch>/x.patch`, `git apply -R`) instead. A subagent starts in
   its parent's cwd, often the main checkout: use absolute worktree paths for every edit, read,
   test `cwd` and git command, or the edits land in the main checkout (two of eight parallel PR
   workers once wrote there and had to recover their changes from a saved patch).
3. **Self-review.** CONTRIBUTING wants the contributor to review every changed file and exercise
   the behavior before submitting. Do that review in full: read the whole diff and run the changed
   path live, from the worktree's own install (step 2).
   For a transport, exercise every
   transport that turn can take, including one ending in a server error: #11613's HTTP/1 path
   hung on end-stream errors because every live check was a successful turn, and the
   maintainer fixed it (`0693c80629`). A fix on one of several backends either covers the others
   or scopes its docs and CHANGELOG to the one it fixes: the browser has Chrome (Puppeteer), Tern
   and cmux, and #14226 and #14232 dropped to P1 for fixing Chrome while the docs promised all
   three. Past the supervised start (step 5) nothing waits on the user's review.
  - **Run live checks and benchmarks on the cheapest model that shows the same behaviour.** First
    name what is measured. Wire and harness behaviour (cache hits, thinking replay and binding,
    request shape, retries, compaction mechanics) is set by omp's code and the catalog, so run it
    on the cheapest model whose KDL rules resolve the same on the axes involved (check
    `classes/*.kdl`: Haiku 5.5 shares Opus 5.5's thinking prefix binding and binding controls on
    direct Anthropic), and say in the body which model ran. Model skill (reading text from
    images, edit accuracy, instruction following) differs by class: measure it on the model users
    run, with a cheaper class only as a pilot. A benchmark that measures both splits in two:
    #14249's read->edit fidelity needs Opus, its cache and signed-thinking cost does not.
  - **Then one independent "what did `main` do" review: one round per PR, total.** The worker
    spawns omp's bundled `reviewer` agent itself (it is pinned to `@slow`; the reviewer-family
    extension overrides that only when `@slow` is the session's own family, or `models.reviewer`
    is set; with `task.maxRecursionDepth` at
    3 a worker under a lead can; never relay it through the lead) with
    [review-brief.md](review-brief.md) as its brief, not "is the fix sound":
    callers and neighbouring paths of everything the diff touches and what `main` does on each,
    persisted entries across rewind and branching, per-call scans, model policy outside KDL,
    peer-supplied guards, cited outside-service claims, tests that fail without the fix. Record the
    verdict (`../scripts/review-stamp ready|needs-changes --by <agent> --sha <reviewed commit>`),
    then fix or answer each finding, giving each behaviour fix a test that fails with the fix
    reverted, and move on: **the fixes are not reviewed again**, and nothing after this step
    spawns another reviewer. roboomp reviews the PR next, and the bots (step 7) catch what is left.
    A scope or design dispute with the reviewer goes to the parent with both positions. Why one
    round: a gated review loop ran a median of 3 rounds per PR (max 15), 41 of 124 after ready,
    and 13 agents ran out of budget in 5 hours; round 1 gave the most findings per round (1.84
    must-fix, against 0.43 from round 4 on), and bots found about 54 issues the reviewers missed.
    Accepted cost: in one round the maintainer's only code fixups landed on the two PRs whose last
    fixes went out unreviewed (#14751, #14754), and 9 of 36 later re-reviews had caught a
    regression introduced by a fix.
  - **Check the reviewer's family.** The extension's note shows in the task UI only; a background
    reviewer's result reaches you without it or the resolved model. The extension appends each
    decision to `~/.cache/omp-contrib/reviewer-routes.jsonl` (`$XDG_CACHE_HOME`; `%LOCALAPPDATA%`
    on Windows): after the reviewer returns, read the line written when you spawned it (`at`,
    `session`, `model`, `note`). A `same-family review` note (only one family available), or no
    line at all (the extension did not run), means the review still counts and the PR's Testing
    section says the independent review was same-family.
4. **Write the body, then queue it.** Derive the body from [framing.md](framing.md), read whole:
   its rules, *Visuals* and the own-words sentence. **Ask the user for the own-words sentence**
   (framing.md, *The own-words sentence*): upstream's `AGENTS.md` says never to generate a
   substitute, so the agent never writes it. A worker that cannot ask the user (a subagent) gets
   the sentence in its prompt, or leaves the template's placeholder line for the session that
   talks to the user to fill before `pr-queue open`; precheck refuses a body without it.
   As you write each idea, ask whether a figure
   would show it better than the table or paragraph you are about to write (*Visuals* says which
   ideas a figure carries and which read at once as text). If one would, make it now, in this
   draft: a timeline or decision flow is one `figures.json` and one
   `charts/run.mjs DIR --body <file>` ([charts.md](charts.md)). If not, write the text and move on;
   nothing records why. Of 21 PRs opened over four days, one had a figure and five went out
   without one they would have read better with: no step asked while the body was written, and 8
   of 13 writers never opened framing.md.
   Then `../scripts/pr-queue add <github.branch_prefix><topic> --title '<type(scope): …>' --body <file>`,
   with `--needs` when it builds on unmerged work ([queue.md](queue.md)). The title is a
   Conventional Commit and becomes the merge subject (`Merge PR #N: <title> (@<github.fork_owner>)`).
   A change that is P2 by design (shaping.md: it changes a default, adds a setting, or reverses a
   deliberate contract) is added with `--p2-decision "<the one maintainer decision>"`: under
   `autonomy.open_p2 = "hold"` it waits for the user's approval of that decision (queue.md,
   *P2 decisions*; `pr-queue approve <id>` records it). Before it opens, check the stored body's closing keywords against the
   issues meant to close.
5. **Open it when `pr-queue plan` marks it `open`**: `../scripts/pr-queue open <id>`. A worker in
   a round of several stops after `add`: the round's opener runs this step for every entry and
   hands each worker its PR number for step 7 (*Opening* in [queue.md](queue.md)).
   **Supervised start:** while `autonomy.supervised_opens` is above zero, the opener stops before
   `open` and shows the user the stored body, a diff summary (files, lines, what changes for a
   user) and the own-words sentence, and opens only on the user's explicit OK, with
   `pr-queue open <id> --user-approved` (refused without it; queue.md, *Supervised start*). roboomp reviews each PR number once, ever, so a
   mistake in an early PR is permanent.
   While the user's opening pause is set, `plan` prints it first and marks such rows `paused`,
   `open` refuses, and `precheck N` prints a FIX for a draft: nothing opens or turns ready, by
   hand either, until `pr-queue unpause`. `open` refuses
   unless the entry's needs have merged, its own commits sit on `origin/main` and land there alone,
   it has no code conflict with an open ready PR of ours, its merged tree with each open ready PR
   sharing a crate or package is recorded as built and tested (`pr-queue tree`, the steps under
   *Opening*), the hour's ready
   budget has room, and `../scripts/precheck` passes on the branch and the stored body. Then it
   pushes, opens a draft, appends the PR link and credit to each new CHANGELOG entry in one
   `docs(<scope>):` commit, reruns precheck, and marks the PR ready. Afterwards read the published
   body back (`gh pr view N --json body,closingIssuesReferences`) and tick only checklist items that
   actually ran. precheck prints FIX for
   what roboomp or the maintainer flags (inline `import()`, `as never`/`as any`, a touched
   package without an attributed `[Unreleased]` entry, an entry that lands under a released
   heading once `origin/main` merges in, body headings, length, own-words line, @-mentions,
   merge-order lines, another open PR's commits on the branch, a code conflict with an open ready
   PR of ours, a Rust diff without a `rust-check` record for each platform it builds on) and NOTE
   for calls to make
   (new casts in source, full-string test assertions, `test.each` rows, mock casts, env-key
   fallbacks, changed signatures without a Breaking Changes entry, docs naming a changed function,
   model-family constants or id matching outside the catalog's KDL rules, a URL, token or env
   value rendered unredacted into a prompt, open issues mentioned but
   not closed, generated-file overlaps, open ready PRs in the same crate or package (build the
   merged tree), no review recorded, and the preparation checks of
   `code-style.md`: removed calls, commits scoped outside the title, tests asserting on script
   text, readers of a type's fields that miss a new one). A CHANGELOG FIX or a real conflict
   with `main` is cleared by `pr-queue advance` or a rebase onto `origin/main` (*Cadence*); a
   sibling FIX means one of the two waits in the queue (`pr-queue plan` says which). A `rust` FIX
   is cleared by `../scripts/rust-check` for that platform, run where `build.<platform>` places it
   (here, on an ssh host, or `--ci` on the fork's GitHub Actions: queue.md *Where builds run*),
   which records the pass in the queue. A platform set to `none` is not checked: precheck prints a
   NOTE instead of the FIX, and the PR's Testing section says which platform's Rust went
   unchecked. Run it again before any later push that changes a Rust line, a bot-round fix
   included, since CI compiles no Rust before the merge (#16202's bot-round push broke the Wayland
   build, `bf9fd4bd6a`).
6. **Why `open` goes through a draft.** roboomp reviews each PR number at most once, ever: on the
   first `opened`, `reopened` or `ready_for_review` of a non-draft PR that gets past its rate
   limit. Once a review is submitted, later reopens and draft -> ready toggles are skipped
   (`python/robomp/src/tasks.py` `review_pr`, `has_successful_tool_call(key,
   "submit_pr_review")`). So the head it sees must be final. Opening non-draft and amending the
   attribution a minute later produced roboomp's commonest false positive, "missing changelog
   attribution" (#10234, #13527, #12523, #11879). Never leave a PR in draft expecting review:
   drafts get no bot review and maintainers rarely act on them (#8577 45 days, #11613, #11650),
   though a maintainer does read them (our draft #15276 was closed by one).
   - **Stay under roboomp's rate limit, or the review is silently lost.** The cap depends on your
     author tier (`bots.md`): a CONTRIBUTOR gets 10 queued events per rolling hour across all
     their PRs and issues (code defaults in `config.py` `rate_limit_contributor`,
     `rate_limit_window_seconds`; the deployment's env may differ, so the label check below is the
     real test). Opens, reopens and ready toggles of non-draft PRs and new issues count; draft
     opens and pushes don't. An event over the cap is recorded as skipped and never retried
     (`server.py`). `pr-queue` keeps a ready budget two under that cap (8 an hour for a
     contributor, 1 for a first-time author; `plan`'s `Ready budget:` line names your tier),
     issues filed in the same hour included: it counts them on GitHub, and past the budget an
     open waits for the next hour (`next-hour`).
   - **Confirm the rank arrived.** Within 30 min, `gh pr view N --json labels` shows a
     `review:pN` label. If roboomp neither labeled nor reviewed, the event was dropped: once the
     hour has cleared, `gh pr ready N --undo && gh pr ready N` triggers it again (this works
     only because no review was submitted).
   - **Work whose shape the user is still deciding stays out of the queue.** If they want it
     visible meanwhile, it is a draft opened by hand; once they settle the shape it goes through
     the queue like any other change. A final PR is never held as a draft to control merge order:
     work that needs another PR waits in the queue (*Open-PR rule*).
7. **Wait for the bots, then judge** (details in `bots.md`). roboomp posts in about
   4 min (p90 25 min), once per PR. Codex reviews each new head while its plans have usage
   (`bots.md`, Availability). **Once Codex has reviewed a PR, every push to it waits for Codex's
   pass on the new head to end: run `pr-trace --wait-codex N` (several PRs at once if you pushed
   several) and handle what it prints**: `clean`, `findings` (handle them,
   below), `failed` (the pass ended without a result), or `never` (no 👀 from Codex within 30 min
   of the push: that push gets no pass, so stop waiting). Codex's 👀 on the PR body is the pass
   in progress (`bots.md`); `pr-trace` flags it as `Codex reviewing head`, a push it has not
   started on as `Codex due on head`. Why: four PRs (#15130, #15133, #15489,
   #15498) once sat 6-23 h on findings Codex posted 6-12 min after a fix push whose agent had
   already reported done. The 30 min and the 45 min after which 👀 counts as a dead pass are
   measured in `bots.md` (Latency). Before
   Codex has reviewed a PR (out of usage, or not started), don't wait for it. A review landing
   after the wait goes to whichever session next sees it in `pr-trace`.
   **Codex findings** (a pass is one completed Codex review of one head, a
   clean 👍 included; a round is a pass with findings). **Aim: the head the maintainer gets has a
   clean Codex pass, or only findings we declined as design-level.** The maintainer loops on
   Codex before merging and fixes whatever is still open, findings we declined included; in one
   round the three PRs whose final head had no open finding got no code from the maintainer.
   - **First, a third round landing in the same function or model means the approach is wrong.**
     Before fixing that round, ask whether a platform, browser or OS API
     already answers the question the code models by hand, or whether storing less would leave
     the findings nowhere to land (code-style.md, *Pass state explicitly*). If so, replace the
     model in this PR's next push, which also answers the round's threads (`Fixed in
     <sha>`); it is how the PR keeps its promise, so it is neither a decline nor a follow-up. Only
     when neither exists, handle the findings as below. On #15496 three of our rounds and
     eight of the maintainer's patched a hand-written CSS clip and visibility model until it was
     replaced with the browser's hit test plus a check that the page received the click
     (`7698846f87`, +176/-239). #15574 took 15 Codex rounds, most findings on what its refs
     stored; the maintainer's merge kept a hash and its proving walk per ref instead
     (`6e211f8cd8`, +211/-345). `pr-trace` names a file whose Codex findings span three rounds,
     the latest included.
   - **Fix every cheap finding, P2 included**, every fix of a pass in one push. Cheap means the fix
     stays inside the PR's design (a guard, a check, an ordering, a missed case on a path the PR
     already touches), however many lines it takes. How rarely the trigger occurs is no reason to
     skip one: the maintainer's first commit on #15502 was a 4-line fix for a finding we had
     declined as needing "a page that installs a throwing getter" (`77cca7b7a0`), and on #15496
     the maintainer implemented 6 of the 7 findings we had declined (`3b60ccd8a5`).
   - **Decline only a finding whose fix needs a design change**: a new mechanism (a lock, a cache,
     a protocol, new persisted state), an outcome outside the title's promise, or reversing a
     decision the body states and argues. Reply in one line naming that change, then resolve the
     thread: `Not fixing here: needs <the design change>, beyond what this PR <promises>.` A finding
     that is wrong is not declined but disproved (Invalid, below).
   - **Stop pushing for Codex at the first of:** (a) its last pass on the head is clean; (b) every
     finding of that pass is declined as design-level or disproved (Codex settled); (c) before
     hand-off, the PR has had 5 rounds (the budget). Past the budget only a P0/P1 gets a push,
     with one exception: a cheap finding on lines our latest push wrote is a regression we just
     shipped, so it is still fixed, once (one more push; the pass after it gets none, whatever it
     finds). `pr-trace` names
     those threads (`past the budget, on a line our latest push wrote`; it blames the line's commit
     to after Codex's previous review). On #15418 the round-5 push made an idle close always sent,
     and Codex's round-5 finding was that the close could now block every later write. Reply to
     each other P2 `Not fixed yet: <the fix in one line>; Codex round budget
     spent.` and resolve it: the fix stays on record as ours, cleared at hand-off (next bullet). A
     later push (a maintainer request, a real conflict with `main`, a real bug) still waits for its
     pass, and that pass's findings are handled by these same rules. `pr-trace` shows `Codex
     clean`, `Codex settled`, `Codex budget spent`, `Codex findings` (fix or decline), `Codex fixes
     pushed`, and `maintainer pushed` (a head a maintainer committed: its findings are theirs).
   - **At hand-off the budget ends: every valid Codex finding is ours.** A PR is
     handed off when the user sends it to a maintainer (a tag or message: *Asking a maintainer*),
     or once a maintainer reviews, comments on or asks for changes on it, and stays so until it
     merges or closes. Before it goes, and on every pass while the maintainer has it, fix each open
     finding, the ones the budget skipped included, with a test that fails without the fix; or
     disprove it with evidence, or decline it in our words (`Not fixing here: …`, above). Then edit
     each `Not fixed yet` reply in place
     (`gh api -X PATCH repos/can1357/oh-my-pi/pulls/comments/<id>`) to
     `Fixed in <sha>: <what changed>. Test: <name>.` or the decline or disproof, and edit any
     comment of ours that leaves work to the maintainer (`left for review`, `left for you`, `for
     the maintainer`), changing only those sentences. Each fix push waits for its pass, handled
     the same way, until a pass is clean or settled. Why: under the budget, replies saying `Left
     for review` and top-level comments telling the maintainer a finding was "left for you" on
     #15105, #15128, #15130, #15433, #15574, #15762 and #15920 handed the maintainer work that was
     ours. `pr-trace` counts a PR as handed off when its queue note says it is with a maintainer or
     a maintainer reviewed or commented on it, lifts the budget and lists its `hand-off` items
     (each deferred reply, each comment with hand-off wording) as work for us. To check a PR
     before it goes, name it: `pr-trace --summary N …` lists the same items as `pre-hand-off`,
     budget unchanged and not counted as needing us.
   - **No pushes that aren't fixes**: a rebase for anything short of a real conflict, and a
     CHANGELOG move while the bot rounds are still open, only ride along with a push we need anyway
     (*Cadence*): every push wakes a Codex pass. Once they have settled, a release that moved our
     entry gets one CHANGELOG-only push (`pr-queue advance '#N'`; *Cadence*).
     Never request a pass with `@codex review`.
   Why the budget: Codex finds about 2 things per round in every round (1.8 in round 1, 2.4 from
   round 5 on), so a clean pass alone may never come; in one study of our PRs, 11 of the 12
   material findings came in rounds 1-3 and none of the 104 from round 4 on.
   roboomp never re-reviews (step 6), and `@roboomp` on a contributor PR does nothing (0 of 49).
   - roboomp's review-body notes are findings too, not only its inline threads (`bots.md`,
     *Judging a finding* 5; `pr-trace` prints them as `roboomp note:`). The maintainer's fixups
     landed on them in one round: #14753 "the live check covered `shouldLogout`, not a successful
     renewal" (the renewal stored the wrong refresh token), #14758 "`--history` now throws
     instead of printing" (a one-line error was added), #14762's proxy default (a trusted-proxy
     test was added).
   - Treat each finding as a claim to test against the code, the precedent in other providers,
     and a live run. Roughly 3-5% of bot threads in the corpus were wrong; on our PRs about 3 of
     22. The finding says where the problem is; the fix is ours to design. Both
     ways of going wrong drew maintainer fixups: declining or half doing a finding (#14226,
     #14247, #14251, #14277, #14338, #14485, where the maintainer's fix was the mechanism roboomp
     had proposed), and pasting roboomp's suggested patch as is (#14420, #14425, #14431, where its
     patch was too broad, mis-ordered or broke a neighbour). Answer every clause, make each input
     or path it names a test case, and run the blast-radius list above over whatever fix you
     adopt, including a guard you add only because it asked. When roboomp asks whether invalid
     input should fail and a sibling backend already fails, make it fail rather than list it as a
     non-goal. Our other open PRs are never a reason to decline or bend what a reviewer asks: each
     PR merges alone (*Open-PR rule*) and the queue absorbs the conflict. #15599 kept
     `bodyIfOmitted` to spare our #15555 a conflict, and the maintainer applied roboomp's
     `(selector = "body")` default anyway (`7e34ec86d5`).
   - Valid: fix it, and batch all fixes into one push per round: each push wakes another Codex
     pass (#10648 grew to +939/-67 over 10 Codex rounds) and reruns CI. No reviewer for bot fixes
     (step 3's one round was the review): each behaviour fix carries a test that fails with it
     reverted, and the targeted tests run before the push.
   - The same kind of finding a second time, on one PR or across our PRs in one area, means the
     code lets it keep happening: fix that cause (one check, type or helper every path must go
     through), not just the second line it names. #15293 took five Codex rounds,
     each finding a foreground check that the previous fix had moved. A third Codex round in one
     place goes further: see the first Codex bullet above.
   - Reply in the thread: `Fixed in <sha>. <root cause in one sentence>. <the regression test>.`
   - Invalid: reply with live evidence and add a regression test or a code comment where the
     suggestion pointed, so the next reviewer does not raise it again (#13527 "Not restoring the
     gate. I tested both paths live ...").
   - Stale (raced an amend): say it is already on the head and name the sha.
   - Resolve each Codex thread right after the reply, with the GraphQL `resolveReviewThread`
     mutation (`pr-trace` prints the thread id under `resolve`). Leave roboomp threads open for
     the maintainer.
   - Reply to every roboomp thread in its thread, with no exceptions. Its
     review body mostly restates the inline findings ("One blocking issue, inline: …") around a
     summary, and the thread replies answer those. One top-level PR comment answers only body
     content that has no thread: every question roboomp leaves for the maintainer, and each
     body-only finding (an untested path, a trade-off, a behavior note), one line each, with what
     changed and the sha when it was settled in code. Leave out summaries, praise, test-run reports
     and pointers to a thread; when nothing qualifies, post no top-level comment (mirrored
     comments on #15418 and #15419 only repeated the thread replies).
   - A question roboomp raises for the maintainer (a "maintainer call", "open question",
     "decision for the maintainer") gets our best answer, posted as a reply to the bot without
     waiting for the user's approval: the recommendation first, the evidence behind it, what the
     other choice would cost, and how small the change is if the maintainer picks it. Post it
     where roboomp raised it (its thread, or that one top-level comment for a review-body
     question). No @-mention. With the decision the body names, this answer is how the maintainer
     sees a P2's decision; nothing more goes to the maintainer (*Asking a maintainer*).
   - Replies to bots need no approval. A reply to a maintainer's change request follows
     *Maintainer change request* below. Other text addressed to a maintainer (a tag, a
     question of our own) needs the user's approval of the exact text and goes
     through *Asking a maintainer*.
8. **Done** when every bot thread and review-body note is settled, Codex's wait on the last push is
   over with nothing of its passes left to fix or decline (step 7), the head has no real conflict
   with `main` and `pr-trace` shows no `rule:` line for it, our last push left no CHANGELOG line
   outside `[Unreleased]` (drift a later release causes gets its one push once the bot rounds settle, *Cadence*),
   and the body matches the head. Then leave the worktree until the PR merges, but
   delete its Cargo `target/` (`rm -rf target`): a natives build leaves 2-3 GiB per worktree, and
   a few idle worktrees fill a laptop disk. A shared `CARGO_TARGET_DIR` or `sccache` keeps the
   later rebuild to minutes.
   Whoever opens the PR owns steps 7-8 in the same task, and so does every later agent that pushes
   to it (a bot-fix sweep, a change-request round): wait for roboomp and for Codex's review of your
   own last push, handle every finding
   and review-body note, and only then report done. A delegating prompt must never say "don't
   wait for bot reviews": five PRs once sat with unhandled roboomp reviews after an opener was
   told to skip this step. It also carries the user's own-words sentence when the worker writes
   the body (step 4): a subagent cannot ask the user, and must not write one itself.
9. **Merged or closed:** remove the worktree, in whichever session notices first (including a
   `pr-trace` resume): copy anything uncommitted worth keeping (scratch notes, fixtures) out of
   it, then `git worktree remove <paths.worktrees>/<topic>`; the branch ref stays. For a merge,
   do the *Learn from each merge* review (in *Write the code the way the maintainers do*) first;
   it reads the merge from the canonical repo, not the worktree. Never remove a worktree whose
   `git rev-list --count HEAD --not --remotes` is nonzero without the user's go-ahead.
10. **Post-merge sweep, every session and every merge round** (standing step, not optional): Codex
   reviews the head the maintainer pushes right before merging (a merge of `main`), so its
   findings land after the merge, and while Codex is out of usage during review that pass is the
   only one a PR gets. The maintainer fixed earlier ones on `main` (`13d09929b7`, `1a97f79d28`,
   `d25d0ed5a9`, `8f5a0aa4ea`, `864c1b370a`, `8567bdcab1`, `3166e4d221`). The queue watcher
   (`pr-queue watch`; on a timer when `watch.enabled`, else run it at the start of a round) asks
   for findings on every merge of the last two days each run and keeps one open until a later
   `main` commit names the PR or rewrites its lines, or its thread is resolved;
   `pr-trace --summary` prints them first (`Post-merge findings open: #N Codex P1 x1`)
   and lists each in Needs us (`post-merge: … open`), past its `--since` window too. For each:
   judge it as in step 7 against the code on `origin/main`; a valid one gets a follow-up PR off
   `main` with a regression test that fails there (the full step 1-8 path, its body opening
   `Follow-up to #N` or linking the finding), before the maintainer has to: while that PR is open
   or merged the summary shows the finding as `addressed by #M` under the merge instead of in
   Needs us, and back in Needs us if it closes unmerged; a wrong one gets a reply with the
   evidence in its Codex thread, then the thread resolved (that drops it from the list).

## Maintainer change request

A maintainer may write change requests as top-level PR comments on PRs not merged that round
(often opening with a CHANGELOG "Rebase note"), and push fixups onto the ones being merged.
`pr-trace` shows an unanswered one as `CHANGES` and makes it the next step.

1. One agent per PR, in its worktree. `git fetch origin && git rebase origin/main` (*Cadence*;
   maintainers also rebase our branches themselves), resolve conflicts the way the comment says, and
   run `../scripts/changelog-to-unreleased --tip <backup ref> --old-base <its old merge-base>` to put
   our CHANGELOG lines back under `## [Unreleased]`
   (precheck FIX otherwise), then `../scripts/quiet-refs` (replayed messages name PRs as `PR N`).
2. Treat every point, nit and docs line as a finding: design the fix, build the blast-radius
   list (*Write the code the way the maintainers do*), and give each behaviour fix a test that
   fails with the fix reverted. The maintainer's suggested snippet is a pointer, like roboomp's.
3. No new reviewer round: the PR had its one (step 3). Give each behaviour fix a test that fails
   with it reverted, run the targeted tests and precheck, then push once.
   - **Scope: the maintainer's ask, plus defects in code this PR adds, fixed within the PR's
     design.** A defect whose fix needs a new mechanism (a cross-process lock on #14416, a shared
     staging folder on #14544) goes in the body as a one-sentence residual risk, unless the head
     is worse than `main` there; then fix it or drop the part that regressed. The #14544 redesign
     went beyond the ask and had to be walked back to its scope plus our own data-loss fix.
4. Reply with a top-level comment in the PR thread, mirroring the maintainer's numbering, one line
   per point: `Fixed in <sha>: <what changed>. <test that fails without it>.` plus a first line
   for the CHANGELOG move. No @-mention: the maintainer is notified as a participant. The reply is
   text to a human: show the user its exact text and post it only once they approve. A reply that
   disagrees, declines a point, or asks something is drafted the same way and goes through
   *Asking a maintainer*.
5. A queued entry that needs one merged with maintainer fixups (#14765 needed #14764) is advanced
   at once (`pr-queue advance`, [queue.md](queue.md)): only its own commits replay, resolved
   toward the maintainer's version of the shared code.
