"""Hermetic omp-contrib config for the tests: import it before any script module.

Points OMP_CONTRIB_CONFIG, XDG_CONFIG_HOME and XDG_CACHE_HOME at a temp dir, so no test reads the
user's config or writes the user's caches (gh-spend.jsonl, pr-poll, the gh login), and writes a
config naming a test identity: fork owner `FORK_OWNER` on remote `fork`, no supervised opens left.
Subprocesses inherit the environment. A test that needs other values writes its own file and points
OMP_CONTRIB_CONFIG at it (`write_config`), then `omp_config.load(reload=True)`."""
import atexit
import os
import shutil
import tempfile

FORK_OWNER = "octo-fork"
BRANCH_PREFIX = f"{FORK_OWNER}/"
MAINTAINERS = ("can1357", "H4vC")
BASE = """[github]
fork_owner = "%s"
fork_remote = "fork"

[build]
linux = "local"
macos = "local"
windows = "ci"

[autonomy]
open_p2 = "hold"
supervised_opens = 0
""" % FORK_OWNER

ROOT = os.environ.get("OMP_CONTRIB_TEST_ROOT")
if not ROOT:
    ROOT = tempfile.mkdtemp(prefix="omp-contrib-test-env-")
    atexit.register(shutil.rmtree, ROOT, True)
    os.environ.update(OMP_CONTRIB_TEST_ROOT=ROOT, XDG_CONFIG_HOME=os.path.join(ROOT, "config"),
                      XDG_CACHE_HOME=os.path.join(ROOT, "cache"),
                      OMP_CONTRIB_CONFIG=os.path.join(ROOT, "config", "omp-contrib", "config.toml"))
    os.makedirs(os.path.dirname(os.environ["OMP_CONTRIB_CONFIG"]), exist_ok=True)
    with open(os.environ["OMP_CONTRIB_CONFIG"], "w") as f:
        f.write(BASE)
CONFIG = os.environ["OMP_CONTRIB_CONFIG"]


def write_config(path, text):
    """Write a config file at `path` (dirs made); returns the path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path
