"""omp-contrib configuration (references/config.md): one TOML file, resolved per key in the order
environment variable → the file → a default derived from the machine → the literal default.

API:
  config_path()           the file: $OMP_CONTRIB_CONFIG, else ${XDG_CONFIG_HOME:-~/.config}/omp-contrib/config.toml
                          (%APPDATA%\\omp-contrib\\config.toml on Windows). It may not exist.
  cache_dir(*parts)       ${XDG_CACHE_HOME:-~/.cache}/omp-contrib[/parts...] (%LOCALAPPDATA% on Windows);
                          not created: callers makedirs when they write.
  load(reload=False)      the Config for config_path(), cached per path for the process.
  set_value(section, key, value, path=None)
                          writes one key into the file, keeping its other lines and comments (a line
                          `key = …` under `[section]` is replaced with its trailing comment kept; a
                          missing key or section is added). Values: str, int, bool, list of str.
                          Drops load()'s cache.
  decrement_supervised(path=None)
                          autonomy.supervised_opens - 1 (not below 0) written back; returns the new value.

Config (every value resolved; derived ones looked up lazily on first access, then kept):
  cfg.get("section.key")  the resolved value of any key in config.md, e.g. cfg.get("build.linux")
  cfg.source("section.key")  where it came from: "env" | "file" | "derived" | "default"
  cfg.path, cfg.exists    the file and whether it was there; cfg.data is its parsed content ({} if none)
  cfg.choices             {decision id: {"value", "reason", "at", ...}} from [choices.<id>]
  Attributes (same values as get()):
    upstream_repo, maintainers (tuple), fork_owner, fork_remote, fork_repo ("owner/name" of the fork: the
    fork remote's URL, else "<fork_owner>/<upstream name>"), queue_branch, branch_prefix,
    checkout, worktrees, scratch_roots (list of expanded paths), build ({"linux", "macos", "windows"}),
    reviewer_model, behaviour_models (list), cold_read_model, image_upload, open_p2, supervised_opens
    (int), watch_enabled (bool)

Derived defaults:
  github.fork_owner   `gh api user --jq .login`, cached in cache_dir("gh-login") for a week; "" when gh
                      cannot answer
  github.fork_remote  the checkout's remote whose URL owner is fork_owner (case-insensitive); "fork" when none
  github.branch_prefix  "<fork_owner>/" ("" without an owner)
  paths.checkout      env OMP_REPO; else the main clone of the cwd's git repo when it is an oh-my-pi clone
                      (a remote URL ends in the upstream repo's name); else the cwd
  paths.worktrees     env OMP_PR_WORKTREES; else "<checkout>-wt"
  build.<os>          "local" for this machine's own OS, else "ci" (Windows: always "ci")
"""
import json
import os
import re
import subprocess
import sys
import time
import tomllib

ENV_PATH = "OMP_CONTRIB_CONFIG"
GH_LOGIN_TTL = 7 * 86400

DEFAULTS = {
    "github.upstream_repo": "can1357/oh-my-pi",
    "github.maintainers": ["can1357", "H4vC"],
    "github.fork_owner": "",
    "github.fork_remote": "",
    "github.queue_branch": "omp-queue",
    "github.branch_prefix": "",
    "paths.checkout": "",
    "paths.worktrees": "",
    "paths.scratch_roots": [],
    "build.linux": "",
    "build.macos": "",
    "build.windows": "",
    "models.reviewer": "",
    "models.behaviour": [],
    "models.cold_read": "",
    "images.upload": "relay",
    "autonomy.open_p2": "hold",
    "autonomy.supervised_opens": 3,
    "watch.enabled": False,
}
ENV = {"paths.checkout": "OMP_REPO", "paths.worktrees": "OMP_PR_WORKTREES"}
BUILD_VALUES = re.compile(r"^(local|ci|none|ssh:\S+)$")


def _windows():
    return sys.platform.startswith("win") or os.name == "nt"


def config_path():
    if os.environ.get(ENV_PATH):
        return os.path.expanduser(os.environ[ENV_PATH])
    if _windows() and os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], "omp-contrib", "config.toml")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "omp-contrib", "config.toml")


def cache_dir(*parts):
    if _windows() and os.environ.get("LOCALAPPDATA"):
        base = os.environ["LOCALAPPDATA"]
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "omp-contrib", *parts)


def _run(*args, cwd=None):
    try:
        return subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


def gh_login():
    """The gh CLI's login, cached for a week (one `gh api user` per host, not per script run)."""
    path = cache_dir("gh-login")
    try:
        if time.time() - os.path.getmtime(path) < GH_LOGIN_TTL:
            with open(path) as f:
                cached = f.read().strip()
            if cached:
                return cached
    except OSError:
        pass
    p = _run("gh", "api", "user", "--jq", ".login")
    login = p.stdout.strip() if p and p.returncode == 0 else ""
    if login:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(login + "\n")
        except OSError:
            pass
    return login


def url_owner(url):
    """`owner` of a GitHub remote URL (https, ssh or scp form), else ""."""
    m = re.search(r"github\.com[:/]+([^/]+)/", url or "")
    return m.group(1) if m else ""


def _remotes(checkout):
    p = _run("git", "remote", "-v", cwd=checkout) if checkout and os.path.isdir(checkout) else None
    out = {}
    for line in (p.stdout.splitlines() if p and p.returncode == 0 else []):
        parts = line.split()
        if len(parts) >= 2:
            out.setdefault(parts[0], parts[1])
    return out


def _omp_clone(cwd, repo_name):
    """The main clone (not a linked worktree) of cwd's repo when it is an oh-my-pi clone, else ""."""
    p = _run("git", "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    if not p or p.returncode:
        return ""
    common = p.stdout.strip()
    top = os.path.dirname(common) if os.path.basename(common) == ".git" else common
    name = re.compile(r"[/:]" + re.escape(repo_name) + r"(?:\.git)?/?$", re.I)
    return top if any(name.search(u) for u in _remotes(top).values()) else ""


class Config:
    def __init__(self, path, data, exists):
        self.path, self.data, self.exists = path, data, exists
        self._values, self._sources = {}, {}

    # -- resolution -----------------------------------------------------------------------------
    def _file(self, key):
        section, name = key.split(".", 1)
        table = self.data.get(section)
        if isinstance(table, dict) and name in table and table[name] not in ("", None):
            return table[name]
        return None

    def _derive(self, key):
        if key == "github.fork_owner":
            return gh_login()
        if key == "github.fork_remote":
            owner = self.fork_owner.lower()
            remotes = _remotes(self.checkout)
            hits = [r for r, u in remotes.items() if owner and url_owner(u).lower() == owner]
            return (sorted(hits, key=lambda r: r != "fork")[0] if hits else "") or None
        if key == "github.branch_prefix":
            return f"{self.fork_owner}/" if self.fork_owner else None
        if key == "paths.checkout":
            return _omp_clone(os.getcwd(), self.upstream_repo.split("/")[-1]) or None
        if key == "paths.worktrees":
            return self.checkout.rstrip("/\\") + "-wt"
        if key.startswith("build."):
            here = "windows" if _windows() else "macos" if sys.platform == "darwin" else "linux"
            return "local" if key == f"build.{here}" and here != "windows" else "ci"
        return None

    def _literal(self, key):
        if key == "github.fork_remote":
            return "fork"
        if key == "paths.checkout":
            return os.getcwd()
        return DEFAULTS[key]

    def get(self, key):
        if key in self._values:
            return self._values[key]
        if key not in DEFAULTS:
            raise KeyError(f"unknown config key {key!r} (references/config.md)")
        value, source = None, None
        if os.environ.get(ENV.get(key, "")):
            value, source = os.environ[ENV[key]], "env"
        if value is None:
            value = self._file(key)
            source = "file" if value is not None else None
        if value is None:
            value = self._derive(key)
            source = "derived" if value not in (None, "") else None
        if value in (None, ""):
            value, source = self._literal(key), "default"
        if key.startswith("paths.") and isinstance(value, str):
            value = os.path.expanduser(value)
        if key == "paths.scratch_roots":
            value = [os.path.expanduser(v) for v in value]
        self._values[key], self._sources[key] = value, source
        return value

    @property
    def fork_repo(self):
        url = _remotes(self.checkout).get(self.fork_remote, "")
        m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url)
        return m.group(1) if m else f"{self.fork_owner}/{self.upstream_repo.split('/')[-1]}"

    def source(self, key):
        self.get(key)
        return self._sources[key]

    # -- attributes -----------------------------------------------------------------------------
    upstream_repo = property(lambda self: self.get("github.upstream_repo"))
    maintainers = property(lambda self: tuple(self.get("github.maintainers")))
    fork_owner = property(lambda self: self.get("github.fork_owner"))
    fork_remote = property(lambda self: self.get("github.fork_remote"))
    queue_branch = property(lambda self: self.get("github.queue_branch"))
    branch_prefix = property(lambda self: self.get("github.branch_prefix"))
    checkout = property(lambda self: self.get("paths.checkout"))
    worktrees = property(lambda self: self.get("paths.worktrees"))
    scratch_roots = property(lambda self: self.get("paths.scratch_roots"))
    build = property(lambda self: {p: self.get(f"build.{p}") for p in ("linux", "macos", "windows")})
    reviewer_model = property(lambda self: self.get("models.reviewer"))
    behaviour_models = property(lambda self: list(self.get("models.behaviour")))
    cold_read_model = property(lambda self: self.get("models.cold_read"))
    image_upload = property(lambda self: self.get("images.upload"))
    open_p2 = property(lambda self: self.get("autonomy.open_p2"))
    supervised_opens = property(lambda self: int(self.get("autonomy.supervised_opens")))
    watch_enabled = property(lambda self: bool(self.get("watch.enabled")))

    @property
    def choices(self):
        return {k: v for k, v in (self.data.get("choices") or {}).items() if isinstance(v, dict)}


_CACHE = {}


def load(reload=False):
    path = config_path()
    if reload or path not in _CACHE:
        try:
            with open(path, "rb") as f:
                data, exists = tomllib.load(f), True
        except FileNotFoundError:
            data, exists = {}, False
        _CACHE[path] = Config(path, data, exists)
    return _CACHE[path]


def _toml(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    raise TypeError(f"unsupported config value {value!r}")


HEADER = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(?:#.*)?$")


def set_value(section, key, value, path=None):
    """Write `section.key = value`, keeping the file's other lines and comments."""
    path = path or config_path()
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    line_re = re.compile(r"^(\s*" + re.escape(key) + r"\s*=\s*)(.*)$")
    current, start, end = None, None, len(lines)
    for i, line in enumerate(lines):
        m = HEADER.match(line)
        if m:
            if current == section:
                end = i
                break
            current = m.group(1)
            if current == section:
                start = i
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", f"{key} = {_toml(value)}"]
    else:
        for i in range(start + 1, end):
            m = line_re.match(lines[i])
            if m:
                comment = re.search(r"\s+#.*$", m.group(2)) if not m.group(2).lstrip().startswith(("\"", "'", "[")) \
                    else re.search(r"(?<=[\"'\]])(\s+#.*)$", m.group(2))
                lines[i] = m.group(1) + _toml(value) + (comment.group(0) if comment else "")
                break
        else:
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, f"{key} = {_toml(value)}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    _CACHE.pop(path, None)


def decrement_supervised(path=None):
    path = path or config_path()
    left = max(0, load(reload=True).supervised_opens - 1) if path == config_path() else None
    if left is None:
        with open(path, "rb") as f:
            left = max(0, int((tomllib.load(f).get("autonomy") or {}).get("supervised_opens", 3)) - 1)
    set_value("autonomy", "supervised_opens", left, path)
    return left
