# Linking issues, and filing issues

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

## Linking issues

A PR closes an issue on merge only through a closing keyword in its body; a bare `#N` mention
links nothing. can1357 merges silently, so an issue left unlinked stays open after its fix ships.

- **Find them.** Search open issues by the user-visible symptom and the component, not only by
  our root cause: `gh issue list -R can1357/oh-my-pi --state open --search '<symptom> <provider>'`.
  Also read the issues cited by the PRs and issues we touched, and the open issues on any PR
  this one supersedes.
- **Fixes or relates, per issue.** Use `Fixes #N` only when, after merge, nothing the issue asks
  for remains. A partial fix, a precursor, or a request another PR implements gets a plain
  mention under *Why* (`Related: #N, which <PR> implements`). #13677 makes stored legacy Windsurf
  keys work, but #13116 asks for the Windsurf login itself (another contributor's #13288); `Fixes #13116` there
  would close that request before the login exists. An ask triage already declined (a `wontfix`
  label, a roboomp rejection) doesn't count as remaining: close the issue and say in the body
  that the declined part is left out on purpose (#14410 for #13524, whose `waitUntil` default
  flip was declined).
- **Our own issues.** A merged PR that only says `Refs #N`, or a triage `duplicate` label, leaves
  an issue you filed open. `../scripts/pr-trace --issues` lists both; close the duplicates, and
  after a Refs-only merge check what remains before closing.
- **Syntax.** One keyword per issue, in the body: `Fixes #10, fixes #12` (GitHub's docs require
  the full syntax for each issue). Keywords: close(s/d), fix(es/ed), resolve(s/d). They act only
  when the PR merges into the default branch, `main`.
- **Verify.** After publishing and after every body edit, `gh pr view N --json
  closingIssuesReferences --jq '[.closingIssuesReferences[].number]'` must equal the set meant
  to close; it is what the sidebar's *Development* link shows.

## Issues: a problem we have not patched

roboomp triages new issues in about 3 min and opens a fix PR in about 12 min for issues it
classifies `bug`; about 76% of prioritized bugs end in a merged fix. Classification is the gate,
and it follows the bug merit gate in `python/robomp/src/prompts/system_append.md`: broken
contract, demonstrated impact on real work, not a deliberate tradeoff, this repo's defect, true
premise.

- Use the bug template: what happened in first person during real work, minimal steps (a
  command or script with no private data), expected, observed, verbatim error output, `omp
  --version`, `bun --version`, platform. Issues with a repro heading were classified `bug` 69% of
  the time; without one, 19%. #13229 (minimal repro, then a suggested fix) got a fix merged 73
  min after filing.
- A suggested fix may follow the failure; never lead with it. Proposal framing gets classified
  enhancement, and roboomp does not implement enhancements (0 of 242) without a maintainer "go".
- One real failure per issue. roboomp rejects audit-style issues and "near-identical same-author
  (serial bodies)" as batch issues. It reads tables, line-cited evidence and N-of-N repro counts
  as effort, not severity. Several related gaps each need their own first-person scenario, not a
  shared template.
- Filing an issue needs the user's approval of its exact text (upstream `AGENTS.md` § *GitHub*).
  So does every comment: on an issue, on a PR, or to roboomp. Draft it, show it, post only what
  they approved.
- If roboomp posts "Could not reproduce", answer its "Information needed" list. It resumes from
  that context. If its fix PR stalls, comment on the roboomp PR (it acts on its own PRs), with a
  narrow ask (#10636), once the user approves the comment's text.
