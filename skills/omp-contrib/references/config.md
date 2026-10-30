# Configuration

Part of the `omp-contrib` skill. Every machine-specific value the scripts and references use lives in
one TOML file. `/contribute`'s setup wizard writes it ([setup.md](setup.md)); `scripts/doctor`
checks it on every run. Scripts never hard-code a person, host or path.

## Where it lives

`$OMP_CONTRIB_CONFIG`, else `${XDG_CONFIG_HOME:-~/.config}/omp-contrib/config.toml`
(`%APPDATA%\omp-contrib\config.toml` on Windows). Caches go under
`${XDG_CACHE_HOME:-~/.cache}/omp-contrib/`.

Resolution order for every key: environment variable (where one is listed) → the file → a
default derived from the machine → the literal default. A missing file is valid: every key has a
default, and `doctor` reports what it derived.

## Keys

```toml
[github]
upstream_repo = "can1357/oh-my-pi"
maintainers   = ["can1357", "H4vC"]   # logins whose comments, reviews and commits count as maintainer activity
fork_owner    = ""                    # default: `gh api user --jq .login` (cached)
fork_remote   = ""                    # default: the remote whose URL owner is fork_owner
queue_branch  = "omp-queue"           # branch on the fork that stores the PR queue
branch_prefix = ""                    # default: "<fork_owner>/"

[paths]
checkout      = ""                    # env OMP_REPO; default: the enclosing git toplevel when it is an oh-my-pi clone
worktrees     = ""                    # env OMP_PR_WORKTREES; default: "<checkout>-wt" (sibling of the checkout)
scratch_roots = []                    # extra dirs pr-trace searches for a PR's working notes; none by default

# Where each platform's Rust check runs (scripts/rust-check, precheck's `rust` FIX).
#   "local"      this machine (only for its own OS; Windows also via cargo-xwin from Linux/macOS)
#   "ssh:<host>" a host reachable as `ssh <host>`; the agent runs rust-check there
#   "ci"         GitHub Actions on the fork (rust-check --ci)
#   "none"       unchecked: precheck prints a NOTE, the PR's Testing section says so
[build]
linux   = ""                          # default: "local" on Linux, else "ci"
macos   = ""                          # default: "local" on macOS, else "ci"
windows = ""                          # default: "ci"

[models]
reviewer   = ""                       # default: the reviewer-family extension picks a model of another family than the session's
behaviour  = []                       # two models of different families for behaviour runs of prompt changes; default: derived by doctor
cold_read  = ""                       # model for charts/cold-read.py; default: omp's @smol role

[images]
upload = "relay"                      # "relay" (GitHub attachments via the omp browser relay) | "fork-links"

[autonomy]
open_p2          = "hold"             # "hold": a change that is P2 by design waits for the user's go-ahead | "open"
supervised_opens = 3                  # PRs that stop before `pr-queue open` for the user's OK; counts down

[watch]
enabled = false                       # a launchd/systemd timer runs `pr-queue watch` (contrib/)

# One table per wizard decision (setup.md): the choice and why, so doctor never re-asks a deliberate
# choice and re-offers the ideal only when its reason no longer holds. Ids: github, build-hosts,
# reviewer, behaviour-models, omp-settings, image-upload, chart-tools, autonomy, watcher, session-reader.
[choices.image-upload]
value   = "relay"
reason  = "relay connected, Chrome signed in to github.com"
at      = "2026-10-30"
reoffer = true                        # false: the choice holds regardless; doctor never re-offers the ideal
```

## Reading it

Python: `import omp_config; cfg = omp_config.load()` (see the module docstring for the API).
TypeScript (extension, charts): `charts/lib/config.mjs`.
Change a value with `scripts/doctor --set KEY VALUE` (validated, keeps the file's other lines), by
editing the file, or by rerunning `/contribute setup`; `scripts/doctor` validates it.
