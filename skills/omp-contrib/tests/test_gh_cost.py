"""gh-cost: reading gh's GH_DEBUG=api log into priced requests."""
import importlib.machinery
import importlib.util
import os
import unittest

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
loader = importlib.machinery.SourceFileLoader("gh_cost", os.path.join(SCRIPTS, "gh-cost"))
GC = importlib.util.module_from_spec(importlib.util.spec_from_loader("gh_cost", loader))
loader.exec_module(GC)


def block(url, request, status="200", resource="graphql", took="212.5ms"):
    return (f"* Request at 2026-10-19\n* Request to {url}\n> POST /graphql HTTP/1.1\n> Host: api.github.com\n\n"
            f"{request}\n\n< HTTP/2.0 {status} OK\n< X-Ratelimit-Resource: {resource}\n\n{{}}\n* Request took {took}\n")


class RequestsTest(unittest.TestCase):
    def test_gh_pr_view_pretty_json_rest_304_and_cache_hits(self):
        log = (block("https://api.github.com/graphql",
                     "GraphQL query:\nquery PullRequestByNumber($n: Int!) {\n  x\n}\nGraphQL variables: {\"n\":1}")
               + block("https://api.github.com/graphql", '{\n  "query": "query{rateLimit{cost} repository{a}}"\n}')
               + block("https://api.github.com/graphql", '{\n  "query": "query{b}"\n}', took="176.3µs")
               + block("https://api.github.com/repos/o/r/pulls/12/comments", "", status="304", resource="core")
               + block("https://api.github.com/repos/o/r/pulls/12/comments", "", resource="core").replace(
                   "> POST /graphql", "> GET /repos/o/r/pulls/12/comments?page=2"))
        found = GC.requests(log)
        self.assertEqual([(k, label) for k, label, _, _ in found],
                         [("graphql", "query PullRequestByNumber"), ("graphql", "query{rateLimit{cost}repository{a}}"),
                          ("core", "GET /repos/o/r/pulls/N/comments")])
        self.assertEqual(found[0][3], '{"n":1}')

    def test_dry_run_replaces_the_querys_own_rate_limit(self):
        self.assertEqual(GC.with_dry_run('query{rateLimit{cost remaining} repository(owner:"o"){x}}'),
                         'query{rateLimit(dryRun:true){cost}  repository(owner:"o"){x}}')
        self.assertEqual(GC.with_dry_run("query Q($n: Int!) {x}"), "query Q($n: Int!) {rateLimit(dryRun:true){cost} x}")


if __name__ == "__main__":
    unittest.main()
