"""GitHub spend accounting in omp_pr: every call logged with its GraphQL cost, a spent budget named.
gh is a fake. Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import omp_pr  # noqa: E402

RATE = {"cost": 3, "remaining": 4210, "resetAt": "2026-10-19T01:03:17Z"}


class FakeGh:
    """Answers `gh` calls: GraphQL with `rateLimit` when the query asks for it, plus `data`."""

    def __init__(self, data=None, fail=None):
        self.calls, self.data, self.fail = [], data or {"repository": {"pullRequest": {"number": 1}}}, fail

    def __call__(self, *args, cwd=None):
        self.calls.append(args)
        if self.fail:
            return subprocess.CompletedProcess(args, 1, self.fail, "gh: " + self.fail)
        query = next((a[6:] for a in args if a.startswith("query=")), "")
        data = dict(self.data)
        if "rateLimit" in query:
            data["rateLimit"] = RATE
        return subprocess.CompletedProcess(args, 0, json.dumps({"data": data}), "")



class SpendLogHome(unittest.TestCase):
    def test_the_spend_log_lives_in_the_cache_dir_tests_point_at_a_temp_dir(self):
        # Tests once appended to the user's real gh-spend.jsonl; the log follows XDG_CACHE_HOME.
        self.assertEqual(omp_pr.SPEND_LOG, os.path.join(os.environ["XDG_CACHE_HOME"], "omp-contrib", "gh-spend.jsonl"))
        self.assertTrue(omp_pr.SPEND_LOG.startswith(contrib_env.ROOT))


class SpendLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gh-spend-test-")
        self.log = os.path.join(self.dir, "gh-spend.jsonl")
        patches = [mock.patch.object(omp_pr, "SPEND_LOG", self.log),
                   mock.patch.object(omp_pr.sys, "argv", ["/x/scripts/pr-queue", "plan", "--no-fetch"])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def rows(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def test_graphql_asks_for_its_cost_logs_it_and_returns_the_data_without_it(self):
        gh = FakeGh()
        with mock.patch.object(omp_pr, "run", gh):
            data = omp_pr.graphql('query($n:Int!){repository(owner:"o",name:"r"){pullRequest(number:$n){number}}}', n=7)
        self.assertEqual(data, {"repository": {"pullRequest": {"number": 1}}})
        query = next(a for a in gh.calls[0] if a.startswith("query="))
        self.assertTrue(query.startswith("query=query($n:Int!){rateLimit{cost remaining resetAt} repository"), query)
        self.assertIn("n=7", gh.calls[0][gh.calls[0].index("-F") + 1])
        [row] = self.rows()
        self.assertEqual((row["caller"], row["query"], row["cost"], row["remaining"], row["reset"]),
                         ("pr-queue plan", "repository.pullRequest", 3, 4210, "2026-10-19T01:03:17Z"))
        self.assertEqual(row["api"], "graphql")

    def test_a_query_that_asks_for_rate_limit_itself_keeps_it(self):
        with mock.patch.object(omp_pr, "run", FakeGh()):
            data = omp_pr.graphql("query{rateLimit{cost remaining resetAt} viewer{login}}")
            body = omp_pr.gh_json("api", "graphql", "-f", "query={rateLimit{cost remaining resetAt} viewer{login}}")
        self.assertEqual(data["rateLimit"], RATE)
        self.assertEqual(body["data"]["rateLimit"], RATE)
        self.assertEqual([r["cost"] for r in self.rows()], [3, 3])

    def test_gh_json_prices_api_graphql_and_logs_gh_pr_calls_without_a_cost(self):
        gh = FakeGh()
        with mock.patch.object(omp_pr, "run", gh):
            body = omp_pr.gh_json("api", "graphql", "-f", 'query={repository(owner:"o",name:"r"){pullRequest(number:1){number}}}')
            omp_pr.gh_json("pr", "view", "16257", "-R", "o/r", "--json", "state,comments")
            omp_pr.gh_json("api", "repos/o/r/issues/123")
            omp_pr.gh_json("api", "graphql", "--cache", "5m", "-f", "query={repository{pullRequest(number:1){number}}}")
        self.assertNotIn("rateLimit", body["data"])
        self.assertIn("rateLimit{cost remaining resetAt}", gh.calls[0][-1])
        self.assertEqual(gh.calls[3][-1], "query={repository{pullRequest(number:1){number}}}",
                         "a cached query stays as asked: a hit would replay an old rateLimit")
        rows = self.rows()
        self.assertEqual([(r["api"], r["query"], r["cost"]) for r in rows],
                         [("graphql", "repository.pullRequest", 3), ("graphql", "pr view state,comments", None),
                          ("rest", "api repos/o/r/issues/N", None), ("graphql", "repository.pullRequest (cached)", None)])

    def test_a_spent_budget_says_when_it_resets_instead_of_a_bare_gh_error(self):
        spent = FakeGh(fail="GraphQL: API rate limit already exceeded for user ID 24197106.")
        reset = omp_pr.datetime.datetime(2026, 10, 19, 0, 3, tzinfo=omp_pr.datetime.timezone.utc)
        with mock.patch.object(omp_pr, "run", spent), mock.patch.object(omp_pr, "budget", return_value=(0, reset)):
            with self.assertRaises(omp_pr.RateLimited) as err:
                omp_pr.graphql("{viewer{login}}")
            with self.assertRaises(SystemExit) as exit_:
                omp_pr.gh_json("pr", "view", "1", "--json", "state")
        self.assertIn("resets at 00:03Z", str(err.exception))
        self.assertIn("resets at 00:03Z", str(exit_.exception))
        self.assertEqual(len(self.rows()), 2, "a refused call is logged too")

    def test_caller_names_the_script_and_its_subcommand_not_the_pr_number(self):
        self.assertEqual(omp_pr.caller(["/s/pr-trace", "16257", "16249", "--wait-codex"]), "pr-trace --wait-codex")
        self.assertEqual(omp_pr.caller(["/s/pr-queue", "open", "x"]), "pr-queue open")
        self.assertEqual(omp_pr.caller(["/s/pr-queue", "--manifest", "queue.json", "watch"]), "pr-queue watch")
        self.assertEqual(omp_pr.caller(["/s/pr-trace", "--wait-change", "1", "--state", "keeper/s.json"]),
                         "pr-trace --wait-change")
        self.assertEqual(omp_pr.caller(["/s/precheck", "16257"]), "precheck")

    def test_budget_reads_graphql_rate_limit_not_the_rest_bucket(self):
        gh = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "812\t2026-10-19T01:03:17Z\n", ""))
        with mock.patch.object(omp_pr, "run", gh):
            left, reset = omp_pr.budget()
        self.assertEqual((left, f"{reset:%H:%M}"), (812, "01:03"))
        self.assertEqual(gh.call_args[0][:3], ("gh", "api", "graphql"))


if __name__ == "__main__":
    unittest.main()
