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
                "models": {"reviewers": ["openai-codex/gpt-6.1-sol", "anthropic/claude-opus-5-5"],
                           "behaviour": ["a/claude-haiku-5-5", "b/gpt-6-luna"]},
                "images": {"upload": "relay"}, "autonomy": {"open_p2": "hold", "supervised_opens": 3},
                "watch": {"enabled": False},
                "choices": {"image-upload": {"value": "relay", "reason": "relay connected", "at": "2026-10-30"}}}
        self.assertEqual(D.validate_config(data), [])

    def test_reports_each_problem(self):
        data = {"build": {"linux": "buildbox", "freebsd": "local"}, "images": {"upload": "imgur"},
                "autonomy": {"supervised_opens": True, "open_p2": "maybe"}, "models": {"behaviour": ["one"], "reviewers": "x/y"},
                "extra": {}, "choices": {"image-upload": {"value": "fork-links"}, "nonsense": {"value": 1, "reason": "x"}}}
        errors = "\n".join(D.validate_config(data))
        for needle in ("build.linux: 'buildbox' is not local", "build.freebsd: unknown key", "images.upload: 'imgur'",
                       "autonomy.supervised_opens: expected an integer", "autonomy.open_p2: 'maybe'", "models.behaviour: two models",
                       "models.reviewers: expected list",
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
    def m(provider, id, cost, reasoning=True, ctx=200_000, output=None, kind="chat"):
        return {"provider": provider, "id": id, "selector": f"{provider}/{id}", "kind": kind,
                "cost": {"input": cost, "output": cost * 5 if output is None else output},
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

    def test_behaviour_pair_prefers_anthropic_and_openai_even_through_a_reseller(self):
        models = [self.m("anthropic", "claude-haiku-5-5", 0.1), self.m("google", "gemini-3.8-flash", 0.05),
                  self.m("openrouter", "openai/gpt-6-luna", 0.1)]
        self.assertEqual(D.behaviour_pair(models), ["anthropic/claude-haiku-5-5", "openrouter/openai/gpt-6-luna"])

    # The catalog shape that matters: pricier untiered lines (mythos, astra) and newer cheap tiers (haiku 5.5)
    # beside the flagships, and resellers listing the same labs.
    CATALOG = [("anthropic", "claude-haiku-5-5", 0.1), ("anthropic", "claude-opus-4-8", 5), ("anthropic", "claude-opus-5-5", 4),
               ("anthropic", "claude-sonnet-5-5", 2), ("anthropic", "claude-mythos-5", 10),
               ("openai-codex", "gpt-6-luna", 0.1), ("openai-codex", "gpt-6-astra", 10), ("openai-codex", "gpt-6-sol", 2),
               ("openai-codex", "gpt-6.1-sol", 2), ("openai-codex", "gpt-6.1-terra", 1),
               ("google", "gemini-3.8-flash", 0.75), ("cursor", "claude-opus-4-7-fast", 30), ("openrouter", "openai/gpt-6.1-sol", 2)]

    def models(self, *skip):
        return [self.m(p, i, c) for p, i, c in self.CATALOG if p not in skip and not any(s in i for s in skip)]

    def test_reviewer_ranking_by_tier_then_revision_on_the_labs_own_provider(self):
        rank = lambda fam: [m["selector"] for m in D.reviewer_ranking(fam, D.families(self.models())[fam])]
        self.assertEqual(rank("anthropic")[:3], ["anthropic/claude-opus-5-5", "anthropic/claude-opus-4-8", "anthropic/claude-sonnet-5-5"])
        self.assertEqual(rank("anthropic")[-1], "cursor/claude-opus-4-7-fast")
        self.assertEqual(rank("openai")[:3], ["openai-codex/gpt-6.1-sol", "openai-codex/gpt-6-sol", "openai-codex/gpt-6.1-terra"])
        self.assertLess(rank("openai").index("openai-codex/gpt-6-astra"), rank("openai").index("openai-codex/gpt-6-luna"))

    def test_reviewer_plan_pairs_openai_and_anthropic(self):
        plan = D.reviewer_plan(self.models())
        self.assertEqual(plan["recommended"], ["openai-codex/gpt-6.1-sol", "anthropic/claude-opus-5-5"])
        self.assertEqual(plan["missing"], [])
        self.assertEqual(plan["labs"]["google"], {"best": "google/gemini-3.8-flash", "own": True})

    def test_reviewer_plan_without_openai_falls_back_to_another_lab_and_names_the_login(self):
        plan = D.reviewer_plan(self.models("openai-codex", "openai/"))
        self.assertEqual(plan["recommended"], ["anthropic/claude-opus-5-5", "google/gemini-3.8-flash"])
        self.assertEqual(len(plan["missing"]), 1)
        self.assertIn("no OpenAI login: reviews of Anthropic sessions go to google/gemini-3.8-flash", plan["missing"][0])
        self.assertIn("/login", plan["missing"][0])

    def test_reviewer_plan_with_anthropic_only_stays_same_family(self):
        plan = D.reviewer_plan(self.models("openai-codex", "openai/", "google"))
        self.assertEqual(plan["recommended"], ["anthropic/claude-opus-5-5"])
        self.assertIn("reviews of Anthropic sessions stay same-family", plan["missing"][0])

    def test_reviewer_plan_flags_a_lab_only_through_a_reseller(self):
        plan = D.reviewer_plan(self.models("openai-codex"))
        self.assertEqual(plan["recommended"][0], "openrouter/openai/gpt-6.1-sol")
        self.assertIn("OpenAI only through a reseller", plan["missing"][0])

    def test_reviewers_row_flags_a_one_lab_list_and_reoffers_a_new_lab(self):
        text = ('[models]\nreviewers = ["anthropic/claude-opus-5-5", "google/gemini-3.8-flash"]\n'
                '[choices.reviewer]\nvalue = "anthropic/claude-opus-5-5, google/gemini-3.8-flash"\nreason = "no ChatGPT"\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = contrib_env.write_config(os.path.join(tmp, "c.toml"), text)
            with mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": path}):
                omp_config.load(reload=True)
                doctor = D.Doctor()
                doctor.reviewers(self.models())
                contrib_env.write_config(path, text.replace("google/gemini-3.8-flash", "gone/model", 1))
                omp_config.load(reload=True)
                gone = D.Doctor()
                gone.reviewers(self.models())
        omp_config.load(reload=True)
        row = next(c for c in doctor.checks if c["id"] == "models.reviewers")
        self.assertEqual(row["status"], "ok")
        self.assertTrue(row["reoffer"])
        self.assertEqual(row["recommended"], 'models.reviewers = ["openai-codex/gpt-6.1-sol", "anthropic/claude-opus-5-5"]')
        self.assertIn("Claude sessions are reviewed by the OpenAI entry", row["notes"][0])
        row = next(c for c in gone.checks if c["id"] == "models.reviewers")
        self.assertEqual(row["status"], "degraded")
        self.assertIn("not available: gone/model", row["detail"])
        self.assertIn("--set models.reviewers", row["fix"])


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


class WriteConfigTest(unittest.TestCase):
    def test_set_and_record_keep_other_keys_and_reject_invalid_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = contrib_env.write_config(os.path.join(tmp, "c.toml"), '[github]\nqueue_branch = "q"  # mine\n')
            with mock.patch.dict(os.environ, {"OMP_CONTRIB_CONFIG": path}), mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                self.assertEqual(D.main(["--set", "build.linux", "ci", "--set", "watch.enabled", "true",
                                         "--set", "models.behaviour", "a/x, b/y",
                                         "--record", "image-upload", "fork-links", "no Chrome here", "--no-reoffer"]), 0)
                cfg = omp_config.load(reload=True)
                self.assertEqual((cfg.queue_branch, cfg.build["linux"], cfg.watch_enabled, cfg.behaviour_models),
                                 ("q", "ci", True, ["a/x", "b/y"]))
                self.assertEqual(cfg.choices["image-upload"]["reason"], "no Chrome here")
                self.assertIs(cfg.choices["image-upload"]["reoffer"], False)
                self.assertIn("# mine", open(path).read())
                before = open(path).read()
                self.assertEqual(D.main(["--set", "images.upload", "none"]), 1)
                self.assertEqual(D.main(["--set", "watch.enabled", "yes"]), 1)
                self.assertEqual(open(path).read(), before)
        omp_config.load(reload=True)


class PackageHintTest(unittest.TestCase):
    def test_bun_needs_unzip_and_oxipng_needs_cargo(self):
        which = {"apt-get": "/usr/bin/apt-get"}
        with mock.patch.object(D.shutil, "which", lambda name: which.get(name)):
            self.assertEqual(D.package_hint("bun", "linux"),
                             "sudo apt-get install -y unzip && curl -fsSL https://bun.sh/install | bash")
            self.assertTrue(D.package_hint("oxipng", "linux").endswith(", then: cargo install --locked oxipng"))
            which.update(unzip="/usr/bin/unzip", cargo="/usr/bin/cargo")
            self.assertEqual(D.package_hint("bun", "linux"), "curl -fsSL https://bun.sh/install | bash")
            self.assertEqual(D.package_hint("oxipng", "linux"), "cargo install --locked oxipng")


if __name__ == "__main__":
    unittest.main()
