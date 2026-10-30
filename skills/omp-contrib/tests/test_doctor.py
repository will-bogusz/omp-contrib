"""scripts/doctor's pure logic: config validation, upstream drift, build placement against what this
machine can do, model families, recorded choices. Run: python3 -m unittest discover -s tests"""
import contrib_env  # noqa: F401  (hermetic config and caches; before any script import)

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
loader = importlib.machinery.SourceFileLoader("doctor", os.path.join(SCRIPTS, "doctor"))
spec = importlib.util.spec_from_loader("doctor", loader)
D = importlib.util.module_from_spec(spec)
loader.exec_module(D)
import omp_config  # noqa: E402


class ValidateConfigTest(unittest.TestCase):
    def test_full_example_is_valid(self):
        data = {"github": {"upstream_repo": "can1357/oh-my-pi", "maintainers": ["can1357"], "fork_owner": "me",
                           "queue_branch": "omp-queue"},
                "paths": {"checkout": "~/src/oh-my-pi", "scratch_roots": []},
                "build": {"linux": "ssh:box", "macos": "local", "windows": "ci"},
                "models": {"reviewer": "", "behaviour": ["a/claude-haiku-5-5", "b/gpt-6-luna"]},
                "images": {"upload": "relay"}, "autonomy": {"open_p2": "hold", "supervised_opens": 3},
                "watch": {"enabled": False},
                "choices": {"image-upload": {"value": "relay", "reason": "relay connected", "at": "2026-10-30"}}}
        self.assertEqual(D.validate_config(data), [])

    def test_reports_each_problem(self):
        data = {"build": {"linux": "buildbox", "freebsd": "local"}, "images": {"upload": "imgur"},
                "autonomy": {"supervised_opens": True, "open_p2": "maybe"}, "models": {"behaviour": ["one"]},
                "extra": {}, "choices": {"image-upload": {"value": "fork-links"}, "nonsense": {"value": 1, "reason": "x"}}}
        errors = "\n".join(D.validate_config(data))
        for needle in ("build.linux: 'buildbox' is not local", "build.freebsd: unknown key", "images.upload: 'imgur'",
                       "autonomy.supervised_opens: expected an integer", "autonomy.open_p2: 'maybe'", "models.behaviour: two models",
                       "[extra]: unknown section", "[choices.image-upload]: no `reason`", "[choices.nonsense]: unknown decision"):
            self.assertIn(needle, errors)

    def test_negative_supervised_opens(self):
        self.assertEqual(D.validate_config({"autonomy": {"supervised_opens": -1}}), ["autonomy.supervised_opens: must be 0 or more"])

    def test_is_configured_needs_a_recorded_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            cases = [(None, False), ("", False), ('[images]\nupload = "relay"\n', False),
                     ('[choices.autonomy]\nvalue = "hold"\nreason = "default kept"\n', True),
                     ('[images]\nupload = "bad"\n[choices.autonomy]\nvalue = "hold"\nreason = "r"\n', False)]
            for text, want in cases:
                if text is None:
                    with contextlib_suppress():
                        os.remove(path)
                else:
                    contrib_env.write_config(path, text)
                with mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": path}):
                    self.assertEqual(D.is_configured(omp_config.load(reload=True)), want, text)
        omp_config.load(reload=True)


class contextlib_suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return exc[0] is FileNotFoundError


class DriftTest(unittest.TestCase):
    AGENTS = "# Rules\n\n## GitHub\nuse gh\n### Pull requests\nsmall\n\n## Code Quality\nx\n\n## Changelog\nentries\n"

    def test_markdown_section_keeps_subsections_and_stops_at_next_h2(self):
        self.assertEqual(D.markdown_section(self.AGENTS, "GitHub"), "## GitHub\nuse gh\n### Pull requests\nsmall\n\n")
        self.assertEqual(D.markdown_section(self.AGENTS, "Changelog"), "## Changelog\nentries\n")
        self.assertEqual(D.markdown_section(self.AGENTS, "Missing"), "")

    def test_compare_drift(self):
        drift = D.compare_drift({"hashes": {"a": "1", "b": "2", "c": "3"}}, {"a": "1", "b": "9", "d": "4"})
        self.assertEqual(drift, {"changed": ["b"], "added": ["d"], "removed": ["c"]})
        self.assertEqual(D.compare_drift({"hashes": {"a": "1"}}, {"a": "1"}), {"changed": [], "added": [], "removed": []})

    def test_upstream_hashes_track_only_the_watched_text(self):
        with tempfile.TemporaryDirectory() as repo:
            def commit(files):
                for rel, text in files.items():
                    os.makedirs(os.path.dirname(os.path.join(repo, rel)) or repo, exist_ok=True)
                    with open(os.path.join(repo, rel), "w") as f:
                        f.write(text)
                subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"], cwd=repo, check=True)
                return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            first = commit({"CONTRIBUTING.md": "be kind\n", "AGENTS.md": self.AGENTS,
                            "python/robomp/src/prompts/directive.md": "rank\n", "src/x.ts": "1\n"})
            base = D.upstream_hashes(repo, first)
            self.assertEqual(sorted(base), ["AGENTS.md#Changelog", "AGENTS.md#GitHub", "CONTRIBUTING.md",
                                            "python/robomp/src/prompts/directive.md"])
            # Code and unwatched AGENTS.md sections change nothing.
            second = commit({"src/x.ts": "2\n", "AGENTS.md": self.AGENTS.replace("## Code Quality\nx", "## Code Quality\ny")})
            self.assertEqual(D.compare_drift({"hashes": base}, D.upstream_hashes(repo, second))["changed"], [])
            third = commit({"AGENTS.md": self.AGENTS.replace("entries", "entries, linked"),
                            "python/robomp/src/prompts/new.md": "x\n"})
            drift = D.compare_drift({"hashes": base}, D.upstream_hashes(repo, third))
            self.assertEqual(drift["changed"], ["AGENTS.md#Changelog"])
            self.assertEqual(drift["added"], ["python/robomp/src/prompts/new.md"])


class PlacementTest(unittest.TestCase):
    MAC = {"here": "macos", "cargo": True, "xwin": False, "win_target": False, "ssh": {}, "ssh_probed": False, "fork": True}

    def caps(self, **kw):
        return {**self.MAC, **kw}

    def test_local_on_own_platform(self):
        self.assertEqual(D.placement_status("macos", "local", self.caps())[0], "ok")
        self.assertEqual(D.placement_status("macos", "local", self.caps(cargo=False))[0], "missing")

    def test_local_on_another_platform(self):
        status, detail, fix = D.placement_status("linux", "local", self.caps())
        self.assertEqual(status, "missing")
        self.assertIn("this machine is macos", detail)
        self.assertIn("build.linux", fix)

    def test_windows_local_needs_xwin_and_target(self):
        status, detail, fix = D.placement_status("windows", "local", self.caps())
        self.assertEqual(status, "missing")
        self.assertIn("cargo-xwin", detail)
        self.assertIn("rustup target add x86_64-pc-windows-msvc", fix)
        self.assertEqual(D.placement_status("windows", "local", self.caps(xwin=True, win_target=True))[0], "ok")

    def test_ssh(self):
        self.assertEqual(D.placement_status("linux", "ssh:box", self.caps())[0], "missing")  # not in ~/.ssh/config
        unprobed = D.placement_status("linux", "ssh:box", self.caps(ssh={"box": None}))
        self.assertEqual(unprobed[0], "ok")
        self.assertIn("--probe-hosts", unprobed[1])
        self.assertEqual(D.placement_status("linux", "ssh:box", self.caps(ssh={"box": None}, ssh_probed=True))[0], "degraded")
        self.assertEqual(D.placement_status("linux", "ssh:box", self.caps(ssh={"box": "macos"}, ssh_probed=True))[0], "missing")
        self.assertEqual(D.placement_status("linux", "ssh:box", self.caps(ssh={"box": "linux"}, ssh_probed=True))[0], "ok")

    def test_ci_needs_fork_and_none_is_a_loud_degrade(self):
        self.assertEqual(D.placement_status("linux", "ci", self.caps())[0], "ok")
        self.assertEqual(D.placement_status("linux", "ci", self.caps(fork=False))[:3:2], ("missing", "doctor --fix fork"))
        status, detail, _ = D.placement_status("windows", "none", self.caps())
        self.assertEqual(status, "degraded")
        self.assertIn("NOTE", detail)

    def test_recommendation_prefers_local_then_ssh_then_ci(self):
        self.assertEqual(D.recommend_placement("macos", self.caps()), "local")
        self.assertEqual(D.recommend_placement("linux", self.caps()), "ci")
        self.assertEqual(D.recommend_placement("linux", self.caps(ssh={"a": "macos", "b": "linux"})), "ssh:b")
        self.assertEqual(D.recommend_placement("windows", self.caps(xwin=True, win_target=True)), "local")
        self.assertEqual(D.recommend_placement("linux", self.caps(fork=False)), "none")

    def test_platform_names(self):
        self.assertEqual(D.host_platform("Darwin"), "macos")
        self.assertEqual(D.host_platform("Linux"), "linux")
        self.assertEqual(D.host_platform("Windows"), "windows")
        self.assertEqual(D.uname_platform("Linux x86_64"), "linux")
        self.assertEqual(D.uname_platform("Darwin arm64"), "macos")
        self.assertEqual(D.uname_platform("MINGW64_NT-10.0 x86_64"), "windows")
        self.assertIsNone(D.uname_platform(""))

    def test_ssh_config_hosts_follow_includes_and_skip_patterns(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".ssh", "conf.d"))
            contrib_env.write_config(os.path.join(home, ".ssh", "config"),
                                     "Include conf.d/*\nHost box other\n  HostName 10.0.0.1\nHost *.lan !x\nHost *\n")
            contrib_env.write_config(os.path.join(home, ".ssh", "conf.d", "a"), "Host winbox\n")
            with mock.patch.dict(os.environ, {"HOME": home}):
                self.assertEqual(D.Doctor.ssh_hosts(None), ["winbox", "box", "other"])


class ModelsTest(unittest.TestCase):
    @staticmethod
    def m(provider, id, cost, reasoning=True, ctx=200_000):
        return {"provider": provider, "id": id, "selector": f"{provider}/{id}", "cost": {"input": cost},
                "reasoning": reasoning, "contextWindow": ctx}

    def test_family(self):
        for model_id, fam in (("claude-haiku-5-5", "anthropic"), ("gpt-6.1-sol", "openai"), ("o3-mini", "openai"),
                              ("gemini-3.8-flash", "google"), ("grok-4.7", "xai"), ("kimi-k3", "moonshot"),
                              ("glm-5.3", "zhipu"), ("anthropic/claude-opus-5-5", "anthropic"), ("composer-2.5", None),
                              ("gpt-oss-120b", "openai"), ("glimpse-1", None)):
            self.assertEqual(D.model_family(model_id), fam, model_id)

    def test_behaviour_pair_prefers_own_providers_cheap_reasoning_models(self):
        models = [self.m("anthropic", "claude-opus-5-5", 4), self.m("anthropic", "claude-haiku-5-5", 0.1),
                  self.m("cursor", "claude-sonnet-5-5", 0), self.m("cursor", "deepseek-v41-flash", 0.05),
                  self.m("openai-codex", "gpt-6-luna", 0.1), self.m("openai-codex", "gpt-6.1-sol", 2),
                  self.m("openai-codex", "gpt-tiny", 0.01, ctx=32_000), self.m("moonshot", "kimi-k2.5", 0.6)]
        self.assertEqual(D.behaviour_pair(models), ["anthropic/claude-haiku-5-5", "openai-codex/gpt-6-luna"])

    def test_behaviour_pair_needs_two_families(self):
        self.assertEqual(D.behaviour_pair([self.m("anthropic", "claude-haiku-5-5", 1), self.m("anthropic", "claude-opus-5-5", 4)]), [])
        self.assertEqual(D.behaviour_pair([self.m("openrouter", "z-ai/glm-5", 1), self.m("openrouter", "qwen/qwen3", 1)]),
                         ["openrouter/z-ai/glm-5", "openrouter/qwen/qwen3"])


class ChoiceTest(unittest.TestCase):
    def test_reoffer_only_when_the_ideal_became_available(self):
        choice = {"value": "fork-links", "reason": "no relay installed"}
        self.assertTrue(D.choice_reoffer(choice, "relay", True))
        self.assertFalse(D.choice_reoffer(choice, "relay", False))
        self.assertFalse(D.choice_reoffer({**choice, "reoffer": False}, "relay", True))
        self.assertFalse(D.choice_reoffer({"value": "relay", "reason": "r"}, "relay", True))
        self.assertFalse(D.choice_reoffer(None, "relay", True))


class ReportTest(unittest.TestCase):
    def test_unconfigured_report_points_at_the_wizard(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": os.path.join(tmp, "none.toml")}):
            omp_config.load(reload=True)
            report = D.Doctor().run(["config", "autonomy"])
        omp_config.load(reload=True)
        self.assertFalse(report["configured"])
        file_row = next(c for c in report["checks"] if c["id"] == "config.file")
        self.assertEqual(file_row["status"], "missing")
        self.assertIn("/contribute setup", file_row["fix"])
        self.assertEqual({c["area"] for c in report["checks"]}, {"config", "autonomy"})
        self.assertIn("NOT CONFIGURED", D.render(report))

    def test_configured_report_lists_undecided_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = contrib_env.write_config(os.path.join(tmp, "c.toml"),
                                            '[choices.autonomy]\nvalue = "hold"\nreason = "start supervised"\nat = "2026-10-30"\n')
            with mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": path}):
                omp_config.load(reload=True)
                report = D.Doctor().run(["config"])
        omp_config.load(reload=True)
        self.assertTrue(report["configured"])
        row = next(c for c in report["checks"] if c["id"] == "config.choices")
        self.assertEqual(row["status"], "degraded")
        self.assertNotIn("autonomy", row["detail"].split(": ", 1)[1].split(", "))
        self.assertIn("image-upload", row["detail"])

    def test_split_set(self):
        self.assertEqual(D._split_set("omp config set task.agentSoftRequestBudget '{\"reviewer\":400}'"),
                         ["task.agentSoftRequestBudget", '{"reviewer":400}'])
        self.assertEqual(D._split_set("omp config set task.maxRecursionDepth 3"), ["task.maxRecursionDepth", "3"])


if __name__ == "__main__":
    unittest.main()
