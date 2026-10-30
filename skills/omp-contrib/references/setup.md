# Setup: the wizard

Part of the `omp-contrib` skill. `/contribute` sends you here when `scripts/doctor --json` reports
`"configured": false`, when the user runs `/contribute setup`, and when doctor flags a check with
`"reoffer": true`. Keys and defaults: [config.md](config.md).

## How to run it

The user is setting up a tool that will act on GitHub in their name. The aim is a machine set up
the way the flow works best, with every compromise chosen knowingly; not a fast pass through
defaults.

1. Run `scripts/doctor --json` (add `--probe-hosts` before the build-hosts record). Each check
   names its `decision`; walk only records with no `[choices.<id>]` yet, a check that is not `ok`,
   or `reoffer: true`. A rerun of `/contribute setup` with everything recorded asks which record
   the user wants to change.
2. Walk the records below in order (later ones depend on earlier: `ci` builds need the fork). For
   each: say in a sentence what it protects, state what the probe found, recommend the best
   option this machine supports **with its reason and the cost of each lower option**, and let
   the user tweak. Group records whose probes all came back ideal into one confirmation; spend
   the user's attention on the ones that need a choice.
3. Write each outcome with `omp_config.set_value` (from `scripts/`: `python3 -c 'import
   omp_config; omp_config.set_value("build", "linux", "ci")'`) or by editing the file: the values,
   then `[choices.<id>]` with `value`, `reason` (the user's reason, or the probe fact that made the
   recommendation stick), `at` (today). Set `reoffer = false` when the user says the choice holds
   regardless; otherwise doctor re-offers the ideal once it becomes available, and never re-asks
   while the recorded reason still holds.
4. Commands that change the machine outside the config (installs, `gh repo fork`, `omp config
   set`, unit files) run only after the user approves them; show the exact command first. doctor
   never installs packages itself: its `fix` field is a proposal. Safe local repairs go through
   `scripts/doctor --fix <hook|fork|queue-branch|omp-settings>`, which prints each step
   (`--dry-run` to preview).
5. Rerun `scripts/doctor` and resolve or explain every remaining `missing`.
6. Finish with a dry-run first hunt (*Dry run* below).

`/contribute` without arguments never re-runs the wizard on its own: an undecided record shows
as one line in the status card.

## Decision records

Each: **Intent** (what it protects) · **Ideal** · **Probe** (doctor check ids) · **Alternatives**
(ranked, with cost) · **Ask** · **Re-offer when**.

### github: identity, fork, remotes, hook

- **Intent.** PRs come from the user's fork; the queue lives on a branch of that fork, so every
  machine of theirs sees the same queue; the hook keeps commits pushed to the fork from naming
  `#N`, which would put a cross-reference on upstream PR N's timeline that the maintainer sees.
- **Ideal.** `gh` logged in as the user; an oh-my-pi clone with `origin` = upstream and a
  `fork` remote; the queue branch (`github.queue_branch`) on the fork; the commit-msg hook linked
  into the clone. Branches are named `<branch_prefix><topic>`, default `<login>/`.
- **Probe.** `tools.gh-auth`, `repo.checkout`, `repo.origin`, `repo.fork`, `repo.queue-branch`,
  `repo.hook`, `github.tier` (roboomp's per-hour review cap for this login; first-time
  contributors get the smallest, so the queue's ready budget is smaller until a PR merges).
- **Alternatives.** None for gh and the fork: the flow needs them. Checkout location is free
  (`paths.checkout`; worktrees at `paths.worktrees`, default `<checkout>-wt`). Without the hook:
  every commit message has to be written with `PR N`, by hand; `scripts/quiet-refs` repairs after
  the fact, but a push before that leaves the timeline entry.
- **Ask.** Confirm the login and branch prefix; where the clone lives (offer `gh repo clone
  can1357/oh-my-pi` when there is none); then `doctor --fix fork`, `doctor --fix hook`. The
  queue branch is created by the first `pr-queue add`, or now by `doctor --fix queue-branch`.
- **Re-offer when.** gh's login changes, the fork remote disappears, or another tool replaced the
  hook.

### build-hosts: where Rust and merged-tree builds run

- **Intent.** Upstream CI compiles no Rust on a fork PR before it merges, so a Rust diff that
  breaks another platform is found by the maintainer's build. `scripts/precheck` asks for a
  `rust-check` record per platform the diff builds differently on; a merged-tree build of each
  queue round catches PRs that pass alone and break together.
- **Ideal.** Each of `build.linux`, `build.macos`, `build.windows` set to `local` (this machine's
  own OS; Windows also from Linux or macOS through cargo-xwin and the
  `x86_64-pc-windows-msvc` target) or `ssh:<host>` (a reachable host of that OS, from
  `~/.ssh/config`), so the check runs before the PR opens.
- **Probe.** `system` (RAM, cores), `tools.rust`, `hosts.ssh` (with `--probe-hosts`: reachability
  and OS per host), `build.<platform>` (each row carries `recommended`).
- **Alternatives**, best first: `local` → `ssh:<host>` (the agent runs `rust-check` there and
  imports its record; costs a host the user keeps reachable with the toolchain) → `ci`
  (`rust-check --ci` pushes a temporary branch to the fork and runs GitHub Actions there; costs
  15–60 minutes per check and needs Actions enabled on the fork; untested platforms otherwise
  look the same) → `none` (precheck prints a NOTE instead of blocking, and the PR's Testing
  section says that platform is unchecked; the maintainer's build is then the first one).
  Under ~24 GB RAM, recommend an ssh host for merged-tree builds, or a low
  `task.maxConcurrency` during queue rounds: parallel workers plus a full build have run a
  machine out of memory.
- **Ask.** Show doctor's `recommended` per platform with the reason; for cargo-xwin, propose
  `cargo install --locked cargo-xwin && rustup target add x86_64-pc-windows-msvc`. Record why a
  platform is `none` (e.g. "no Windows users affected by my changes so far").
- **Re-offer when.** doctor's `recommended` beats the recorded value (a new ssh host of that OS,
  cargo-xwin installed) and the choice did not say `reoffer = false`.

### reviewer: model family of the independent review

- **Intent.** One independent review per PR, before roboomp sees it once ever. A reviewer from
  the author's model lineage shares its blind spots; a different family catches what the author
  cannot.
- **Ideal.** Leave `models.reviewer` empty: the plugin's reviewer-family extension moves omp's
  bundled `reviewer` agent to a model of another family than the session's at spawn time, so it
  stays right when the user switches driver models.
- **Probe.** `models.available` (families logged in), `models.reviewer`.
- **Alternatives.** Pin `models.reviewer` (costs: the pin can be the driver's own family after a
  model switch; doctor does not know the driver). One family only: the review still runs, and the
  PR's Testing section says it was same-family; recommend a second subscription (`/login` in omp)
  as the fix, not as a requirement.
- **Ask.** Only when one family is available, or the user wants a specific reviewer.
- **Re-offer when.** A second family becomes available while the choice records "one family".

### behaviour-models: the pair for prompt and tool-text changes

- **Intent.** A change to a prompt, tool description or rule changes model behaviour; precheck
  asks for a before/after run on two models of different families, cheap ones, so the claim
  holds beyond the model that wrote it.
- **Ideal.** The derived pair: per family the cheapest priced reasoning model with ≥128k context
  from the lab's own provider, the two most-used families first (doctor `models.behaviour`).
- **Probe.** `models.behaviour`.
- **Alternatives.** Set `models.behaviour` to two explicit selectors (costs: goes stale as
  catalogs move). One family: the run uses one model and the PR says so.
- **Ask.** Show the derived pair; ask only if the user prefers other models.
- **Re-offer when.** The derived pair changes family composition (a second family appears).

### omp-settings: three settings the flow relies on

- **Intent.** The flow nests agents and runs a long review; omp's defaults stop both.
- **Ideal.** `task.maxRecursionDepth` ≥ 3 (main → lead/task → reviewer; default 2 stops the
  reviewer under a worker); the reviewer's soft request budget ≥ 400 (default 200: a review
  working through review-brief.md hits the wrap-up notice mid-review); `task.isolation.enabled`
  true (workers edit in their own worktrees instead of the user's checkout).
- **Probe.** `omp.task.maxRecursionDepth`, `omp.task.agentSoftRequestBudget.reviewer`,
  `omp.task.isolation.enabled`; each non-ok row's `fix` is the exact line, e.g.
  ```
  omp config set task.maxRecursionDepth 3
  omp config set task.agentSoftRequestBudget '{"reviewer":400}'
  omp config set task.isolation.enabled true
  ```
  (the budget is one record: the probe's line keeps the user's other agents' entries).
- **Alternatives.** Keep a default: depth 2 means workers cannot spawn the reviewer (the main
  session must); budget 200 means reviews end early and get re-run; isolation off means parallel
  workers share the checkout and collide.
- **Ask.** Show the lines; apply with `scripts/doctor --fix omp-settings` on approval. These are
  global omp settings that affect the user's other work: say so.
- **Re-offer when.** A setting drifts below the ideal with no recorded reason.

### image-upload: how PR images reach GitHub

- **Intent.** A figure is often the fastest way for the maintainer to decide. GitHub's own
  attachments (`user-attachments`) are the only images that survive the fork branch being
  deleted after merge, and the only route to a light/dark theme pair (`<picture>`) and a phone-width variant.
- **Ideal.** `images.upload = "relay"`: omp's browser relay with the user's own Chrome signed in to
  github.com; `scripts/pr-images` drives GitHub's upload field in that tab.
- **Probe.** `browser.relay` (relay answering, extension connected, `browser.relay` on),
  `browser.github-signin` (always `unknown` to doctor: open https://github.com in a relay tab and
  check the avatar), `tools.uv` (pr-images runs under uv).
- **Alternatives.** `"fork-links"`: images committed to a branch on the fork, linked raw (costs:
  no theme or phone variants, links break when that branch is deleted, the images are public on
  the fork; this path is untested). Explain the cost rather than silently falling back; the user
  may prefer to set up the relay (`omp browser-relay install`, load the unpacked extension,
  `omp config set browser.relay true`).
- **Ask.** Whether they will use the relay; if not, record why.
- **Re-offer when.** doctor sees a connected relay while the choice is `fork-links`.

### chart-tools: drawing PR figures

- **Intent.** `charts/run.mjs` renders body charts and screenshots headless; small PNGs keep the
  body fast to load.
- **Ideal.** `bun install` done in `charts/`; a Chrome for Testing (omp installs one the first
  time a `browser` tab opens; a system Chrome works on Linux and Windows); pngquant and oxipng
  (size); ffmpeg (loops and video frames).
- **Probe.** `tools.charts`, `tools.pngquant`, `tools.oxipng`, `tools.ffmpeg`; each missing row's
  `fix` is this OS's package-manager line.
- **Alternatives.** Without pngquant/oxipng: larger PNGs, with a warning. Without ffmpeg: no
  loops or video frames. Without Chrome: no figures; text and tables only.
- **Ask.** One approval for the install lines of the missing tools.
- **Re-offer when.** Never on its own; a chart run that fails names the missing tool.

### watcher: noticing changes between sessions

- **Intent.** `pr-queue watch` records what changed while no session was open: queued entries
  that became openable, open PRs newly conflicting with main, merges shipped, bot findings posted
  after a merge. `pr-trace --summary` prints that record first.
- **Ideal.** Optional. A timer every 30 minutes from `contrib/`: macOS
  `contrib/launchd/dev.omp-contrib.pr-queue-watch.plist` (fill `{{SKILL_DIR}}`, `{{CHECKOUT}}`,
  `{{PATH}}`, `{{INTERVAL_SECONDS}}` e.g. 1800, `{{LOG_DIR}}`; install to `~/Library/LaunchAgents/`,
  `launchctl bootstrap gui/$(id -u) <file>`); Linux `contrib/systemd/pr-queue-watch.{service,timer}`
  (`{{SKILL_DIR}}`, `{{CHECKOUT}}`, `{{PATH}}`, `{{INTERVAL}}` e.g. `30min`; install to
  `~/.config/systemd/user/`, `systemctl --user enable --now pr-queue-watch.timer`). Then
  `watch.enabled = true`.
- **Probe.** `watcher`.
- **Alternatives.** None (`watch.enabled = false`): the summary says "no run recorded" and each
  session starts by asking `pr-trace` directly; nothing breaks.
- **Ask.** Whether they want a background job on this machine at all.
- **Re-offer when.** Never; the user enables it.

### autonomy: what opens without asking

- **Intent.** roboomp reviews each PR number once, on the head it first sees; an early mistake is
  permanent on that PR. A P2-by-design change (it changes a default, adds a setting, reverses a
  deliberate contract: [shaping.md](shaping.md)) asks the maintainer for a decision the user
  should own before it goes out under their name.
- **Ideal (defaults).** `autonomy.open_p2 = "hold"`: fixes and changes estimated P0/P1 open through
  the queue on their own; a P2-by-design entry (`pr-queue add --p2-decision TEXT`) waits as
  `user decision pending` until `pr-queue approve KEY`. `autonomy.supervised_opens = 3`: the
  first three PRs stop before `pr-queue open` for the user's OK on the body, a diff summary and
  the own-words sentence they supply (`open --user-approved` after that OK); each counts the
  number down. Anything addressed to a human needs the user's approval of its exact text,
  always, whatever these say.
- **Probe.** `autonomy`.
- **Alternatives.** `open_p2 = "open"`: P2s open like fixes (costs: the maintainer decides a
  question the user never saw; suits a contributor who already knows the maintainers' taste).
  `supervised_opens = 0`: autonomous from the first PR (costs: the first PRs are where the setup's
  mistakes surface). A larger count: more review of the factory's output before trusting it.
- **Ask.** Explain both with the reasons above; most users keep the defaults.
- **Re-offer when.** Never; the supervised count runs down on its own.

### session-reader: how the agent reads omp sessions

- **Intent.** Intake starts from what went wrong in a real session: the user's prompt, the tool
  calls and errors, what the model did next. The hunt reads several recent sessions.
- **Ideal.** omp built-ins, nothing to install: transcripts are JSONL under
  `~/.omp/agent/sessions/<cwd-slug>/<timestamp>_<id>.jsonl` (or `$PI_CODING_AGENT_DIR/sessions`).
  `read` takes a jq filter per line, e.g. `<file>.jsonl?q=select(.type=="message" and
  .message.role=="user") | .message.content[0].text&raw=true` (user prompts) and
  `?q=select(.message.role=="toolResult" and .message.isError) | {toolName: .message.toolName,
  text: .message.content[0].text[0:400]}` (failed tool calls); the eval `archive` namespace lists
  recent sessions with titles and recaps (`await archive.sessions(project="*", limit=50)`) and
  searches typed prompts (`archive.search(...)`).
- **Probe.** `sessions` (recent transcripts under the sessions dir).
- **Alternatives.** None needed. A session the user pastes or names by path works the same.
- **Ask.** Nothing; confirm transcripts exist. If `archive.enabled` is off, the `read` route
  still works.
- **Re-offer when.** Never.

## Dry run

Ends the wizard. Goal: the user sees the whole flow on their own data once, with nothing reaching
GitHub.

1. Hunt as `/contribute` would (its *Hunt* step) over the user's sessions from the last 14 days;
   present the three strongest candidates (what went wrong, evidence, likely area) and let the
   user pick one, or stop here if nothing qualifies.
2. Run the flow on it as far as the queue: duplicate scan (read-only `gh` searches), the fix in a
   worktree on `<branch_prefix><topic>`, self-review, the independent review, precheck, the body
   with the user's own-words sentence.
3. Queue it in a scratch manifest instead of the fork: `scripts/pr-queue --manifest
   <scratch>/queue.json add <branch> --title … --priority … [--p2-decision …] --body <file>
   --no-push`, then `pr-queue --manifest <scratch>/queue.json plan`. Show the plan row (open,
   held, or waiting, and why).
4. Stop. Tell the user what a real run would do next (push, `pr-queue open` under supervision),
   and that the branch and worktree are theirs to keep, queue for real, or delete.

The wizard is done when doctor reports `"configured": true` and every remaining `missing` is one
the user chose (recorded in `[choices.*]`).
