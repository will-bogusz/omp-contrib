"""omp_config (references/config.md): resolution order env → file → derived → literal, fork-remote
detection by URL owner, the cached gh login, and comment-keeping writes. Run: python3 -m unittest discover -s tests"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import omp_config  # noqa: E402


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=contrib_env.ROOT)
        self.path = os.path.join(self.dir, "config.toml")
        env = {"OMP_CONTRIB_CONFIG": self.path, "XDG_CACHE_HOME": os.path.join(self.dir, "cache")}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        for var in ("OMP_REPO", "OMP_PR_WORKTREES"):
            if var in os.environ:
                p = mock.patch.dict(os.environ)
                p.start()
                self.addCleanup(p.stop)
                del os.environ[var]
        self.addCleanup(omp_config.load, True)

    def load(self, text=None):
        if text is not None:
            contrib_env.write_config(self.path, text)
        return omp_config.load(reload=True)

    def clone(self, remotes):
        repo = os.path.join(self.dir, "oh-my-pi")
        os.makedirs(repo)
        sh(repo, "git", "init", "-q")
        for name, url in remotes.items():
            sh(repo, "git", "remote", "add", name, url)
        return repo


class ResolutionTest(ConfigTest):
    def test_env_beats_file_beats_derived_beats_literal(self):
        cfg = self.load('[paths]\ncheckout = "/from/file"\nworktrees = "/wt/file"\n')
        self.assertEqual((cfg.checkout, cfg.source("paths.checkout")), ("/from/file", "file"))
        with mock.patch.dict(os.environ, {"OMP_REPO": "/from/env"}):
            cfg = self.load()
            self.assertEqual((cfg.checkout, cfg.source("paths.checkout")), ("/from/env", "env"))
            self.assertEqual(cfg.worktrees, "/wt/file")
        cfg = self.load('[paths]\ncheckout = "/from/file"\n')
        self.assertEqual((cfg.worktrees, cfg.source("paths.worktrees")), ("/from/file-wt", "derived"))
        self.assertEqual((cfg.queue_branch, cfg.source("github.queue_branch")), ("omp-queue", "default"))

    def test_a_missing_file_is_valid_and_every_key_has_a_value(self):
        with mock.patch.object(omp_config, "gh_login", return_value="someone"):
            cfg = self.load()
            self.assertFalse(cfg.exists)
            for key in omp_config.DEFAULTS:
                cfg.get(key)
            self.assertEqual(cfg.upstream_repo, "can1357/oh-my-pi")
            self.assertEqual(cfg.branch_prefix, "someone/")
            self.assertEqual(cfg.supervised_opens, 3)
            self.assertEqual(cfg.open_p2, "hold")
        with self.assertRaises(KeyError):
            cfg.get("github.nope")

    def test_the_own_os_builds_locally_and_others_on_ci(self):
        here = "macos" if sys.platform == "darwin" else "linux"
        cfg = self.load('[build]\nwindows = "none"\n')
        self.assertEqual(cfg.build[here], "local")
        self.assertEqual(cfg.build["windows"], "none")
        self.assertEqual(cfg.build[{"macos": "linux", "linux": "macos"}[here]], "ci")

    def test_config_path_follows_xdg_and_appdata(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x"}):
            del os.environ["OMP_CONTRIB_CONFIG"]
            self.assertEqual(omp_config.config_path(), "/x/omp-contrib/config.toml")
            with mock.patch.object(omp_config, "_windows", return_value=True), \
                    mock.patch.dict(os.environ, {"APPDATA": "C:/Users/u/AppData/Roaming"}):
                self.assertEqual(omp_config.config_path(),
                                 os.path.join("C:/Users/u/AppData/Roaming", "omp-contrib", "config.toml"))
        self.assertEqual(omp_config.cache_dir("pr-poll"), os.path.join(self.dir, "cache", "omp-contrib", "pr-poll"))


class ForkTest(ConfigTest):
    def test_the_fork_remote_is_the_one_whose_url_owner_is_the_fork_owner(self):
        repo = self.clone({"origin": "https://github.com/can1357/oh-my-pi.git",
                           "mine": "git@github.com:Octo-Fork/oh-my-pi.git",
                           "friend": "https://github.com/someone/oh-my-pi"})
        cfg = self.load(f'[github]\nfork_owner = "octo-fork"\n[paths]\ncheckout = "{repo}"\n')
        self.assertEqual((cfg.fork_remote, cfg.source("github.fork_remote")), ("mine", "derived"))
        self.assertEqual(cfg.fork_repo, "Octo-Fork/oh-my-pi")
        cfg = self.load(f'[github]\nfork_owner = "nobody"\n[paths]\ncheckout = "{repo}"\n')
        self.assertEqual((cfg.fork_remote, cfg.source("github.fork_remote")), ("fork", "default"))
        self.assertEqual(cfg.fork_repo, "nobody/oh-my-pi")

    def test_the_checkout_is_derived_from_an_omp_clone_around_the_cwd(self):
        repo = self.clone({"origin": "https://github.com/can1357/oh-my-pi.git"})
        sh(repo, "git", "-c", "user.name=T", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false",
           "commit", "-q", "--allow-empty", "-m", "x")
        wt = os.path.join(self.dir, "wt")
        sh(repo, "git", "worktree", "add", "-q", wt)
        with mock.patch("os.getcwd", return_value=wt):
            cfg = self.load("")
            self.assertEqual(os.path.realpath(cfg.checkout), os.path.realpath(repo), "a worktree names its main clone")

    def test_gh_login_is_cached(self):
        calls = []

        def fake(*args, cwd=None):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "octo\n", "")
        with mock.patch.object(omp_config, "_run", fake):
            self.assertEqual(omp_config.gh_login(), "octo")
            self.assertEqual(omp_config.gh_login(), "octo")
            self.assertEqual(len(calls), 1)
            old = time.time() - omp_config.GH_LOGIN_TTL - 10
            os.utime(omp_config.cache_dir("gh-login"), (old, old))
            omp_config.gh_login()
            self.assertEqual(len(calls), 2, "a week-old answer is asked again")


class HostTest(ConfigTest):
    def test_host_label_names_no_hostname_unless_configured(self):
        self.load("")
        with mock.patch("socket.gethostname", return_value="dev-laptop.local"):
            label = omp_config.host_label()
            self.assertRegex(label, r"^host-[0-9a-f]{6}$")
            self.assertNotIn("will", label.lower())
            self.assertEqual(omp_config.host_label(), label, "stable per host")
        self.load('[queue]\nhost_label = "laptop"\n')
        self.assertEqual(omp_config.host_label(), "laptop")

    def test_stored_paths_write_home_as_tilde_and_read_back(self):
        home = os.path.expanduser("~")
        wt = os.path.join(home, "src", "oh-my-pi-wt", "x")
        self.assertEqual(omp_config.home_path(wt), "~/src/oh-my-pi-wt/x")
        self.assertEqual(omp_config.local_path(omp_config.home_path(wt)), wt)
        self.assertEqual(omp_config.home_path("/srv/wt/x"), "/srv/wt/x")
        self.assertEqual(omp_config.home_path(home + "-other/x"), home + "-other/x")
        self.assertIsNone(omp_config.home_path(None))


class WriteTest(ConfigTest):
    TEXT = ('# my config\n[github]\nfork_owner = "octo"   # me\n\n[autonomy]\nopen_p2 = "hold"\n'
            'supervised_opens = 2  # counts down\n\n[choices.image-upload]\nvalue = "relay"\n')

    def test_set_value_keeps_comments_and_other_keys(self):
        self.load(self.TEXT)
        omp_config.set_value("autonomy", "open_p2", "open")
        omp_config.set_value("build", "linux", "ssh:box")
        omp_config.set_value("github", "maintainers", ["a", "b"])
        with open(self.path) as f:
            text = f.read()
        self.assertIn('# my config\n[github]\nfork_owner = "octo"   # me\nmaintainers = ["a", "b"]\n', text)
        self.assertIn('open_p2 = "open"\nsupervised_opens = 2  # counts down\n', text)
        self.assertIn('[build]\nlinux = "ssh:box"\n', text)
        cfg = omp_config.load()
        self.assertEqual((cfg.open_p2, cfg.build["linux"], cfg.maintainers), ("open", "ssh:box", ("a", "b")))
        self.assertEqual(cfg.choices["image-upload"]["value"], "relay")

    def test_decrement_supervised_counts_down_to_zero(self):
        self.load(self.TEXT)
        self.assertEqual(omp_config.decrement_supervised(), 1)
        self.assertEqual(omp_config.decrement_supervised(), 0)
        self.assertEqual(omp_config.decrement_supervised(), 0)
        with open(self.path) as f:
            self.assertIn("supervised_opens = 0  # counts down\n", f.read())
        self.assertEqual(omp_config.load().supervised_opens, 0)


if __name__ == "__main__":
    unittest.main()
