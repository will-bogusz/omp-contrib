# Asking a maintainer

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

The maintainers (`github.maintainers`) merge in rounds and read PRs, not messages. A maintainer's
attention is the scarcest thing in the flow: PRs that are easy to merge earn a quick round, and a
stream of questions spends that goodwill. So a message to a maintainer is never the default end
state of a PR or a report:

- **A PR-carried decision rides on the PR.** A P2's body names the one maintainer decision with
  our pick, and our answer to roboomp's maintainer question (workflow step 7) carries the
  recommendation and evidence. That is where the maintainer sees it. Report such a PR to the user
  as waiting on a maintainer round, not as a decision for them, and draft nothing for the
  maintainer.
- **Answer it yourself first.** Anything the code, the history (`git log -S`, `git blame`, earlier
  PRs and their reviews) or a run can answer never goes to a maintainer.
- **Draft a message only when the user asks for one, or when the tag test below holds.** In the
  second case, offer it in the report as an option with the draft attached ("one tag could
  unblock #A-#D; draft below if you want it"), not as a decision the user has to make.

**Approval of the exact text.** Every message to a maintainer goes out only after the user
approves its exact text. Two kinds post directly: a factual "Fixed in <sha>" reply to a change
request the maintainer wrote on our PR (*Maintainer change request* in `workflow.md`), and our
answer to a question roboomp raised for the maintainer (workflow step 7).

A PR a message sends to a maintainer is handed off: before it goes, clear its `pre-hand-off`
items (`../scripts/pr-trace --summary N …`; workflow step 7, *At hand-off*), so every Codex
finding the round budget skipped is fixed by us and no comment of ours leaves work to the
maintainer.

## The tag test

A tag passes only if all three hold: it costs the maintainer seconds, they can answer it cold from
the note, and the answer unblocks or redirects several PRs (is X intentional? A or B for this
contract?). One P2's own decision fails the third: its PR already asks it.

Design direction (the change reshapes how a feature works, or the right approach is still open)
is a conversation the user drives with the maintainers, about PRs already open and
roboomp-reviewed (*Pick the path*: open first, never wait on this conversation). Never post an
async "what do you think?". If the user has another channel to the maintainers, they use it
themselves; the agent drafts only for GitHub.

## The note

Write it the way we write PR bodies: the maintainer should be able to answer from the note alone,
and the user, if they haven't been following, should be able to read it and recall what's going
on. About five plain lines, no headings: what the PR or series does for users; where it stands
(rank, what has merged, what waits); the question, answerable in a word; the options with our pick
and why; what each answer unblocks. Link the PRs. When roboomp raised the question, quote the
relevant sentence or two of its comment inline (a `>` blockquote) instead of linking it: a comment
link doesn't render as anything readable on GitHub.

**Where on GitHub.** A top-level comment in the PR's main thread, the newest thing at the bottom,
where a maintainer looks first. Never in the PR body (it notifies them on open, before any question
exists), and never inside an inline roboomp or Codex thread, where it gets lost. A question
spanning a series goes on its first open PR and links the rest.

**Tracking.** `../scripts/pr-trace` lists each comment of ours that tags a maintainer and whether a
maintainer has replied since. Never ask again while one is unanswered; act on an answer as soon
as it appears, and carry its lesson into the related PRs. Conversations outside GitHub are
invisible to us: before drafting another message, ask the user what was sent and what came back.

**Report to the user.** When they asked for a message, or a tag passes the test above: an
executive summary they can read cold. Per series, a few lines: what it is in user terms, its PRs
and ranks, the question, and why now (everything clean and bot-handled, one answer unblocks N
PRs), with the drafted note below it.
