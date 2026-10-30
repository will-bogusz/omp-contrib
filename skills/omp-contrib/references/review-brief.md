# Reviewer brief: the independent "what did `main` do" review

Part of the `omp-contrib` skill. Workflow step 3 spawns omp's bundled `reviewer` agent with this
file as its brief (pinned to `@slow`; the plugin's reviewer-family extension moves it to a model of
another family when `@slow` is the session's own, or `models.reviewer` is set). The task adds the PR, the worktree and the worker's
report. Read `skill://omp-contrib` for the repo's conventions; the brief below is what the
reviewer acts on.

## Goal
The one independent review of one of our PRs to can1357/oh-my-pi, before it opens. Decide whether
the head is ready to push, and find what a maintainer (`github.maintainers`) would still send back
or fix themselves. **This is the only review round**: the worker fixes your findings without
another review, so report everything you find in this pass, each with the concrete fix and the
test that should prove it.

## What to review
The worktree's `HEAD` versus `origin/main` (`git diff origin/main...HEAD`) and the worker's report.
Read-only: do not edit, commit, push or comment anywhere. Revert temporarily only through a saved
patch in scratch, never `git stash`.

## Criteria (check each; this is not "is the fix sound")
1. What did `main` do? For every function or contract the diff touches, list callers and
   neighbouring paths: other providers, other credential or pin kinds, retry and failure branches,
   concurrent sessions or processes, the window between a value's capture and its use, consumers of
   a changed exit code, payload or log. For each, state what `origin/main` does and whether the head
   keeps it. Flag any outcome changed beyond what the PR title promises.
2. Persisted state: if the diff adds or changes a saved session entry, custom entry or record, what
   happens to it on rewind, branching (`branchWithSummary`), forking, compaction, tree navigation and
   resume? An entry that stays on the old branch while the reply it describes moves is the miss the
   maintainer fixed on #14754 (`6a5629ed5a`).
3. Hot paths: a new scan over session history, branch entries or the message list on every model
   call, render or event is a finding unless it is bounded or incremental (`6a5629ed5a` replaced a
   per-call reverse scan with an incremental one).
4. Model and provider policy: a number, list or rule true for one model family or provider belongs in
   the catalog's KDL rules, scoped to the class it holds for (AGENTS.md, "Model/Provider Policy
   Lives in KDL"), not a TS constant or an id string match. #14751's `CACHE_LOOKBACK_POSITIONS = 20`
   applied to every model; the maintainer replaced it with a `prompt-cache-lookback` axis
   (`1111b1fc03`).
5. Trust boundaries: a guard built only from values the same untrusted source supplies is no guard
   (#14544 checked a peer-supplied file name against a peer-supplied id, twice). Name the source of
   every value that reaches a filesystem, process or network operation.
6. Every claim about an outside service's behaviour (API counting rules, token semantics, CLI exit
   codes) is backed by vendor docs or a live probe; check the citation.
7. Tests: each behaviour fix has a test that fails with the fix reverted (re-run that check where
   cheap); no full-string assertions unless bytes are the contract; no ambient env leakage; every
   `test.each` row is a distinct case; fixtures match the scenario; no test passes or fails by how
   fast the machine runs (sleeps, clock reads, elapsed-time bounds, timer races): fake timers or an
   injected clock, and await the event itself.
8. CHANGELOG: each entry of this PR sits under `## [Unreleased]` after merging `origin/main`, brief
   and user-facing. Docs that state a changed contract are updated.
9. Model-visible text: a settings, env or request value the diff renders into a prompt template,
   tool description, system block or anything else sent to the model provider must carry no
   credential (URL userinfo or token query, key, header, cookie): name each such value and whether
   it is redacted. #16390 rendered `browser.cdpUrl` verbatim into the relay guidance block; the
   maintainer wrapped it in `redactUrlForLog` (`914654c252`).
10. Platforms: CI runs nothing on our PRs before the merge and no tests on Windows or macOS. For
   Rust, name the platforms whose code the diff compiles differently (paths under `macos/`,
   `linux/`, `win32/`, `cfg(target_os …)` lines) and check `rust-check` is recorded for each
   (precheck's `rust` FIX), or the platform is placed `none` and the PR's Testing section says
   so; a closure or binding that shadows a name only one platform's module has is #16202's
   Wayland E0618 (`bf9fd4bd6a`). A test asserting filesystem or process semantics
   (concurrent delete, locks, permissions, signals, symlinks) is gated to the platforms whose
   semantics it asserts or holds on Windows too (#16433, `9b481c53bd`).
11. Run `python3 <skill dir>/scripts/precheck --no-siblings` in the worktree (the skill dir is
   the directory holding the `omp-contrib` skill's `SKILL.md`) and judge each FIX and NOTE. Run
   the targeted test files yourself.

## Report
Verdict (`ready` / `needs-changes`), then findings each with location, trigger, impact, the
concrete fix and the test that proves it, ordered by severity. Be specific; no generic advice.
