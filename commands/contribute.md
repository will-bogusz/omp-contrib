---
description: Turn something omp got wrong into a reviewed PR on can1357/oh-my-pi (setup, fix, hunt, status)
argument-hint: "[setup | path/to/session.jsonl | what went wrong]"
---
You are running `/contribute` from the omp-contrib plugin: it turns something oh-my-pi (omp) did wrong into a reviewed, bot-clean PR on can1357/oh-my-pi, opened from the user's fork. The user's arguments are between the markers (empty means none):

<arguments>
$ARGUMENTS
</arguments>

The skill lives at `skill://omp-contrib` (reading it shows its directory as `Skill file:`). Its scripts run as `skill://omp-contrib/scripts/<name>` in bash, or by that directory's path.

## 1. Doctor first

Run `skill://omp-contrib/scripts/doctor --json`. It is local and fast (no GitHub writes). From its report:

- `"configured": false` → run the setup wizard: read `skill://omp-contrib/references/setup.md` and follow it, then continue with the arguments if there were any.
- Arguments are exactly `setup` → the wizard, even when configured (walk what the user wants to change).
- Any check with `"status": "missing"` that the current request needs (e.g. `repo.checkout`, `tools.gh-auth`) → say which, propose its `fix`, and get it resolved before continuing. Others: mention in one line, do not stop.
- `upstream.drift` not ok → upstream's CONTRIBUTING, PR template, AGENTS.md *GitHub*/*Changelog* or roboomp's prompts changed since the skill was checked. Read the changed paths at `origin/main` before writing any body; upstream wins where the skill disagrees. Tell the user once.
- `"reoffer"` non-empty → offer the setup record named by each check's `decision`, once, with its reason.

## 2. Route

Read `skill://omp-contrib` (SKILL.md) before acting on any route below; it routes to the references for each phase.

**Arguments name a subject** (a `.jsonl` path, or a description such as "the edit tool drops tabs"): go to *Fix intake* with it.

**No arguments**: show a status card of at most three lines, then ask.
- Run `skill://omp-contrib/scripts/pr-trace --summary --open --json` and `skill://omp-contrib/scripts/pr-queue plan --json` (neither writes upstream; plan may refresh its cache on the fork's queue branch).
- Line 1: PRs needing the user (rows with `needs_us`), by number and the one thing each needs; or "none".
- Line 2: the queue: how many entries open now, how many wait or are held, and the supervised opens left.
- Line 3: held P2 decisions awaiting the user (`awaiting_user` rows), each with its one decision; omit when none. Add doctor's one-line note here only if something is `missing`.
- Then use the `ask` tool with these options: **Fix something you hit** (then ask what, or for a session path) · **Hunt my recent sessions** · **PR status** (follow the skill's *Resume* phase for the PRs on line 1) · **Other**.

## Fix intake

The subject is either a session transcript or a description.

- A `.jsonl` path: read it with `read` and jq filters, not whole. Start with the user's prompts (`?q=select(.type=="message" and .message.role=="user") | .message.content[0].text&raw=true`), then failing tool calls (`?q=select(.message.role=="toolResult" and .message.isError) | {toolName: .message.toolName, text: .message.content[0].text[0:400]}`), then the assistant turns around the moment things went wrong. The `omp` version is in each line's `runtime.version`.
- A description: ask for the session only if a reproduction needs it; otherwise find the code path from the description.

Then state in two sentences what omp did, what it should have done, and the evidence, and start the skill's *Fixing something omp did wrong* chain:

1. `skill://omp-contrib/scripts/contrib start "<what omp got wrong, in a sentence>"`.
2. Ask the user one question, once, now while they are here (a plain message, not the `ask` tool, so you keep working while they answer): "In a sentence, in your words: what should change, and why does it matter to you? It goes first in the PR, verbatim." When the reply comes, record it exactly as written: `contrib record own-words "<their sentence>"`. If the arguments already carry their answer to that question (for example after "in my words:"), record that sentence instead of asking; their description of the bug is not it. Never write, suggest or polish one for them.
3. Continue with the duplicate scan, before reading code for a fix, and after each step run `contrib next`: it names the next step, its command, and whether it is yours (do it), the user's (ask and stop), or nobody's yet. If the subject turns out to be expected behaviour, a duplicate of an open PR or issue, or not omp's code, end it with `contrib stop <not-a-bug|duplicate|not-omp> --evidence "…"` and say so with the evidence.

## Hunt

Find what went wrong in the user's own recent sessions, so they can pick what to fix.

1. List sessions from the last 14 days: `await archive.sessions(project="*", limit=100)` in eval (titles, recaps), or the newest `*.jsonl` under `~/.omp/agent/sessions/` by modification time. Skip sessions that were themselves contribution work on oh-my-pi PRs.
2. Scan each with jq filters, not full reads. Signals: tool results with `isError`; the same tool retried with small changes; user turns that correct the agent ("no", "that's wrong", "you didn't", "stop"); aborted or timed-out calls; writes to `xd://report_issue`. For more than ~15 sessions, split the scan across a few `scout` subagents, each given a list of files and these signals.
3. Group hits by likely cause in omp (a tool, a prompt, a provider, the TUI), not by session. Drop what is the user's environment, a model's ordinary mistake no omp change would prevent, or third-party code.
4. For each group, check `origin/main` and open PRs/issues for an existing fix (the skill's duplicate scan, read-only).
5. Present the three strongest: what goes wrong, how often and in which sessions, the evidence lines, the likely area, and whether it looks like a fix (P0/P1) or a change of a deliberate default (P2 by design). Let the user pick one. In the same message ask the own-words question for the pick ("In a sentence, in your words: what should change, and why does it matter to you? It goes first in the PR, verbatim."); the pick goes to *Fix intake*, where their answer is recorded as written.

## Limits

Nothing addressed to a human (maintainer, issue, discussion) posts without the user's approval of its exact text. PRs open only through `pr-queue open`, under the opening policy and supervised start the skill states. If the request fits none of the routes above, follow the skill.
