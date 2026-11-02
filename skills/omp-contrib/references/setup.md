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
2. Walk the records below in order (later ones depend on earlier: `ci` builds need the fork, so
   apply the github record before asking build-hosts). For each: say in a sentence what it
   protects, state what the probe found, recommend the best option this machine supports **with
   its reason and the cost of each lower option**, and let the user tweak. Every question the user
   sees, in prose or in an `ask` form, meets all of these:
   - **Intent in the question.** The question text says in plain words what the record is for
     and what goes wrong without it, not only the config key.
   - **A reason and a cost on every option.** Each `ask` option's `description` carries why
     someone picks it and what it costs or gives up; the user reads a form option by option, so a
     reason only in prose above the form does not count. Options name the user's actual
     choices from the probe (their logins and models, hosts, tools), not generic ones.
   - **Recommended option first** (`recommended: 0`).
   - **Batching** several records into one `ask` is fine only when each question meets the
     above on its own. Records whose probes all came back ideal share one question in the same
     form ("already set up: omp settings (depth 3, …), chart tools, session reader; keep?") that
     names what each one confirms.
   - **Never record a choice the user did not see and answer**, ideal ones included: a record
     is written only after its question was answered. An answer marked
     `(auto-selected after timeout)`, a cancelled question, or a record left out of the form
     stays undecided (doctor keeps listing it); reviewer and autonomy are always asked, never
     recorded as a default.
3. Write each outcome with `scripts/doctor --set KEY VALUE` (e.g. `--set build.linux ci`) and
   `scripts/doctor --record <id> VALUE REASON` (`[choices.<id>]` with `value`, `reason`: the user's
   reason, or the probe fact that made the recommendation stick, and today's `at`). Both edit the
   file in place and refuse an invalid result; never rewrite the whole file, which may hold keys
   the user set. Add `--no-reoffer` when the user says the choice holds regardless; otherwise
   doctor re-offers the ideal once it becomes available, and never re-asks while the recorded
   reason still holds.
4. Commands that change the machine outside the config (installs, `gh repo fork`, `omp config
   set`, unit files, PATH or profile edits) run only after the user approves them; show the exact
   command first. doctor never installs packages itself: its `fix` field is a proposal. After
   installing tools, rerun doctor before acting on rows probed without them (e.g. `gh` may already
   be logged in through `GH_TOKEN`). Never ask the user to paste a token into the chat. Safe local
   repairs go through `scripts/doctor --fix <hook|fork|queue-branch|omp-settings>`, which prints
   each step (`--dry-run` to preview).
5. Rerun `scripts/doctor` and resolve or explain every remaining `missing`.
6. Finish with a dry-run first hunt (*Dry run* below).

`/contribute` without arguments never re-runs the wizard on its own: an undecided record shows
as one line in the status card.

## Decision records

Each: **Intent** (what it protects) · **Ideal** · **Probe** (doctor check ids) · **Cost** (where
the ideal itself costs something) · **Alternatives** (ranked, with cost) · **Ask** · **Re-offer when**.

### github: identity, fork, remotes, hook

- **Intent.** PRs come from the user's fork; the queue lives on a branch of that fork, so every
  machine of theirs sees the same queue; the hook keeps commits pushed to the fork from naming
  `#N`, which would put a cross-reference on upstream PR N's timeline that the maintainer sees.
- **Ideal.** `gh` logged in as the user; git's `user.name`/`user.email` set; an oh-my-pi clone
  with `origin` = upstream and a `fork` remote; the queue branch (`github.queue_branch`) on the
  fork; the commit-msg hook linked into the clone. Branches are named `<branch_prefix><topic>`,
  default `<login>/`.
- **Probe.** `tools.gh-auth`, `tools.git-identity`, `repo.checkout`, `repo.origin`, `repo.fork`,
  `repo.queue-branch`, `repo.hook`, `github.tier` (roboomp's per-hour review cap for this login; first-time
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

### reviewer: who reviews the diff

- **Intent** (say it in these plain words). The model that wrote a fix cannot see its own blind
  spots, and a model from the same lab tends to share them. So before roboomp reviews the PR
  (once ever, on the head it first sees), one model from another lab reads the diff once,
  against review-brief.md, and its findings are fixed first.
- **Ideal.** `models.reviewers` = doctor's `recommended` list: the strongest OpenAI model the
  user can use, then the strongest Anthropic one, e.g. `["openai-codex/gpt-6.1-sol",
  "anthropic/claude-opus-5-5"]`. At spawn the reviewer-family extension takes the first entry
  from another lab than the session's: a Claude session gets the OpenAI reviewer, a GPT session
  the Anthropic one, a session on any other lab the first entry. It stays right when the user
  switches driver models. Why these two labs: their frontier models are the strongest code
  reviewers available on consumer subscriptions, and the whole flow was measured on Opus and Sol.
- **Probe.** `models.labs` (per lab the user is logged in to, its best reviewer; resellers
  marked), `models.reviewers` (current value, `recommended`, and `notes`: the reason, plus one
  line per gap, e.g. "no OpenAI login: reviews of Anthropic sessions go to google/…; `/login`
  ChatGPT Plus/Pro (Codex) adds GPT Sol").
- **Cost.** One review per PR, never repeated. The last measured reviewer run (on Sol) came to
  about $1–2 at list price; on a subscription login it spends quota, not money.
- **Alternatives**, best first: the recommended list → empty (the extension ranks at spawn with
  the same Anthropic/OpenAI preference; costs: the user never sees which model reviews) → models
  the user names (another lab they trust, a cheaper tier; costs: unmeasured with this flow) →
  one lab only (every review of that lab's sessions is same-family and the PR's Testing section
  says so; name the `/login` that adds the missing lab, as a fix, not a requirement). A lab
  reached only through a reseller works but may serve the model differently; doctor's `notes`
  say so.
- **Ask.** Always, even when the recommendation is obvious. In the question: the intent above,
  the labs doctor found with each one's best model (`models.labs`), and how to change it later
  (`/contribute setup` and pick reviewer, or the same `--set`). In the recommended option's
  description: which model reviews which sessions, why those two labs, the cost. The
  alternatives with their costs; when a lab is missing, what that means for this user's sessions
  and the login that adds it (`notes`). Write the answer with
  `scripts/doctor --set models.reviewers '<json list>'` (nothing for "empty") and
  `scripts/doctor --record reviewer '<the list, or "unset">' '<their reason>'`.
- **Re-offer when.** doctor marks `reoffer` (the recommendation now covers Anthropic or OpenAI and
  the choice did not), or an entry stops resolving (`models.reviewers` degraded with a `fix`).

### behaviour-models: the pair for prompt and tool-text changes

- **Intent** (plain words). A change to a prompt, tool description or rule changes what models
  do, and two labs' models read the same line differently (#15402: a GPT model ignored a todo rule
  Opus kept). precheck asks for a before/after run of a small sample set on two cheap models from
  different labs, so the claim holds beyond the model that wrote it.
- **Ideal.** Leave `models.behaviour` empty: doctor derives the pair per lab as the cheapest
  priced reasoning model with ≥128k context on the lab's own provider, Anthropic and OpenAI first
  (most omp users drive with them, so a change is checked where it lands most), e.g. Haiku + GPT
  Luna; it follows the catalog as models change.
- **Probe.** `models.behaviour` (the pair and, in `notes`, why), `models.labs`.
- **Cost.** Only PRs that change agent-facing text: one sample set per model on `main` and on the
  branch, cheap tier, on subscription quota.
- **Alternatives.** The derived pair → two explicit selectors (costs: goes stale as catalogs
  move) → one lab only (the run uses one model and the PR says so; name the login that adds a
  second lab).
- **Ask.** Always, and it may share a form with reviewer: the intent, the derived pair by name,
  why cheap models of those two labs, the cost, the alternatives. Record with
  `scripts/doctor --record behaviour-models derived '<their reason>'` (or `--set models.behaviour
  a,b` for an explicit pair).
- **Re-offer when.** The derived pair changes lab composition (a second lab appears).

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
