"""changelog-to-unreleased run in a real git repo, after a rebase (--tip/--old-base)."""
import os
import subprocess
import tempfile
import unittest

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "changelog-to-unreleased")
PATH = "packages/a/CHANGELOG.md"
URL = "https://github.com/can1357/oh-my-pi/pull"


def link(n):
    return f"([#{n}]({URL}/{n}) by [@octo-fork](https://github.com/octo-fork))"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class RelinkedNeedEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@example.com")
        sh(self.repo, "git", "config", "user.name", "t")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, text, msg):
        path = os.path.join(self.repo, PATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-q", "-m", msg)
        return sh(self.repo, "git", "rev-parse", "HEAD")

    def test_drops_our_stale_copy_of_a_need_entry_that_landed_under_a_new_number(self):
        # browser-worker-exit (2026-10-16): its first commit carried its need's entry linked to the
        # need's closed PR #15493; the need reopened and merged as #15920, relinked. The rebuild after
        # the rebase kept the #15493 copy as ours, so the branch re-added the need's entry.
        need = "- Relay tabs reattach after Chrome detaches "
        old = self.commit("# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n\n- Old\n", "init")
        base = self.commit(f"# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n{need}{link(15920)}\n\n"
                           "## [1.0.0]\n\n- Old\n", "need")
        ours = "- Worker exits reattach " + link(15498)
        tip = self.commit(f"# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n{need}{link(15920)}\n{need}{link(15493)}\n"
                          f"{ours}\n\n## [1.0.0]\n\n- Old\n", "ours")
        sh(self.repo, "git", "checkout", "-q", "-b", "upstream", old)
        main = self.commit(f"# Changelog\n\n## [Unreleased]\n\n## [1.1.0]\n\n### Fixed\n\n{need}{link(15920)}\n\n"
                           "## [1.0.0]\n\n- Old\n", "release")
        sh(self.repo, "git", "checkout", "-q", "-b", "rebased", tip)
        sh(self.repo, "git", "rebase", "-q", "-X", "theirs", main)
        subprocess.run([SCRIPT, "--base", main, "--tip", tip, "--old-base", base], cwd=self.repo, check=True,
                       capture_output=True, text=True)
        with open(os.path.join(self.repo, PATH)) as f:
            text = f.read()
        unreleased = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        self.assertIn(ours, unreleased, text)
        self.assertNotIn("15493", text, "the need's entry is main's, whatever PR it links")
        self.assertEqual(text.count(need), 1, text)


if __name__ == "__main__":
    unittest.main()
