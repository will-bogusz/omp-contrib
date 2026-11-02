---
name: omp-contrib
description: MUST read first whenever the user reports something omp (oh-my-pi) does wrong or asks to fix omp ("omp did X wrong", "omp keeps …", "the edit tool broke", "is this an omp bug?", "fix it upstream"), including when the session is inside an oh-my-pi checkout; such fixes land as reviewed PRs on can1357/oh-my-pi through this skill, never as direct edits to the checkout. Also for turning a session .jsonl into a fix and for any oh-my-pi PR or issue work (status, bot reviews, change requests, the queue).
---

# Contributing to can1357/oh-my-pi

**First:** run `scripts/doctor --json`. If it reports the skill unconfigured, run the setup wizard
([references/setup.md](references/setup.md)) before anything else; if it reports drift, repair or
re-offer what it names. Every machine-specific value (identity, remotes, paths, build hosts,
models, autonomy) comes from the config file: [references/config.md](references/config.md).

A PR lands when a maintainer can decide from the body alone, and roboomp can rank it P0 or P1.
This skill builds on `rule://omp-pr-authoring` (the four questions, register by surface, length
budget); read that first. Where the two differ for omp, this file says so. Facts are dated
2026-09-28; re-read upstream's own documents at `origin/main` each time, since they win:
`CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `AGENTS.md` sections *GitHub* and *Changelog*,
`python/robomp/src/prompts/` (what the bot checks).

This file routes: open the reference for the phase you are in. Each rule's source is in
[references/evidence.md](references/evidence.md).

## Invariants (hold even without opening a reference)

- The duplicate scan comes first, before any fix, body or issue.
- Work on oh-my-pi worth keeping becomes a PR on can1357/oh-my-pi; nothing is carried locally,
  and a fix we can make is never filed as an issue, before or after.
- A request to fix something upstream (`/contribute`, "fix it upstream") is the user asking for
  commits: commit on `<branch_prefix><topic>` in its worktree, which `review-stamp`, `precheck` and
  `pr-queue add` all read. That ask satisfies upstream `AGENTS.md`'s "never commit unless asked";
  never commit in the user's checkout (`paths.checkout`).
- Never tag Codex, request reviews, or bump a stalled PR. A P2's maintainer decision rides on its
  PR (the body names it, our answer to roboomp's question argues it): report the PR to the user
  as waiting on a maintainer round. Draft a message to a maintainer only when the user asks or
  *Asking a maintainer*'s tag test holds.
- Anything addressed to a human (a maintainer, an issue author, a discussion), and every new issue,
  posts only after the user approves its exact text. Replies to bots need no approval, and that
  includes our answer to a question roboomp raises for the maintainer, posted in roboomp's thread.
- A PR opens through `scripts/pr-queue open` (draft, CHANGELOG link, precheck, then ready):
  roboomp reviews each PR number once, ever, on the head it first sees.
- **Opening policy.** A PR of ours is open only while it merges onto `main` by itself and has no
  code conflict with our other open ready PRs (except a P0/P1 whose only blockers are P2s open
  longer than `over_p2_days`, which opens over them), and no body carries merge-order text;
  everything else waits in the queue. Fixes and changes we estimate P0/P1 open automatically when
  `pr-queue plan` marks them `open`; no count of open PRs holds them back, and there is no rank
  threshold (roboomp ranks only after opening). A change that is **P2 by design** (it changes a
  default, adds a setting, or reverses a deliberate contract: [references/shaping.md](references/shaping.md))
  is queued with a hold until the user approves its one maintainer decision
  (`autonomy.open_p2 = "hold"`; `"open"` lets it open like any other). While the user's opening
  pause is set (`pr-queue pause`), nothing opens or turns ready ([references/queue.md](references/queue.md)).
- **Supervised start.** While `autonomy.supervised_opens` is above zero, each PR stops before
  `pr-queue open` for the user's explicit OK on its body, a diff summary and its own-words
  sentence; each supervised open counts it down. After that, opening is autonomous.
- **The own-words sentence is the user's.** Ask for it once, at intake, while the user is there
  (*Fixing something omp did wrong*), record it with `contrib record own-words`, and put it first
  under `## What` verbatim; never write, suggest or edit a substitute (upstream `AGENTS.md`).
  precheck FIXes a body whose first paragraph there is not a recorded sentence. No body carries
  private context.
- Before the PR opens, one independent reviewer works through
  [references/review-brief.md](references/review-brief.md) (what `main` did on every path the diff
  touches), stamped with `scripts/review-stamp`. The reviewer is omp's bundled `reviewer` agent
  (its models: omp's `task.agentModelOverrides.reviewer`, else `@slow`); the plugin's
  reviewer-family extension takes the first of them from another lab than the session's, else
  the other of Anthropic and OpenAI (other labs only as fallback). After it returns, read its
  routing line in `~/.cache/omp-contrib/reviewer-routes.jsonl` (workflow.md step 3): same family →
  the PR's Testing section says the review was same-family. One round per PR, total: its fixes,
  bot fixes and change-request fixes are not reviewed again, so never spawn a second reviewer to
  confirm them.
- The opener waits for the bots and settles every finding, review-body note included, before
  reporting done; once Codex has reviewed a PR, every agent that pushes to it waits for Codex's
  review of that push. Before a PR goes to the maintainer we aim for a clean Codex pass on its
  head: every cheap finding is fixed, P2s included; only one needing a design change is declined
  (one line naming it, then resolved); pushing for Codex stops at a clean pass, a pass whose
  findings are all declined or disproved, or the 5-round budget, past which a cheap finding on
  lines our latest push wrote still gets one push, once, and its other findings get a
  `Not fixed yet: <fix>` reply; once the rounds settle, those deferred fixes go out in one final
  push, since the maintainer usually merges before any hand-off (workflow step 7). At hand-off (the
  PR goes to a maintainer, or a maintainer reviews it) the budget ends: every valid finding is
  ours, fixed, disproved, or declined in our words, and no comment of ours leaves work to the
  maintainer. A push that fixes nothing never
  goes out, except one CHANGELOG-only push per release once a PR's bot rounds have settled
  (*Cadence*). Every roboomp thread gets a reply in its thread; a top-level comment carries only
  body content that has no thread (workflow step 7).
- While writing a body, each idea a figure would show better than its text or table gets that
  figure in the same draft; text needs no stated reason. Writing the body is workflow step 4;
  the form is framing.md's *Visuals*.

## Fixing something omp did wrong

One chain, whether the ask came as `/contribute` or as a plain "can you fix it upstream?". The
steps live in `scripts/contrib`: after each one run `contrib next`, which names the one step left,
its command, and who acts (`agent`, `user`, `wait`, `done`, `stopped`). Do the agent's steps
without asking; stop for the user's. `pr-queue add` refuses until the chain before it is done.
When the user asks to stop or pause, run `contrib pause "<their reason>"` (not `contrib stop`, which
ends the contribution).

0. `contrib start "<what omp got wrong>"`, then ask the user, once: *"In a sentence, in your words:
   what should change, and why does it matter to you? It goes first in the PR, verbatim."* Keep
   working; record the reply as written (`contrib record own-words "…"`). Only a sentence they
   wrote as that answer counts (one given up front, after "in my words:", is fine); their report
   of the bug is not it, so ask.
1. Duplicate scan, before reading code for a fix (`contrib record dup-scan`). A merged fix, an
   open PR, expected behaviour or code outside omp ends the chain: `contrib stop <reason>
   --evidence …`, and report it.
2. Worktree `<paths.worktrees>/<topic>` on `<github.branch_prefix><topic>` from `origin/main`
   (workflow step 2); never edit the user's checkout.
3. Reproduce on `origin/main`, fix with a test that fails without it, commit;
   `contrib record repro --before "<test command>"` runs it both ways.
4. One `reviewer` with review-brief.md as its brief; `review-stamp` its verdict; fix its findings;
   `precheck` on the code (it needs nothing from the user).
5. `contrib body` (the body file, opening with the user's sentence), the rest per framing.md,
   `precheck --body <file>`, `pr-queue add`.
6. Stop before `pr-queue open` while supervised opens remain: the user OKs the body.

Where pushing is not allowed, the chain still runs to `pr-queue --manifest <file> add … --no-push`
(`contrib start --manifest <file>` puts it in `next`'s command): only the push and `open` wait.

## Phases

- **Set up or repair the configuration**: no config, `doctor` drift, or the user asks to change
  a choice. [references/setup.md](references/setup.md); keys: [references/config.md](references/config.md)
- **Scan for duplicates**: before anything else, and again right before branching. [references/duplicates.md](references/duplicates.md)
- **Who decides / pick the path** (PR, issue, or discuss first): when deciding what to open. [references/paths.md](references/paths.md)
- **Shape the change**: before writing the body; the Open-PR rule, overlapping work, splitting, large features, default changes, KDL policy. [references/shaping.md](references/shaping.md)
- **Queue**: when a branch is final, at the start of PR work and after each merge round (`sync`, `advance`, `plan`), to open or requeue a PR, and when `advance` stops on a conflict. [references/queue.md](references/queue.md)
- **Write the code the way the maintainers do**: while coding and after each merge. [references/code-style.md](references/code-style.md)
- **Frame the body for the reader**, visuals and the form each idea takes, and **the own-words sentence**: when drafting or rewriting a body. [references/framing.md](references/framing.md); drawing a chart, opening image or diagram: [references/charts.md](references/charts.md)
- **Workflow: a fix we have already patched**: branch, self-review, independent review, queue and open, bots, done, clean up; and **Maintainer change request** when a maintainer sends a PR back. [references/workflow.md](references/workflow.md); bot behavior: [references/bots.md](references/bots.md)
- **Resume a PR opened in an earlier session**: when asked about hanging PRs. [references/resume.md](references/resume.md)
- **Linking issues** and **Issues: a problem we have not patched**: closing keywords; filing an issue roboomp can reproduce. [references/issues.md](references/issues.md)
- **CHANGELOG and attribution**: every touched package. [references/changelog.md](references/changelog.md)
- **Cadence**: waiting, rebasing onto `main`, re-ranking, bot health. [references/cadence.md](references/cadence.md)
- **Asking a maintainer**: when the user asks for a message to a maintainer, or one small answer would unblock several PRs. [references/maintainers.md](references/maintainers.md)
- **Pre-submit checklist**: before marking ready. [references/checklist.md](references/checklist.md)

Curated PRs and issues to learn from: [references/examples.md](references/examples.md).
Scripts (paths relative to this skill's directory): `scripts/contrib` (the fix chain's step
records: `start`, `record`, `body`, `stop`, `next`, `status`), `scripts/doctor` (config, tools, hosts and
upstream-document drift; `--json` for `/contribute`), `scripts/pr-trace` (start every status scan
with `--summary --open --fetch`; after a push, `--wait-codex N` waits out Codex's pass; waiting on
PRs for anything, `--wait-change N... --state FILE` returns on the first merge, push, person's
comment, Codex pass end or conflict change; after a merge, `--learn [N ...]` lists what
maintainers changed before, inside and after it), `scripts/pr-queue`, `scripts/pr-body N FILE` (edit a
live PR body, refuse queued entries, normalize read-back newlines; `--dry-run` previews without
editing), `scripts/gh-cost -- <command>` (the GraphQL points a command spends; cadence.md),
`scripts/post-status` (a series post's status block; queue.md *Series posts*), `scripts/precheck`,
`scripts/rust-check` (a Rust diff's clippy and rustfmt on one platform, run where `build.<platform>`
says, `--ci` on the fork's GitHub Actions, recorded for precheck; CI compiles no Rust before the
merge; queue.md *Where builds run*), `scripts/review-stamp`, `scripts/changelog-to-unreleased`,
`scripts/models-json decode|encode` (main's encoded `models.json` to plain JSON and back, for a
generated-file conflict the generator cannot redo; queue.md *When `advance` stops on a conflict*),
`scripts/quiet-refs` (after a rebase by hand: replayed messages name PRs as `PR N`),
`scripts/hooks/install` (the commit-msg hook doing that for new commits, per clone),
`scripts/compose-shots`, `scripts/pr-images` (upload PR body images, loops and videos through the
browser relay, or `images.upload`'s fallback), `charts/run.mjs` and `charts/cold-read.py` (body
charts and drawn figures: draft, page check, upload, verify; cold read), `charts/loop.py` (GIF
loops cut from a recording). Tests: `python3 -m unittest discover -s tests`.
