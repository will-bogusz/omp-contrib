"""omp_poll: the host-wide poll pr-trace's waits share (2026-10-18: ~18 waits drained 5000 points twice
in an hour, each polling its own PRs in full)."""
import copy
import os
import re
import sys
import tempfile
import unittest

import contrib_env  # noqa: E402,F401  (hermetic config and caches; before any script import)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import omp_poll  # noqa: E402

FIELDS = "url body"


class FakeGitHub:
    """Answers gate and full queries from `self.prs` {number: dict}; records each query's kind and PRs."""

    def __init__(self):
        self.prs, self.calls, self.main = {}, [], "m1"

    def set(self, n, **fields):
        base = {"state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "headRefOid": "h1",
                "updatedAt": "t0", "comments": {"nodes": []}, "reviews": {"nodes": []},
                "reviewThreads": {"nodes": []}, "reactions": {"nodes": []}, "url": f"u{n}", "body": "b"}
        self.prs[n] = {**base, **self.prs.get(n, {}), **fields}

    def __call__(self, query):
        numbers = [int(n) for n in re.findall(r"p(\d+): pullRequest", query)]
        full = FIELDS in query
        self.calls.append(("full" if full else "gate", numbers))
        repo = {"main": {"target": {"oid": self.main}}}
        for n in numbers:
            node = dict(self.prs[n]) if n in self.prs else None
            if node and not full:
                node = copy.deepcopy(node)
                node.pop("url"), node.pop("body")
                for connection, keys in {
                    "comments": ("id", "updatedAt"), "reviews": ("id", "updatedAt"),
                    "reviewThreads": ("id", "isResolved"), "reactions": ("content", "createdAt", "user")
                }.items():
                    node[connection]["nodes"] = [
                        {key: item[key] for key in keys if key in item} for item in node[connection]["nodes"]]
            repo[f"p{n}"] = node
        return {"rateLimit": {"cost": 1, "remaining": 4000, "resetAt": "2026-10-19T00:00:00Z"}, "repository": repo}


class PollTest(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.gh, self.now = FakeGitHub(), [1000.0]
        for n in (1, 2, 3):
            self.gh.set(n)

    def poller(self):
        return omp_poll.Poll("o/r", FIELDS, cache=self.cache, graphql=self.gh, clock=lambda: self.now[0])

    def test_first_poll_reads_gate_then_full(self):
        main, nodes, rate = self.poller().poll([1], 60)
        self.assertEqual((main, nodes[1]["url"], rate["remaining"]), ("m1", "u1", 4000))
        self.assertEqual(self.gh.calls, [("gate", [1]), ("full", [1])])

    def test_waits_on_one_host_share_a_fresh_gate(self):
        self.poller().poll([1], 60)
        self.now[0] += 30
        _, nodes, _ = self.poller().poll([1], 60)  # another wait, inside max_age: no query at all
        self.assertEqual(nodes[1]["url"], "u1")
        self.assertEqual(len(self.gh.calls), 2)

    def test_an_unchanged_gate_skips_the_full_read(self):
        self.poller().poll([1], 60)
        self.now[0] += 61
        self.poller().poll([1], 60)
        self.assertEqual(self.gh.calls[2:], [("gate", [1])])

    def test_overlapping_full_connections_do_not_trigger_another_full_read(self):
        rich = {
            "comments": {"nodes": [{"id": "C", "updatedAt": "t1", "body": "comment", "author": {"login": "a"}}]},
            "reviews": {"nodes": [{"id": "R", "updatedAt": "t1", "state": "COMMENTED", "body": "review"}]},
            "reviewThreads": {"nodes": [{"id": "T", "isResolved": False, "comments": {"nodes": [{"body": "reply"}]}}]},
            "reactions": {"nodes": [{"content": "EYES", "createdAt": "t1", "user": {"login": "a"}}]},
        }
        self.gh.set(1, **rich)
        fields = FIELDS + " comments(last:100){nodes{body}} reviews(last:100){nodes{body state}}"
        poll = omp_poll.Poll("o/r", fields, cache=self.cache, graphql=self.gh, clock=lambda: self.now[0])
        _, nodes, _ = poll.poll([1], 60)
        self.assertEqual(nodes[1]["comments"]["nodes"][0]["body"], "comment")
        self.gh.calls.clear()
        self.now[0] += 61
        poll.poll([1], 60)
        self.assertEqual(self.gh.calls, [("gate", [1])])

    def test_reaction_user_projection_ignores_extra_fields(self):
        node = {"reactions": {"nodes": [{"content": "EYES", "createdAt": "t1",
                                         "user": {"login": "a", "id": "U"}}]}}
        gate = copy.deepcopy(node)
        del gate["reactions"]["nodes"][0]["user"]["id"]
        self.assertEqual(omp_poll.gate_of(node), omp_poll.gate_of(gate))

    def test_any_change_the_waits_compare_fetches_that_pr_alone(self):
        self.poller().poll([1, 2], 60)
        for change in ({"headRefOid": "h2"}, {"mergeable": "CONFLICTING"}, {"isDraft": True},
                       {"comments": {"nodes": [{"id": "C1", "updatedAt": "t1"}]}},  # a Codex summary edit
                       {"reviews": {"nodes": [{"id": "R1", "updatedAt": "t1"}]}},  # a thread reply is a review
                       {"reviewThreads": {"nodes": [{"id": "T1", "isResolved": True}]}},
                       {"reactions": {"nodes": [{"content": "EYES", "createdAt": "t1", "user": {"login": "c"}}]}}):
            self.gh.calls.clear()
            self.gh.set(2, **change, body=str(change))
            self.now[0] += 61
            _, nodes, _ = self.poller().poll([1, 2], 60)
            self.assertEqual(self.gh.calls, [("gate", [1, 2]), ("full", [2])], change)
            self.assertEqual(nodes[2]["body"], str(change))

    def test_a_gate_query_refreshes_what_other_waits_watch(self):
        self.poller().poll([1], 60)
        self.poller().poll([2], 60)
        self.now[0] += 61
        self.gh.calls.clear()
        self.poller().poll([1], 60)
        self.assertEqual(self.gh.calls, [("gate", [1, 2])])
        self.gh.calls.clear()
        self.now[0] += 5
        self.poller().poll([2], 60)  # its gate came with #1's: nothing to ask
        self.assertEqual(self.gh.calls, [])

    def test_a_watch_that_stopped_drops_out(self):
        self.poller().poll([3], 60)
        self.now[0] += 1000
        self.gh.calls.clear()
        self.poller().poll([1], 60)
        self.assertEqual(self.gh.calls[0], ("gate", [1]))

    def test_a_missing_pr_is_none(self):
        _, nodes, _ = self.poller().poll([9], 60)
        self.assertEqual(nodes, {9: None})


if __name__ == "__main__":
    unittest.main()
