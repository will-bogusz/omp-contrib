"""One host-wide poll of our PRs for pr-trace's waits (--wait-change, --wait-codex).

A token's 5000 GraphQL points an hour are shared by every agent and the queue watcher using it. Once
~18 agents drained them twice in an hour, each wait polling its own PRs in full (--wait-codex 4
points per PR a minute, --wait-change 1.25 per PR a poll, most of it the review threads' nested
comments). Here every wait on a host goes through one cache under a file lock:

- a cheap gate first: per PR its state, head, mergeability, `updatedAt`, and the ids and edit times
  of its last comments, reviews, threads and reactions, plus main's tip. No nested connection, so
  29 PRs cost one point together (rateLimit dryRun, 2026-10-19); a gate under `max_age` old is reused;
- the full node (the caller's fields) only for a PR whose gate changed since its cached node. A
  reply in a review thread is a new review, a Codex summary edit a new comment `updatedAt`, so
  everything the waits compare shows in the gate;
- each gate query also refreshes every PR another wait on this host still watches, so concurrent
  waits on different PRs share one query an interval instead of one each.
"""
import fcntl
import hashlib
import json
import os
import time

import omp_config
from omp_pr import RATE, graphql as gh_graphql  # logs each poll's cost (gh-spend.jsonl)

CACHE = omp_config.cache_dir("pr-poll")
GATE_FIELDS = """state isDraft mergeable headRefOid updatedAt
  comments(last:100){nodes{id updatedAt}} reviews(last:100){nodes{id updatedAt}}
  reviewThreads(last:100){nodes{id isResolved}} reactions(last:50){nodes{content createdAt user{login}}}"""


def gate_of(node):
    """Fingerprint only GATE_FIELDS, even when GraphQL merged richer selections."""
    keep = {k: node.get(k) for k in ("state", "isDraft", "mergeable", "headRefOid", "updatedAt")}
    fields = {"comments": ("id", "updatedAt"), "reviews": ("id", "updatedAt"),
              "reviewThreads": ("id", "isResolved"), "reactions": ("content", "createdAt", "user")}
    for connection, keys in fields.items():
        nodes = (node.get(connection) or {}).get("nodes")
        keep[connection] = None if nodes is None else [
            {key: ({"login": item[key].get("login")} if key == "user" and item.get(key) else item.get(key))
             for key in keys if key in item} for item in nodes]
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()


def repo_query(owner, name, numbers, fields):
    prs = " ".join(f"p{n}: pullRequest(number:{n}){{{fields}}}" for n in numbers)
    return (f'query{{{RATE} repository(owner:"{owner}",name:"{name}"){{'
            f'main: ref(qualifiedName:"refs/heads/main"){{target{{oid}}}} {prs}}}}}')


class Poll:
    """`poll(numbers, max_age)` -> (main oid, {number: full node or None}, rate)."""

    def __init__(self, repo, fields, cache=CACHE, graphql=gh_graphql, clock=time.time):
        self.owner, self.name = repo.split("/")
        self.fields, self.graphql, self.clock = fields, graphql, clock
        key = hashlib.sha256(f"{repo}\n{fields}".encode()).hexdigest()[:12]
        os.makedirs(cache, exist_ok=True)
        self.path, self.lock = os.path.join(cache, f"{key}.json"), os.path.join(cache, f"{key}.lock")

    def _load(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"main": None, "main_at": 0, "rate": None, "prs": {}}

    def _save(self, state):
        tmp = f"{self.path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, self.path)

    def poll(self, numbers, max_age):
        with open(self.lock, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._load()
            now = self.clock()
            prs = state["prs"]
            for n in numbers:
                prs.setdefault(str(n), {"gate": None, "gate_at": 0, "node": None, "node_gate": None})
                prs[str(n)]["watch_until"] = now + 3 * max_age
            stale = [n for n in numbers if now - prs[str(n)]["gate_at"] >= max_age]
            if stale or now - state["main_at"] >= max_age:
                # Every PR a wait here still watches, refreshed with ours once its gate is half stale.
                ask = sorted(set(stale) | {int(k) for k, v in prs.items()
                                           if v.get("watch_until", 0) > now and now - v["gate_at"] >= max_age / 2})
                data = self.graphql(repo_query(self.owner, self.name, ask, GATE_FIELDS))
                self._take(state, data, now)
                for n in ask:
                    node = data["repository"].get(f"p{n}")
                    prs[str(n)].update(gate=gate_of(node) if node else None, gate_at=now)
            full = [n for n in numbers if prs[str(n)]["gate"] and prs[str(n)]["node_gate"] != prs[str(n)]["gate"]]
            if full:
                data = self.graphql(repo_query(self.owner, self.name, full, f"{GATE_FIELDS} {self.fields}"))
                self._take(state, data, now)
                for n in full:
                    node = data["repository"].get(f"p{n}")
                    gate = gate_of(node) if node else None
                    prs[str(n)].update(node=node, node_gate=gate, gate=gate, gate_at=now)
            for k in [k for k, v in prs.items() if v.get("watch_until", 0) < now - 86400]:
                del prs[k]
            self._save(state)
            return state["main"], {n: prs[str(n)]["node"] if prs[str(n)]["gate"] else None for n in numbers}, \
                state["rate"]

    def _take(self, state, data, now):
        state["main"] = data["repository"]["main"]["target"]["oid"]
        state["main_at"] = now
        state["rate"] = data.get("rateLimit")
