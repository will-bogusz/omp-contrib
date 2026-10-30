# CHANGELOG and attribution

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

- Each touched package's `packages/<pkg>/CHANGELOG.md`, under `## [Unreleased]`, in the right
  `### Added|Changed|Fixed|Removed|Breaking Changes` section. One line that leads with what the
  user sees and names every surface or platform affected (`9b1a2f244c` widened ours from macOS to
  all three), without mechanism or API lists. Maintainer entries run a median 20 (can1357) to 31
  (H4vC) words; ours on open PRs ran 39, and changelog fixes are the most common maintainer
  fixup (36 of 154). roboomp checks this in every touched package. A PR gets one line per outcome
  a user notices, not per fix commit, written to the reader ("your app", "you"): the maintainer condensed
  #15184's 16 lines to 7 before merging (`78bf1669cc`), folding sheets, popovers, Finder and
  Open/Save panels into one "landing in the wrong place" line and dropping the mechanism. The line
  states the behaviour, not that a prompt or doc now describes it: #15176's "the `computer` tool
  prompt now says physical Escape stops only takeover input" became "Pressing Escape in your own
  app no longer stops the `computer` tool's background window input unless task control is held"
  (`ff6025abdb`).
- A line records what changed for someone running the last release when the PR merges, so a fix
  of a regression no release shipped gets none: check with `git tag --contains <the commit that
  broke it>`. The maintainer dropped #15941's line (sleep prevention broken by #14591 after v18.11.1,
  `7c9d457d70`), as they dropped others' lines for a reverted change, a no-op refactor and a
  test-only change (`ee32629108`, `904d0613b4`, `3f7276200a`). `../scripts/precheck` names the
  unreleased commits whose lines the diff rewrites and then reports a missing entry as a NOTE, not
  a FIX. The check holds until merge: a release cut while the PR is open ships the regression,
  and the entry is due. #16038 went without one for #15947's `8fbaf75aa2`, v18.11.3 shipped that
  commit 17 minutes after it opened, and the maintainer added the line before merging (`e2b974e459`).
  `../scripts/pr-trace` flags such a PR (`changelog: regression shipped in vX`); add the entry in
  one push.
- External attribution, added once GitHub assigns the number (`pr-queue open` does it, workflow step 5):
  `Fixed foo ([#N](https://github.com/can1357/oh-my-pi/pull/N) by [@<fork_owner>](https://github.com/<fork_owner>))`,
  where `<fork_owner>` is your GitHub login (`github.fork_owner` in [config.md](config.md)).
- Placement is judged on the merged result, where the maintainer reads it: `merge=union` keeps
  our line next to its old context, so after a release cut on `main` it lands under the released
  heading. `../scripts/precheck` simulates the merge and flags that; when and how to fix it is
  *Cadence*: while the bot rounds are open only in a push we need anyway, and once they settle in
  one CHANGELOG-only push per release (`pr-queue advance '#N'`; adopted after the maintainer's 27
  CHANGELOG commits on 20 of one contributor's 78 merges 10-18..20). Released sections are immutable. A `###`
  heading the merge repeats inside Unreleased is no reason to push: `bun run release` runs
  `fix-changelogs`, which merges duplicate category headings and normalizes section order
  (AGENTS.md *Changelog*; on 2026-10-29 five PRs took a second push for it alone after the maintainer
  restructured Unreleased, each restarting Codex).
- A signature change that breaks callers of exported package API (a parameter inserted in
  front, a type narrowed, a parameter removed) gets a `### Breaking Changes` line in that
  package naming old and new forms: the maintainer added one to #14761 for `notifyUsageStale(signal?)` ->
  `(provider?, signal?)` (`ce04d87bf0`). An optional parameter appended at the end does not.
  precheck NOTEs every changed parameter list so the call is made.
- Folding in someone else's work: a `Co-authored-by:` trailer plus a mention in the body.
  Credit only what the PR actually carries: a fork that only inspired the work gets no credit.
