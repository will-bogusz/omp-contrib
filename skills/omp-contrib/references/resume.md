# Resume a PR opened in an earlier session

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

A session usually closes once its main goal is done; the PRs it opened keep going. When the user
asks a fresh session about hanging PRs (or picks *PR status* in `/contribute`), rebuild the
context from local state. Nothing has to be carried forward by hand: branch name, PR URL and
worktree path tie each PR to the transcripts that made it.

1. **Trace.** Start with `../scripts/pr-trace --summary --open --fetch`: one line per open PR,
   the ones that need us first (change requests, bot threads, real conflicts),
   then every PR merged in the last two days with the commits a maintainer added before merging.
   It selects by activity, never by when a PR was opened. Then `../scripts/pr-trace N …` for the
   detail on each PR you act on, and `../scripts/pr-trace --issues` for the open issues the user
   filed. `--fetch` only updates remote-tracking refs, so it is fine in a look-only request. Per
   PR the detail prints the rank,
   bot threads waiting on us, a real-conflict check, `rule:` lines for breaks of the open-PR rule,
   worktree, scratch dirs, what a draft waits on, the session (and subagent) that opened it, the
   other sessions most involved, and a suggested next step. It finds worktrees through `git
   worktree list`, because older branches need not follow the `<github.branch_prefix><topic>` ↔
   `<paths.worktrees>/<topic>` convention, and scratch dirs (under `paths.scratch_roots`, when
   set) by name or by a file naming the PR. Queued work that is not open yet:
   `../scripts/pr-queue show` and `plan` ([queue.md](queue.md)); held P2 decisions waiting on the
   user show there as `held` (`user decision pending: …`), under `Awaiting your decision`.
2. **Rebuild intent, cheapest source first.** The subagent `report` (.md) when listed (it flags
   commits that landed after it); then omp's session archive in Eval (`archive.session("<id>")`)
   for that session's recaps and the user's prompts; then the PR body, reviews and comments. Only
   then read the transcript (`~/.omp/agent/sessions/**/*.jsonl`), at targeted spots: `grep` for
   the branch name, or `read` the file with a jq filter, and read around the newest hits, which
   hold the latest state. Transcripts run to tens of MB; never read one whole.
3. **Check local state.** `git -C <worktree> status` and
   `git -C <worktree> log <github.fork_remote>/<branch>..` for uncommitted or unpushed work; the
   scratch dir holds fixtures and evidence. With no worktree, add one from
   `<github.fork_remote>/<branch>`.
4. **Act on today's state.** A plan found in a transcript is context, not an instruction: confirm
   it still applies (it may be done or superseded) before acting. Then follow the next-step line:
   a `CHANGES` line goes through *Maintainer change request* (`workflow.md`), a `changelog` drift
   line through *Cadence*, a `roboomp note:` gets settled as in Workflow step 7, and the rest
   follows Workflow steps 6–8. A P2 whose maintainer question has our answer posted is waiting
   on a maintainer round: report it as waiting, its decision in a line, not as a decision for
   the user or a note to a maintainer (*Asking a maintainer*). `pr-trace` shows what a maintainer
   was already asked on each PR and whether they answered.
5. **Report per PR**: what it does in user terms, where it stands, what you did, what needs the
   user.

Transcripts hold private context: nothing from them goes into PR text unless it passes
*Keep private context out*.
