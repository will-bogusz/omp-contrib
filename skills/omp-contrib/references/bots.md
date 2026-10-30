# roboomp and Codex on can1357/oh-my-pi

Measured 2026-09-28 from the corpus (883 merged external PRs, 2026-08-08..09-28; 1,000 issues,
2026-08-30..09-20; 350 review threads on 80 PRs). Mechanism is from roboomp's source at
`python/robomp/` on `origin/main`. Re-read the source when behavior seems off: it changes.

## Triggers

| | roboomp (`roboomp`, Can's bot) | Codex (`chatgpt-codex-connector`) |
|---|---|---|
| Contributor PR | One review per PR number, ever: the first `opened`, `reopened` or `ready_for_review` of a non-draft PR that passes the rate limit. Drafts are skipped (`github_events.py` `_pr_review_pr`); a PR with a submitted review is skipped forever (`tasks.py` `review_pr`). | When its plans have usage (see Availability): its own footer (#14345, 2026-10-09) lists a PR opened for review, a draft marked ready, and `@codex review`. Never request a pass with `@codex review`: it is the maintainers' bot, and an unasked pass spends their usage. |
| Re-review | Never on contributor PRs, including after close/reopen or draft -> ready. Comments there are ignored ("incoming PR comments ignored"); 49 `@roboomp` mentions got 0 re-reviews (e.g. #7197). A new rank needs a new PR number. | Every push: its Codex Review Summary comment (one per PR, edited in place) lists trigger "New commits" and shows the latest pass's status (`Running` / `Completed` / `Failed`) and commit. **👀 on the PR body is the pass in progress**: Codex adds it when a pass starts and removes it when the pass ends (2026-10-18: #15184 and #15175 got 👀 at 00:34:48-49, 3 s after their rows turned `Running`; their passes ended with reviews at 00:43:05 and 00:46:14, and 👀 was gone at the next minute's poll; none of the other 14 PRs polled had 👀 while their rows read `Completed`). #15418's 👀 stayed up for hours after a pass that never ended: a dead pass. |
| Rate limit | Per author per rolling hour, by the author's GitHub `author_association` on the repo (`github_events.py` `rate_limit_cap`, caps in `config.py`): owner, member or collaborator unlimited; `CONTRIBUTOR` (a merged PR already) 10 queued events; everyone else, first-timers included, 3. Events over the cap are skipped and never retried (`server.py`). Draft opens and pushes don't count. Your tier is read from GitHub by `scripts/doctor` and the queue's hourly ready budget, never assumed. | none known |
| Its own PRs | Responds to comments and to Codex findings (Codex comments act as directives there) | Reviews them like any PR |
| Issues | Triage on `opened`/`reopened`: classify, then bug -> ack, repro, fix PR; question/enhancement/proposal -> one comment | none |
| Latency | PR review p50 4 min, p90 25 min. Issue first comment p50 3 min; fix PR p50 12 min (p90 24). | From the summary comments' edit history on a contributor's PRs (2026-09-20..10-18): push to pass start p50 18 s, p90 3.7 min, 97.6% within 30 min (293 passes; the 133 after a force push, whose push time is exact: 97.7%, max 41 min, the late ones in backlog bursts), so no 👀 30 min after a push means that push gets no pass (23 of 138 force pushes on PRs Codex had reviewed got none). Pass start to end p50 9 min, p90 13, p99 16, max 26 (415 passes), so 👀 up past 45 min is a dead pass. Its review lands 1-15 s before the row turns `Completed`. |
| Availability | Down about 2026-09-14..09-19 (205 of about 240 issues untriaged; #12606 reviewed 2 days late) | Intermittent: it posts only when the plans hooked up to it have usage left. Posted "usage limits have been reached" on 175 of 515 September PRs, nothing on 21 PRs opened 2026-10-06..08, then two P2 findings on #14345 on 10-09. Don't wait for a PR's first Codex review; once it has reviewed the PR, each push waits for its review of the new head (workflow step 7). |
| Diff size | none known | A pass on a large diff often ends `Failed` with no result, while smaller PRs in the same hours complete: 2026-10-18 04:20-07:40Z, 50 PRs got passes, 6 failed passes on unrelated PRs were on 1,690-22,041-line diffs (5 of 6 at 3,268+), and one stacked series failed 21 of its other 35 passes at 2,405-10,537 lines while #15176 (1,431 lines) completed 9/9 (from each PR's Codex summary comment edit history). A child stacked on an open parent carries the parent's lines into its diff. A `Failed` pass is no reason to push again: record it and move on. |

## What roboomp's PR review produces

`kickoff_pr_review.md`: one batched `COMMENT` review, never approve or request changes. It
applies `triaged`, a type label, area labels and a rank:

- **P0**: merge at a glance (small root-cause fix with a regression test).
- **P1**: mergeable after a touch.
- **P2**: needs an explicit maintainer call. This covers features and any default-behavior
  change; convention breaches also push toward it.
- **P3**: deprioritize (grab-bag, unconfirmed large implementation, superseded).

Merge rates by rank: P0 76%, P1 62%, P2 15%, P3 11%. The rank forecasts a merge, not a merge
without maintainer work: in the 2026-10-08 round a maintainer pushed fixups onto 10 of 11 merged
P0/P1 PRs from one contributor and sent 6 P0 "lgtm" PRs back with change requests. Inline
findings are tagged blocking, should-fix or nit. The conventions it enforces as findings include
a CHANGELOG entry under `[Unreleased]` in every touched package, prompts only in `.md`, no dynamic
`import()`, Bun APIs over `node:*`, no `mock.module()`, and no default-behavior change without
maintainer sign-off.

## What the bots flag, and how often they are wrong

- The 350-thread sample held 140 roboomp threads (should-fix 77, blocking 20, nit 25) and 210
  Codex threads (P2 144, P1 66).
- Clearly wrong or explicitly declined: about 3-5% overall; about 3 of 22 answered findings
  (about 14%) on one contributor's PRs:
  - #7863 reasoning replay, disproved with a live two-request test;
  - #13527 router gate, disproved live on both paths;
  - #10234 attribution, which raced the amend.
- Commonest roboomp false positive: **missing changelog attribution** when the PR number is
  added right after creation (#10234, #13527, #12523, #11879). Avoid it by opening as a draft and
  marking ready after the attribution push.
- Codex findings are often real edge cases (control characters in JSON-extracted errors, a
  surrogate pair split at a truncation point: #10233). H4vC does not merge past an unresolved
  critical Codex finding (#10919). Can sometimes does (#10233 merged with two unanswered P1s).
- Other contributors' reviews are not a signal: kvnloo called #14751 and #14754 "merge-ready"
  an hour after roboomp; a maintainer sent both back.

## Judging a finding

1. Restate the claim as something testable: the input, the path, and the wrong outcome.
2. Check it against the code at the PR head (a finding may predate an amend), against
   precedent in sibling providers or tools, and against a live run when the claim is
   about external behavior.
3. Valid: fix it with a regression test that fails without the fix, batching every fix of a pass
   into one push (each push reruns CI and wakes another Codex pass). Which Codex findings get a fix
   (every cheap one, P2s included) and when to stop pushing for Codex: workflow step 7.
4. Invalid: keep the code, reply with the evidence, and add a test or a short code comment where
   the suggestion pointed.
5. A review-body sentence that is not a thread ("maintainer context", "behavior note",
   "trade-off", "the live check covered X, not Y") is a finding: settle it with a fix, a test or
   a live run, and answer it in the top-level comment (workflow step 7). A body sentence that
   points at an inline finding ("One should-fix issue, inline: …") or summarizes the review is
   not one; the thread reply answers it. A real choice between two behaviours that roboomp
   leaves for the maintainer gets our answer posted directly, recommendation and evidence first;
   split it into its own PR only when the choice is outside the PR's promise.
6. A code-level finding, from our own reviewer as much as from Codex or roboomp, stands until the
   code or a test that drives its exact condition disproves it. Ordinary live runs that pass (a
   handful) do not disprove a timing or path finding: they seldom hit the window it names. On
   2026-10-18 an independent reviewer of #15195's macOS focus guard found that its AX hit-test
   blocks the switch sampler for up to 0.5 s and that a click is placed after the front process
   is read; both were deferred on 3/3 and 5/5 passing VM runs. #15195 merged with them at 11:52Z,
   Codex posted both as P1s 16 s later, and the maintainer fixed them post-merge in
   `13d09929b7` (clicks placed by a thread of their own, off the sampler; +205/-42 in `skylight.rs`).

## Reply shapes (in the thread)

- Fixed: `Fixed in 84a671a. <root cause in one sentence>. Added <test name> covering <case>.`
- Declined: `Not restoring the gate. I tested both paths live at the current CLI identity
  (3000.11.3) ... The 404 the old comment described came from the old 3000.6.2 identity.` Then
  name the regression test or comment added (#13527).
- Codex finding declined as design-level, or a P2 past the round budget (`Not fixed yet: <fix>`,
  edited to `Fixed in <sha>` or a decline at hand-off): the one-line shapes in workflow step 7,
  then resolve.
- Stale: `Already present on the current head (<sha>). No further change needed.` (#10234)
- Numbered roboomp review: mirror its numbering, one line per item with sha (#13527 changelog thread).

Author replies that land 3-25 min after the review, lead with the resolved state and sha, and
disagree with evidence are the norm among merged PRs.
Resolve each Codex thread right after replying (`resolveReviewThread`; `pr-trace` lists answered
ones as `resolve`): it is a bot thread with nothing left for a person. Leave roboomp threads open
for the maintainer, who reads them as the review of record.

## Issues: what roboomp does with them

`system_append.md` defines the flow:

1. Search for duplicates and already-merged fixes.
2. `classify_issue` with a merit gate. A `bug` needs all five: broken contract, demonstrated
   impact, not a deliberate tradeoff, this repo's defect, true premise.
3. For a bug: ack ("Looking into this, will report back with a repro"), minimal repro, a repro
   comment, the cause, the smallest root-cause diff with a regression test, and a PR whose body
   has `## Repro / ## Cause / ## Fix / ## Verification` and `Fixes #N`.
4. If the repro fails: a "Could not reproduce" comment listing the information it needs; it
   resumes when that arrives.
5. Enhancement or proposal: one comment and no PR (0 of 242) until a maintainer says
   "@roboomp go for it" (#7847) or "fix plz" (#7646).
6. A maintainer's "intended" or "works as designed" stops it immediately.

Gate failures to avoid in our issues:

- Audit-style issues (code-review citations, hypotheticals, open questions, no first-person
  failure).
- Near-identical serial issues from the same author.
- A non-default option in an exotic environment with a one-line workaround.
- Wanting different behavior while titling it a bug.
- Causes in a provider, runtime or terminal.

Effort signals (tables, N-of-N repros, acceptance criteria) do not raise priority.

When roboomp and a contributor both have a PR for one issue, roboomp's wins more often: of 71
issues, only roboomp's PR merged in 30 and only the contributor's in 13. The contributor wins
when verification is visibly stronger: #10262 ("21/21 green") over #10261.
