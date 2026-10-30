# Pre-submit checklist

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

- [ ] Duplicate scan run (open and recently merged PRs and issues, plus `origin/main`) and recorded; nothing duplicates this.
- [ ] Path chosen by the table; no issue filed for this fix; `closingIssuesReferences` lists exactly the issues this PR resolves (*Linking issues*).
- [ ] One logical change; no default-behavior change bundled with a fix; overlap with our other open PRs shaped by *Overlapping work* (separate, queued behind what it needs, or combined); no merge-order line in the body.
- [ ] A change that is P2 by design is queued with its one maintainer decision (`pr-queue add --p2-decision`), and under `autonomy.open_p2 = "hold"` the user has approved it (`pr-queue approve`; queue.md, *P2 decisions*).
- [ ] Title is a Conventional Commit describing what the user observed or can now do.
- [ ] Diff self-reviewed and exercised live; the own-words line, in the user's own words (asked from them, never written for them), is first under `## What`.
- [ ] The one independent "what did `main` do" review run by omp's `reviewer` agent (workflow step 3, [review-brief.md](review-brief.md)) and stamped (`../scripts/review-stamp`); its `resolvedModel` compared with the session's family, and Testing says "same-family review" when they match; each finding fixed (behaviour fixes with a test that fails on revert) or answered, without a second round.
- [ ] Body opens with the user-visible problem in omp terms; primer only if needed; decisions,
      maintenance cost and non-goals stated; reading order for large diffs.
- [ ] Testing names the scenario exercised live and its result, plus the command and a negative control.
      A change that can move what agents do (prompt or tool-description text, a tool's arguments,
      results or errors, a new helper the model calls, as with browser and computer use) gets a
      sample set run on `main` and the branch with the two models of different families in
      `models.behaviour`, scored from transcripts (precheck `behavior` NOTE).
- [ ] Code checked against *Write the code the way the maintainers do*: nothing beyond the
      title, no side-channel state, stored state no larger than its readers use, error causes the
      failing signal shows and an arm for each input a message was not written for, comments sized
      to their neighbours with no provenance, a test that fails without the fix and none that only
      restates a hand-off to native or a required-names list, no test that depends on wall-clock
      time, no churn.
- [ ] `../scripts/precheck` prints no FIX (CHANGELOG placement after merging `origin/main`
      included, no other open PR's commits or code conflict with an open ready PR of ours,
      shaping.md, and a `rust-check` recorded for every platform a Rust diff builds on); each NOTE
      (casts, test shapes, signatures, docs, unclosed issue mentions, removed calls, out-of-scope
      commits, tests on script text, field readers missing a new field, credential-shaped values
      rendered into a prompt, a platform placed `none`) decided.
- [ ] The sentence after the own-words line gives the headline number as before → after. Each idea
      takes the one form framing.md *Visuals* picks for it (drawn, never Mermaid), and no number
      is drawn twice. Composites (`../scripts/compose-shots`) checked with `read`; a chart or
      figure passed its cold read in both layouts, independent review, and `run.mjs`'s page check
      at 1280, 1100, 430 and 390 px (`charts.md`); a loop from `../charts/loop.py`, placed with
      `pr-images --loop`, and no video in view (`charts.md`, *Motion*); images the user supplied
      preserved.
- [ ] Under 3,000 characters outside tables, `<details>`, images and the checklist; no private context.
- [ ] CHANGELOG line in every touched package with PR-link attribution, under `[Unreleased]` once
      `main` is merged in, unless it fixes a regression no release shipped (changelog.md);
      checklist ticks only what ran.
- [ ] **CI never runs on our PRs before the merge**: every fork run waits for maintainer approval
      (`action_required`), and CI's Rust jobs run on `main` only, so the maintainer's merge is the
      first build. This list stands in for `.github/workflows/ci.yml`'s jobs:
      `bun run check:ts` at the repo root (`check`: `ci:check:full`, i.e. oxlint, oxfmt and every
      package's type check; per-package `bun check` misses packages that type-check another
      package's sources, as `metaharness` failed #11613); the focused `bun test` files of each
      touched package (CI's `ci:test:*` shards, Linux only); a Cargo.toml or Cargo.lock change also
      `bun scripts/gen-bazel-lock.ts --check` (`bazel_lock`) and `cargo deny --locked check licenses
      sources`; a Rust change `../scripts/rust-check` on every platform precheck names, run where
      `build.<platform>` places it (`rust` FIX: Linux always, macOS or Windows for code gated on
      them; clippy `--all-targets` and rustfmt, as `rust_validate` and the maintainer's build run
      them; a platform placed `none` is named in Testing as unchecked) and `cargo test` of each
      touched crate (queue.md, *Where builds run*).
- [ ] No CI job runs tests on Windows or macOS, and the maintainer runs them on Windows: a test of
      filesystem or process semantics (concurrent delete or rename, open-file locks, permissions,
      signals, symlinks, path separators) holds only where it ran. Gate it to the platforms whose
      semantics it asserts (`#[cfg(unix)]`, `it.skipIf(process.platform === "win32")`) or make it
      hold there: #16433's concurrent `rm -f` test failed on Windows, where a file another process
      is deleting reads as access denied (`9b481c53bd`).
- [ ] The merged tree with every open ready PR in a crate or package this one changes is built and
      tested and recorded (`pr-queue tree --record`; *Opening* in queue.md): #15761 and #15762 each merged
      cleanly and passed alone, and failed to compile together.
- [ ] During the supervised start (`autonomy.supervised_opens` above zero), the user gave an
      explicit OK on the body, the diff summary and the own-words sentence before `open`
      (queue.md, *Supervised start*).
- [ ] Queued with `pr-queue add`, opened with `pr-queue open` (draft, CHANGELOG link, precheck, ready), body read back.
- [ ] No `@codex` or review request anywhere on the PR, and no maintainer mention in the body;
      a question for a maintainer is a separate thread comment whose exact text the user approved
      (*Asking a maintainer*).
- [ ] After the bots: every roboomp thread has a reply in its thread; a top-level comment, only
      if something qualifies, answers roboomp's maintainer question and body-only findings; Codex
      is at a stop point, clean, settled or past its round budget (workflow step 7).
- [ ] At hand-off (the PR goes to a maintainer, or a maintainer has it): `pr-trace --summary N`
      lists no `hand-off` or `pre-hand-off` item; every finding the budget skipped is fixed with a
      test, disproved or declined in our words, and its reply edited, as is any comment of ours
      that leaves work to the maintainer (workflow step 7).
