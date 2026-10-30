# Who decides, and which path to take

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

## Who decides, and what predicts a merge

- **can1357** (the owner) merged 692 of 883 recent external PRs with no comment at all. Merges come in
  silent bursts; between 2026-09-04 and 09-15 nothing merged, then merged 240 in one session.
  Silence is not rejection.
- **H4vC** (collaborator since about 2026-09-03) merged 191, median 6 h after opening, and is the
  only human who reviews and asks for splits. H4vC blocks merges on unresolved bot
  findings (#10919), and since 2026-10-08 sends PRs back with written change requests.
- **roboomp's `review:p0..p3` label is the merge forecast.** For PRs opened 08-08..09-20 the merge
  rates were P0 76%, P1 62%, P2 15%, P3 11%. Any change to default behavior is capped at P2.
  The rank weighs scope discipline and convention adherence heavily
  (`python/robomp/src/prompts/kickoff_pr_review.md`). It does not forecast correctness: six of
  H4vC's seven change requests on 2026-10-08 were on P0 "lgtm" PRs.
- **can1357 salvages the uncontroversial slice personally.** From #13527 can1357 took only the CLI identity
  bump, in his own commit `30f532944f` ("without its Fusion removal or default-model change").
  The same happened to #5096. A bundled default change costs the contributor the credit and the rest of the PR.

## Pick the path

The goal is merged commits under the user's name. Anything with a clear answer becomes our PR; an
issue is only for a problem we can't answer ourselves.
Filing an issue for something we could fix hands the fix, and the commit, to roboomp: #13651 and
#13652 were claimed by roboomp one minute after filing.

| Situation | Path |
|---|---|
| We have a fix, small or narrowly scoped | PR (workflow below). Link the issues it resolves (see *Linking issues*). |
| We have a fix and there is no issue | PR only. **Do not file an issue for it**, before or after. |
| Problem with a clear answer that we haven't patched yet | Patch it, then PR. Don't file an issue. |
| Problem without a clear answer (cause unknown, or the fix is a design choice we can't make) | Issue alone, written so roboomp can reproduce it (see *Issues*). |
| New subsystem, large UI, new dependency, change spanning packages, broad behavior change (`CONTRIBUTING.md` § *Major changes* asks for discussion before the implementation) | Build it and open the PR first, shaped as a series of small chunks (`shaping.md`), each naming its one maintainer decision. Bias towards opening PRs without waiting to hear back from a maintainer. A design conversation, when the user wants one, is about PRs already open and roboomp-reviewed (*Asking a maintainer*, [maintainers.md](maintainers.md)); it never gates opening. A GitHub issue does not count. |
| Default change, opt-in setting, or other narrow behavior change that isn't major in that sense | Build it like any PR, naming the one maintainer decision and our pick. It is P2 by design, so it waits in the queue on the user's approval of that decision unless `autonomy.open_p2 = "open"` (`shaping.md` *Which PRs open on their own*). Once open, the PR carries the decision: our answer to roboomp's maintainer question (workflow step 7) is what the maintainer reads. No separate note to a maintainer (*Asking a maintainer*). |
| We want different behavior, not a fix | Same: a PR that names the behavior change as the one decision. An issue alone waits for a maintainer's "@roboomp go for it". |

Filing an issue for work that already has a PR invites roboomp to write a competing PR within
about 20 minutes, and roboomp's PR usually wins. Issue #11048 said "Proposed fix: #11047" (a
P0-ranked PR). roboomp opened #11051 17 min later, H4vC merged it, and #11047 was closed
unmerged. #10352 went the same way. CONTRIBUTING has said "do not create an issue for it first"
since 2026-07-23. Opening an issue after the PR is reviewed loses the same way. Link instead: an existing issue the PR
resolves gets a closing keyword (see *Linking issues*). Never ping a maintainer to get attention
(see *Asking a maintainer*). Filing an issue or posting any comment always needs the user's
approval of its exact text ([issues.md](issues.md)).

Discuss-first evidence: the 12k-line #8577 and 32k-line #11613 were never reviewed. #11956 was
closed in favour of problem-first proposal issues (#11959, #11960), which then sat 15 days with no
maintainer action.
