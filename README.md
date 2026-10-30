# omp-contrib

An [omp](https://github.com/can1357/oh-my-pi) plugin that turns something omp got wrong (a bug you hit, a hunch, a session `.jsonl`) into a reviewed, bot-clean pull request on can1357/oh-my-pi, opened from your fork. It carries the contribution workflow as a skill, scripts for the PR queue and checks, and a `/contribute` command that sets it up for your machine, models and accounts.

## Install

```sh
omp plugin install github:will-bogusz/omp-contrib
```

Then, in omp:

```
/contribute                      status of your PRs and queue, then: fix / hunt / status
/contribute setup                (re)run the setup wizard
/contribute ~/path/session.jsonl start from a session where omp misbehaved
/contribute the edit tool drops tabs
```

The first `/contribute` runs the setup wizard. It probes the machine (`scripts/doctor`), recommends each choice with its reason and cost, and changes nothing outside its own config without your OK. It ends with a dry run on one of your recent sessions that stops at a local queue file, before anything reaches GitHub. Your first three PRs stop for your approval before they open, and every PR asks you for its one own-words sentence.

## What setup may change on your machine

Each item is proposed and needs your approval first.

| What | Where |
|---|---|
| Config: your choices and the reason for each | `~/.config/omp-contrib/config.toml` (`$OMP_CONTRIB_CONFIG`; `%APPDATA%` on Windows) |
| Caches: gh login, roboomp tier, poll state, GitHub cost log | `~/.cache/omp-contrib/` |
| Missing tools, through your package manager: `gh`, `bun`, `uv`, Python ≥ 3.11; optional `ffmpeg`, `pngquant`, `oxipng`, rustup + `cargo-xwin` | system |
| An oh-my-pi clone if you have none; a fork on GitHub (`gh repo fork`) and a `fork` remote | your clone, your GitHub account |
| The queue branch `omp-queue` on your fork | your fork |
| A `commit-msg` hook in the clone, so commits pushed to your fork do not reference upstream PRs (an existing hook is kept and runs first) | `.git/hooks/` |
| Three omp settings: `task.maxRecursionDepth 3`, the reviewer's soft request budget 400, `task.isolation.enabled true` | `~/.omp/agent/config.yml` |
| Chart dependencies (`bun install`) | the plugin's `skills/omp-contrib/charts/` |
| Optional: a launchd or systemd timer running `pr-queue watch` every 30 min | `~/Library/LaunchAgents/` or `~/.config/systemd/user/` |

Builds run on this machine by default. Platforms it can't build go to an ssh host you name, GitHub Actions on your fork, or none (then the PR says that platform is unchecked).

## What it does not install

No subagent profiles, so omp's bundled `reviewer` stays yours. It adds an extension that moves that reviewer to a model family other than your session's. It adds no always-on rules: `omp-pr-authoring` loads only when the skill asks for it. It installs no background services unless you enable the watcher. It never posts to a human (a maintainer, an issue, a discussion) without your approval of the exact text.

## Uninstall

```sh
omp plugin uninstall omp-contrib
rm -rf ~/.config/omp-contrib ~/.cache/omp-contrib
```

If you set them up, also remove the hook (`.git/hooks/commit-msg`; a hook it replaced is at `commit-msg.chained`), the watcher unit, and the `omp-queue` branch on your fork. Reset any omp setting with `omp config reset <key>`.
