# Scan for duplicates before doing anything

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

Before writing a fix, drafting a body, or planning an issue, check whether the work already exists
upstream. OMP moves fast: roboomp opens fix PRs about 12 min after a bug issue, and other
contributors often hit the same bug the same week. A duplicate costs the commit and the review.

- **Search open PRs and open issues**, by the user-visible symptom, the component or provider, and
  our root-cause terms: `gh pr list -R can1357/oh-my-pi --state open --search '<terms>'` and
  `gh issue list -R can1357/oh-my-pi --state open --search '<terms>'`. Try two or three phrasings;
  roboomp titles name the root cause, user issues name the symptom.
- **Search recently merged and closed ones too** (`--state all`, or `--search '<terms> is:merged'`)
  and check `origin/main` itself: `git log origin/main --oneline -i --grep '<term>'` plus the
  `[Unreleased]` CHANGELOG sections. A fix merged yesterday is not on our checkout.
- **Act on what you find:**

  | Found | Do |
  |---|---|
  | Merged fix on `main` | Drop ours; verify on `main` that it covers our case. |
  | Open PR (roboomp's or a contributor's) for the same change | Don't open a competing copy. If the author is active and the PR is correct, verify it and say so in the report to the user with our evidence; a note to a maintainer vouching for it is drafted only if the user asks, and posted only once they approve its exact text (*Asking a maintainer*). If it has stalled or needs real rework, take it over: carry the author's commits, credit them (`Co-authored-by`, *CHANGELOG and attribution*), and make ours visibly stronger (#10262 over #10261). |
  | Open issue, no PR | Our PR links it with a closing keyword (*Linking issues*). |
  | Related but different work | Keep ours narrow and mention it under *Why*. |

- **Record the scan** (queries run, hits, verdict) in the task report, so the user can see a duplicate
  was ruled out rather than missed.
