"""The queue of our oh-my-pi changes (shaping.md, *Open-PR rule*): the manifest store, each change's
own commits and how they land on main, the audit of our open PRs, and the plan of what stays open
and what opens next. Used by pr-queue, pr-trace and precheck.

A change is an *item*: a manifest entry, or an open PR of ours the manifest does not list yet.
Commits are compared by `git patch-id --stable`, because a maintainer who rebases our branch (and
folds a fixup in) changes every SHA."""
import collections
import datetime
import json
import os
import re
import socket
import subprocess
import tempfile

from omp_pr import (CONFIG, MAINTAINERS, ME, REPO, GhError, budget, classify, github_changelog_conflicts, graphql,
                    merged_prs, open_prs, post_merge_review, run)
import omp_config
import omp_queue_view

MAIN = "origin/main"
STORE_REMOTE = CONFIG.fork_remote
STORE_BRANCH = CONFIG.queue_branch
# Pushes to the fork: gh's login after the host's own credential helpers, so a host with none
# pushes without a per-command `-c credential.helper`. A helper the host has (a keychain) still
# answers first.
PUSH = ("-c", "credential.helper=!gh auth git-credential", "push")
MANIFEST = "queue.json"
STATES = ("queued", "open", "merged", "closed")
RANKS = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
WORKTREES = CONFIG.worktrees

DEFAULT_CONFIG = {
    # Ready events (ready, non-draft open, reopen, new issue) per rolling hour. Not a policy limit:
    # roboomp silently skips a contributor's events past its hourly cap (workflow step 6), so an open
    # past this shows as `next-hour` and goes out then, never later. Unset, it follows the cap of the
    # fork owner's tier (`roboomp_tier`): two under it.
    "ready_budget": None,
    "draft_days": 3,
    # A maintainer comment, review or commit this recent marks a PR as under active review.
    "active_days": 3,
    # A queued P0 or P1 whose only blockers are code conflicts with open P2 PRs of ours open longer than
    # this opens over them (shaping.md, Open-PR rule 3): merge waves take P0 and P1
    # first, so a P1 held behind an old P2 misses them.
    "over_p2_days": 3,
    # [area, regex over changed paths]: a display label that groups plan and audit output, never a
    # limit. A change takes the area most of its files match, first rule winning ties, "other" else.
    # Set your own with the manifest's config `areas`.
    "areas": [],
}

# A change that is P2 by design (shaping.md: it changes a default, adds a setting or reverses a
# deliberate contract) carries the one maintainer decision it asks for (`pr-queue add --p2-decision`).
# With `autonomy.open_p2 = "hold"` it does not open until the user approves that decision
# (`pr-queue approve`): the user, not the agent, decides to put such a question to the maintainer.
P2_HOLD = "user decision pending: "


def entry_hold(entry, open_p2=None):
    """What holds a queued entry from opening, or None: `set --hold`'s reason, else, under
    `autonomy.open_p2 = "hold"`, its unapproved P2 decision as `user decision pending: <decision>`."""
    if entry.get("hold"):
        return entry["hold"]
    if entry.get("p2_decision") and not entry.get("p2_approved") and (open_p2 or omp_config.load().open_p2) == "hold":
        return P2_HOLD + entry["p2_decision"]
    return None


def awaiting_user(entry, open_p2=None):
    """Whether the entry's only hold is its P2 decision waiting on the user."""
    return not entry.get("hold") and bool(entry_hold(entry, open_p2))


# roboomp's hourly cap on a PR author's events, by the author's association with the upstream repo
# (robomp github_events.rate_limit_cap): owners, members and collaborators none, a contributor (any
# merged PR) 10, anyone else 3.
TIER_CAPS = {"maintainer": None, "contributor": 10, "first-time": 3}
TIER_TTL = 86400


def roboomp_tier(login=None):
    """(tier, cap) of `login` (the fork owner) for roboomp's limiter: a maintainer in config, else
    "contributor" once one of their PRs merged upstream (gh search, cached a day), else "first-time"."""
    login = login or ME
    if login in MAINTAINERS:
        return "maintainer", None
    path = omp_config.cache_dir(f"tier-{login}")
    try:
        if datetime.datetime.now().timestamp() - os.path.getmtime(path) < TIER_TTL:
            with open(path) as f:
                tier = f.read().strip()
            if tier in TIER_CAPS:
                return tier, TIER_CAPS[tier]
    except OSError:
        pass
    p = run("gh", "api", "-X", "GET", "search/issues", "-f", f"q=repo:{REPO} author:{login} is:pr is:merged",
            "--jq", ".total_count")
    if p.returncode or not p.stdout.strip().isdigit():
        return "first-time", TIER_CAPS["first-time"]  # unknown: the strictest cap
    tier = "contributor" if int(p.stdout) else "first-time"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(tier + "\n")
    except OSError:
        pass
    return tier, TIER_CAPS[tier]


# Body text that sequences our PRs (shaping.md, *Open-PR rule*: a body never carries it).
MERGE_ORDER = re.compile(
    r"\bmerges?\s+(?:(?:#\d+|this|them|those|it|both)\s+)?(?:first|after|before|alone|second|last)\b"
    r"|\bmerge\s+in\s+(?:that|this)\s+order\b|\bwhichever\s+(?:lands|merges)\b|\boverlap(?:s|ping)?\b[^\n]*#\d+",
    re.I)
# "Builds on #N" counts only when #N is one of our open PRs: "Builds on #14060 by nnnnoel" credits
# another author's work, and "Builds on #15275 (in main now)" names merged groundwork. Only the PR
# list right after the phrase counts, since a body paragraph is one line.
DEPENDS_ON = re.compile(r"\b(?:(?:builds|built|stacked|based|depends|rests|sits)\s+on|merges?\s+after)\b"
                        r"(?:\s+and\s+merges?\s+after)?[\s*:]*((?:#\d+(?:[\s,*&]|and\b)*)+)", re.I)


def depends_refs(line):
    return [int(n) for m in DEPENDS_ON.finditer(line) for n in re.findall(r"#(\d+)", m.group(1))]


def merge_order_lines(body, ours=()):
    """Lines of `body` that sequence PRs: merge-order phrases, overlap notes, and "builds on" a PR in
    `ours` (numbers of our open PRs)."""
    ours = set(ours)
    return [line.strip() for line in (body or "").splitlines()
            if MERGE_ORDER.search(line) or set(depends_refs(line)) & ours]


def body_needs(body, ours):
    """Our open PRs a body says this one builds on or merges after."""
    found = [n for line in (body or "").splitlines() for n in depends_refs(line) if n in ours]
    return list(dict.fromkeys(found))


# The Rust crate or TS package a path builds in. Two changes to one unit can each merge onto main
# cleanly and pass alone and still fail to build together: #15761 changed `worker_with`'s return
# type and #15762 moved that value, E0507 only in the merged tree (2026-10-14). Git sees no
# conflict, so the merged tree has to be built and tested.
UNIT = re.compile(r"^((?:crates|packages)/[^/]+)/")


def build_units(paths):
    """The `crates/<name>` and `packages/<name>` units `paths` change; a CHANGELOG alone is no change."""
    return sorted({m.group(1) for p in paths if not p.endswith("CHANGELOG.md") for m in [UNIT.match(p)] if m})


class GitError(Exception):
    pass


# rerere replays a resolution it recorded for a conflict it saw before ("using previous resolution"). pr-queue
# rebuilds the CHANGELOGs itself, so a replayed resolution can only put a stale line back: every git call here
# runs with rerere off.
GIT_OFF_RERERE = ("-c", "rerere.enabled=false")


def git(repo, *args, input=None, env=None):
    return subprocess.run(["git", *GIT_OFF_RERERE, *args], cwd=repo, capture_output=True, text=True, input=input,
                          env=env)


def git_out(repo, *args, input=None, env=None):
    p = git(repo, *args, input=input, env=env)
    if p.returncode:
        raise GitError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def rev(repo, ref):
    p = git(repo, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    return p.stdout.strip() if p.returncode == 0 else None


def is_ancestor(repo, a, b):
    return git(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


def rev_list(repo, *spec):
    """Non-merge commits, oldest first."""
    return git_out(repo, "rev-list", "--no-merges", "--reverse", "--topo-order", *spec).split()


def merge_tree(repo, ours, theirs, base=None):
    """(tree, conflicted paths) of merging `theirs` into `ours`; the tree is written either way."""
    args = ["merge-tree", "--write-tree", "--name-only", "--no-messages"]
    if base:
        args += ["--merge-base", base]
    p = git(repo, *args, ours, theirs)
    if p.returncode not in (0, 1):
        raise GitError(f"git merge-tree {ours} {theirs}: {p.stderr.strip()}")
    lines = p.stdout.splitlines()
    return lines[0].strip(), [line for line in dict.fromkeys(lines[1:]) if line.strip()]


def commit_tree(repo, tree, parent):
    return git_out(repo, "commit-tree", "--no-gpg-sign", tree, "-p", parent, "-m", "pr-queue landing check")


def topic(branch):
    return branch.split("/", 1)[-1]


# GitHub turns `#N`, `GH-N`, `owner/repo#N` and an issue or PR URL in a commit message into a
# reference, and a commit pushed to our fork resolves `#N` to the upstream repo: every push of a new
# SHA naming a PR lands "<you> added a commit that referenced this pull request" on that PR's
# timeline. `PR N` names it without the link.
REF_URL = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/(pull|issues)/(\d+)[\w#/=?&.-]*")
REF_WORD = re.compile(r"\b(PRs?|pull requests?|issues?)\s+#(\d+)\b", re.I)
REF_REPO = re.compile(r"(?<![\w./-])([\w.-]+/[\w.-]+)#(\d+)\b")
REF_BARE = re.compile(r"(?<![\w&#/])(?:#|GH-)(\d+)\b")


def quiet_refs(text):
    """`text` with each GitHub issue or PR reference written as `PR N` (`issue N` for an issues URL;
    `owner/repo PR N` outside the upstream repo), which GitHub links to nothing."""
    def where(repo):
        return "" if repo.lower() == REPO.lower() else f"{repo} "
    text = REF_URL.sub(lambda m: f"{where(m[1])}{'PR' if m[2] == 'pull' else 'issue'} {m[3]}", text)
    text = REF_WORD.sub(r"\1 \2", text)
    text = REF_REPO.sub(lambda m: f"{where(m[1])}PR {m[2]}", text)
    return REF_BARE.sub(r"PR \1", text)


def quiet_replayed(repo, upstream, kept):
    """Rewrite with `quiet_refs` the messages of HEAD's commits past `upstream` that no commit in
    `kept` (the branch before a rebase, its fork copy) holds: commits a rebase just created, which
    push as new SHAs anyway, so a reworded one adds no push of its own. Trees, authors and dates
    stay. Leaves a branch with merges past `upstream` alone. Returns the count reworded."""
    if git_out(repo, "rev-list", "--merges", f"{upstream}..HEAD"):
        return 0
    head = git_out(repo, "rev-parse", "HEAD")
    chain = git_out(repo, "rev-list", "--reverse", f"{upstream}..HEAD").split()
    new = git_out(repo, "rev-list", "--reverse", f"{upstream}..HEAD", "--not", *[k for k in kept if k]).split()
    if not new or chain[-len(new):] != new:
        return 0
    parent, count = None, 0
    for sha in new:
        header, _, message = git(repo, "cat-file", "commit", sha).stdout.partition("\n\n")
        quiet = quiet_refs(message)
        if parent is None and quiet == message:
            continue
        fields = dict(line.split(" ", 1) for line in header.splitlines()
                      if line.startswith(("tree ", "author ", "committer ")))
        if parent is None:
            parent = git_out(repo, "rev-parse", f"{sha}^")
        env = dict(os.environ)
        for role in ("author", "committer"):
            m = re.match(r"(.*) <(.*)> (\d+ [+-]\d{4})$", fields[role])
            env.update({f"GIT_{role.upper()}_NAME": m[1], f"GIT_{role.upper()}_EMAIL": m[2],
                        f"GIT_{role.upper()}_DATE": m[3]})
        parent = git_out(repo, "commit-tree", fields["tree"], "-p", parent, "-F", "-", input=quiet, env=env)
        count += quiet != message
    if count:
        git_out(repo, "update-ref", "-m", "quiet PR references", "HEAD", parent, head)
    return count


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp():
    return now().strftime("%Y-%m-%dT%H:%M:%SZ")


def kind_rank(title):
    """Fixes before features: fix 0, other types 1, feat 2."""
    m = re.match(r"(\w+)", title or "")
    return {"fix": 0, "feat": 2}.get(m.group(1) if m else "", 1)


def infer_area(paths, rules):
    scores = collections.Counter()
    for path in paths:
        if path.endswith("CHANGELOG.md"):
            continue
        for area, pattern in rules:
            if re.search(pattern, path):
                scores[area] += 1
                break
    if not scores:
        return "other"
    best = max(scores.values())
    return next(area for area, _ in rules if scores[area] == best)


class PatchIds:
    """sha -> `git patch-id --stable`, cached in the repo's shared git dir (a commit's patch id never
    changes), so repeated audits only hash new commits."""

    def __init__(self, repo):
        common = git_out(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        self.path = os.path.join(common, "omp-queue", "patch-ids")
        self.repo, self.known = repo, {}
        try:
            with open(self.path) as f:
                for line in f:
                    sha, _, pid = line.rstrip("\n").partition("\t")
                    self.known[sha] = pid
        except FileNotFoundError:
            pass

    def __call__(self, shas):
        missing = [s for s in dict.fromkeys(shas) if s not in self.known]
        if missing:
            log = git(self.repo, "log", "--no-walk=unsorted", "--stdin", "-p", "--no-color", "--format=commit %H",
                      input="\n".join(missing) + "\n").stdout
            ids = git(self.repo, "patch-id", "--stable", input=log).stdout
            found = {sha: pid for pid, sha in (line.split() for line in ids.splitlines() if line.strip())}
            new = {s: found.get(s, "-") for s in missing}
            self.known.update(new)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a") as f:
                f.writelines(f"{s}\t{p}\n" for s, p in new.items())
        return {s: self.known[s] for s in shas if self.known[s] != "-"}


def empty_manifest():
    return {"version": 1, "config": {}, "entries": []}


def opening_pause(manifest):
    """The queue-wide opening pause `pr-queue pause` sets ("WHO, DATE: REASON"), or None. While it is
    set nothing opens or turns ready; open PRs carry on (bot fixes, rebases, pushes). 2026-10-22: a
    pause relayed in one session's note reached no other, and #16801/#16803 opened during it."""
    return (manifest.get("config") or {}).get("pause") or None


def pause_line(pause):
    return (f"OPENING PAUSED ({pause}): no PR opens or turns ready until `pr-queue unpause`; "
            "open PRs carry on (bot fixes, rebases, pushes)")


class Store:
    """The manifest: `queue.json` plus `bodies/<id>.md` on the fork's queue branch (`github.queue_branch`), so every host
    with the fork remote reads and writes the same queue, and each change is a commit in its history.
    `path` instead keeps them in a local file (dry runs, tests): `<path>` and `<dir>/bodies/`."""

    def __init__(self, repo, path=None):
        self.repo, self.path = repo, path
        self.ref = f"refs/remotes/{STORE_REMOTE}/{STORE_BRANCH}"

    def _fetch(self):
        p = git(self.repo, "fetch", "-q", STORE_REMOTE, f"+refs/heads/{STORE_BRANCH}:{self.ref}")
        if p.returncode:
            if "couldn't find remote ref" not in p.stderr:
                raise GitError(f"fetching the queue from {STORE_REMOTE}: {p.stderr.strip()}")
            git(self.repo, "update-ref", "-d", self.ref)

    def load(self, fetch=True):
        """(manifest, token): token is the store commit the manifest came from (None when local or new)."""
        if self.path:
            try:
                with open(self.path) as f:
                    return normalize(json.load(f)), None
            except FileNotFoundError:
                return empty_manifest(), None
        if fetch:
            self._fetch()
        token = rev(self.repo, self.ref)
        if not token:
            return empty_manifest(), None
        return normalize(json.loads(git_out(self.repo, "show", f"{token}:{MANIFEST}"))), token

    def read(self, rel, token=None):
        if self.path:
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(self.path)), rel)) as f:
                    return f.read()
            except FileNotFoundError:
                return None
        token = token or rev(self.repo, self.ref)
        p = git(self.repo, "show", f"{token}:{rel}") if token else None
        return p.stdout if p and p.returncode == 0 else None

    def update(self, fn, message):
        """Apply `fn(manifest, files)` to the latest manifest and store it; `files` collects extra
        {path: text} to write (bodies). A push that loses a race re-reads and re-applies `fn`, so
        `fn` only edits the manifest; side effects belong before or after. Every write also renders
        QUEUE.md from the manifest it stores (omp_queue_view), in the same commit."""
        for _ in range(5):
            manifest, token = self.load()
            files = {}
            result = fn(manifest, files)
            files[MANIFEST] = json.dumps(manifest, indent=1) + "\n"
            files[omp_queue_view.VIEW] = omp_queue_view.render(manifest, stamp())
            if self.path:
                root = os.path.dirname(os.path.abspath(self.path))
                for rel, text in files.items():
                    target = self.path if rel == MANIFEST else os.path.join(root, rel)
                    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
                    with open(target, "w") as f:
                        f.write(text)
                return result
            commit = self._commit(token, files, message)
            p = git(self.repo, *PUSH, "-q", STORE_REMOTE, f"{commit}:refs/heads/{STORE_BRANCH}")
            if p.returncode == 0:
                git_out(self.repo, "update-ref", self.ref, commit)
                return result
            if not re.search(r"rejected|fetch first|non-fast-forward", p.stderr):
                raise GitError(f"pushing the queue to {STORE_REMOTE}: {p.stderr.strip()}")
        raise GitError("the queue changed under five attempts in a row; rerun")

    def _commit(self, token, files, message):
        with tempfile.TemporaryDirectory(prefix="pr-queue-") as tmp:
            env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
            if token:
                git_out(self.repo, "read-tree", token, env=env)
            for rel, text in files.items():
                oid = git_out(self.repo, "hash-object", "-w", "--stdin", input=text)
                git_out(self.repo, "update-index", "--add", "--cacheinfo", f"100644,{oid},{rel}", env=env)
            tree = git_out(self.repo, "write-tree", env=env)
        return git_out(self.repo, "commit-tree", "--no-gpg-sign", tree, "-m", quiet_refs(message),
                       *(["-p", token] if token else []))


def normalize(manifest):
    manifest.setdefault("version", 1)
    manifest.setdefault("config", {})
    manifest.setdefault("entries", [])
    return manifest


def find_entry(manifest, key):
    """Entry by id, branch, or PR number (`#N` or `N`, current or closed)."""
    key = str(key)
    number = int(key.lstrip("#")) if key.lstrip("#").isdigit() else None
    for entry in manifest["entries"]:
        if number is not None and (entry.get("pr") == number or number in entry.get("closed_prs", [])):
            return entry
        if entry["id"] == key or entry["branch"] == key:
            return entry
    return None


def stored_body_entry(manifest, number, state):
    """The entry whose stored body replaces closed PR `number`'s GitHub body at reopen (`open` posts
    the stored one), or None while GitHub's is the body to edit. `state` is GitHub's PR state."""
    if state != "CLOSED":
        return None
    return next((e for e in manifest["entries"] if number in e.get("closed_prs", [])), None)


def stored_body_message(number, entry):
    return (f"#{number} is closed, queued as {entry['id']}; edit its stored body (pr-queue show / set --body), "
            "not GitHub's")


def new_entry(branch, **fields):
    entry = {"id": topic(branch), "branch": branch, "title": None, "area": None, "priority": None, "needs": [],
             "base": None, "body": None, "state": "queued", "pr": None, "closed_prs": [], "worktree": None,
             "host": socket.gethostname().split(".")[0], "added": stamp(), "updated": stamp(), "note": ""}
    entry.update({k: v for k, v in fields.items() if v is not None})
    return entry


class GitHub:
    """The GitHub reads and writes the queue needs, through `gh`. Tests substitute a fake."""

    owner, name = REPO.split("/")

    def open_prs(self):
        return open_prs()

    def merged_since(self, since, after=""):
        return merged_prs(since, after)

    def post_merge_open(self, merges, cwd):
        """{number: [finding]}: each merge's bot findings posted after it that no later origin/main
        commit took up and whose thread is not resolved (omp_pr.post_merge_review). A finding our
        follow-up PR addresses stays, with `addressed_by`, so it is asked about again and comes back
        if that PR closes unmerged."""
        merges = [dict(m) for m in merges]
        try:
            post_merge_review(merges, cwd=cwd)
        except (GhError, SystemExit) as e:
            # gh_json exits on a failed `gh` call; the watcher's run goes on without these findings.
            raise GitError(f"post-merge findings query failed: {e}") from e
        return {m["number"]: [f for f in m["post_merge"] if not f["taken_up"]] for m in merges}

    def _graphql(self, query, **variables):
        try:
            return graphql(query, **variables)
        except GhError as e:
            raise GitError(str(e)) from e

    def budget(self):
        """(GraphQL points left, reset time); (None, None) when unknown. Free to ask."""
        return budget()

    def _batch(self, numbers, fields, size):
        out = {}
        numbers = sorted(set(numbers))
        for i in range(0, len(numbers), size):
            parts = "".join(f"n{n}:issueOrPullRequest(number:{n}){{{fields}}}" for n in numbers[i:i + size])
            data = self._graphql(f'query{{repository(owner:"{self.owner}",name:"{self.name}"){{{parts}}}}}')
            out.update({v["number"]: v for v in data["repository"].values() if v})
        return out

    def states(self, numbers):
        """{number: "OPEN" | "MERGED" | "CLOSED"} for PRs and issues."""
        rows = self._batch(numbers, "... on PullRequest{number state} ... on Issue{number state}", 50)
        return {n: r["state"] for n, r in rows.items()}

    def active(self, numbers, days):
        """Numbers with a maintainer comment, review, or commit (authored or committed) in `days`."""
        since = (now() - datetime.timedelta(days=days)).isoformat()
        fields = ("... on PullRequest{number comments(last:20){nodes{author{login} createdAt}} "
                  "reviews(last:20){nodes{author{login} submittedAt}} commits(last:20){nodes{commit{"
                  "committedDate author{user{login}} committer{user{login}}}}}}")
        active = set()
        for n, pr in self._batch(numbers, fields, 20).items():
            stamps = [(c["author"] or {}).get("login") for c in pr["comments"]["nodes"] if c["createdAt"] >= since]
            stamps += [(r["author"] or {}).get("login") for r in pr["reviews"]["nodes"] if (r["submittedAt"] or "") >= since]
            for c in pr["commits"]["nodes"]:
                if c["commit"]["committedDate"] >= since:
                    stamps += [((c["commit"].get(k) or {}).get("user") or {}).get("login") for k in ("author", "committer")]
            if any(s in MAINTAINERS for s in stamps):
                active.add(n)
        return active

    def ready_events_since(self, since):
        """Events roboomp's limiter admits for us since `since`: a PR opened non-draft, marked ready or
        reopened while not a draft (`_pr_review_pr` drops drafts first), and an issue filed or reopened."""
        query = """query($q:String!){search(query:$q,type:ISSUE,first:100%s){
          pageInfo{hasNextPage endCursor} nodes{
          ... on PullRequest{createdAt isDraft timelineItems(last:100,itemTypes:[READY_FOR_REVIEW_EVENT,
            CONVERT_TO_DRAFT_EVENT,REOPENED_EVENT]){filteredCount nodes{__typename ... on ReadyForReviewEvent{createdAt}
            ... on ConvertToDraftEvent{createdAt} ... on ReopenedEvent{createdAt}}}}
          ... on Issue{createdAt timelineItems(last:100,itemTypes:[REOPENED_EVENT]){filteredCount nodes{__typename
            ... on ReopenedEvent{createdAt}}}}}}}"""
        iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        count, cursor = 0, None
        while True:
            after = f', after:"{cursor}"' if cursor else ""
            search = self._graphql(query % after, q=f"repo:{REPO} author:{ME} updated:>={iso}")["search"]
            for node in search["nodes"]:
                timeline = node["timelineItems"]
                # GitHub returns timeline items in order; equal timestamps keep that order.
                events = [(e["createdAt"], e["__typename"]) for e in timeline["nodes"]]
                hidden = timeline["filteredCount"] - len(events)
                if hidden and (not events or events[0][0] >= iso):
                    count += hidden  # older items cut off may fall in the window: assume they all count
                if "isDraft" not in node:  # an issue
                    count += (node["createdAt"] >= iso) + sum(1 for at, _ in events if at >= iso)
                    continue
                # Draft at creation if its first toggle readied it; with no toggle, as it is now.
                toggles = [kind for _, kind in events if kind != "ReopenedEvent"]
                draft = toggles[0] == "ReadyForReviewEvent" if toggles else node["isDraft"]
                count += node["createdAt"] >= iso and not draft and not hidden
                for at, kind in events:
                    if kind == "ReadyForReviewEvent":
                        draft = False
                        count += at >= iso
                    elif kind == "ConvertToDraftEvent":
                        draft = True
                    else:
                        count += at >= iso and not draft
            if not search["pageInfo"]["hasNextPage"]:
                return count
            cursor = search["pageInfo"]["endCursor"]

    def tier(self):
        """(tier, cap) of the fork owner for roboomp's hourly limiter (`roboomp_tier`)."""
        return roboomp_tier()

    def create_draft(self, branch, title, body_file):
        p = run("gh", "pr", "create", "-R", REPO, "--base", "main", "--head", f"{ME}:{branch}", "--title", title,
                "--body-file", body_file, "--draft")
        if p.returncode:
            raise GitError(f"gh pr create: {p.stderr.strip()}")
        return int(p.stdout.strip().rstrip("/").rsplit("/", 1)[-1])

    def ready(self, number):
        # Bounded, so the open lock (refreshed just before this call) cannot expire during it.
        try:
            p = subprocess.run(["gh", "pr", "ready", str(number), "-R", REPO], capture_output=True, text=True,
                               timeout=60)
        except subprocess.TimeoutExpired:
            raise GitError(f"gh pr ready {number}: no answer in 60 s; check the PR's state before retrying")
        if p.returncode:
            raise GitError(f"gh pr ready {number}: {p.stderr.strip()}")

    def close(self, number):
        p = run("gh", "pr", "close", str(number), "-R", REPO)
        if p.returncode:
            raise GitError(f"gh pr close {number}: {p.stderr.strip()}")

    def body(self, number):
        p = run("gh", "pr", "view", str(number), "-R", REPO, "--json", "body", "-q", ".body")
        if p.returncode:
            raise GitError(f"gh pr view {number}: {p.stderr.strip()}")
        return p.stdout.removesuffix("\n")


Landing = collections.namedtuple("Landing", "code generated commit")


class Item:
    def __init__(self, entry, pr=None, ref=None):
        self.entry, self.pr, self.ref = entry, pr, ref
        self.number = entry.get("pr") if entry.get("state") == "open" else None
        self.state = entry.get("state", "queued")
        self.draft = bool(pr and pr["draft"])
        self.title = (pr or {}).get("title") or entry.get("title") or ""
        self.body = (pr or {}).get("body", "")
        self.created = (pr or {}).get("created") or entry.get("added") or ""
        self.priority = (pr or {}).get("rank") or entry.get("priority")
        self.base_ref = (pr or {}).get("base", "main")
        self.label = f"#{self.number}" if self.number else entry["id"]
        self.sort_id = (self.number or 10 ** 9, entry["id"])

    def __repr__(self):
        return f"<Item {self.label}>"


class Queue:
    """Analysis over the manifest and our open PRs. Every merge check builds trees and commits as
    objects only (merge-tree, commit-tree): no ref or worktree changes."""

    def __init__(self, repo, manifest, github, prs=None):
        self.repo, self.manifest, self.gh = repo, manifest, github
        self.config = {**DEFAULT_CONFIG, **manifest.get("config", {})}
        self.main = rev(repo, MAIN)
        if not self.main:
            raise GitError(f"no {MAIN} in {repo}: fetch first")
        self.patch_ids = PatchIds(repo)
        self.prs = github.open_prs() if prs is None else prs
        self.items, self.stale = [], []
        covered = set()
        for entry in manifest["entries"]:
            if entry["state"] == "open" and entry.get("pr") not in self.prs:
                self.stale.append(entry)  # merged or closed since the last sync
                continue
            if entry["state"] in ("queued", "open"):
                self.items.append(Item(entry, self.prs.get(entry.get("pr")) if entry["state"] == "open" else None))
                covered.add(entry.get("pr"))
        for n, pr in sorted(self.prs.items()):
            if n not in covered:
                entry = new_entry(pr["branch"], id=f"#{n}", pr=n, state="open", title=pr.get("title"))
                entry["needs"] = None  # inferred: see needs()
                self.items.append(Item(entry, pr))
        self.by_number = {i.number: i for i in self.items if i.number}
        self.by_id = {i.entry["id"]: i for i in self.items}
        self._cache = {}
        self._states = {}
        self._active = None

    def memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    # --- commits ---------------------------------------------------------------------------------

    def tip(self, item):
        if item.ref:
            return rev(self.repo, item.ref)
        branch = item.entry["branch"]
        return rev(self.repo, f"refs/remotes/{STORE_REMOTE}/{branch}") or rev(self.repo, f"refs/heads/{branch}")

    def commits(self, item):
        return self.memo(("commits", item.label), lambda: rev_list(self.repo, self.tip(item), f"^{self.main}")
                         if self.tip(item) else [])

    def pids(self, item):
        return self.patch_ids(self.commits(item))

    def owners(self):
        """patch id -> the item that owns it. Of the items carrying it, one that another of them builds
        on (`declared_needs`) owns it, and never one that builds on another of them: a child stacked
        on its parent's commits never owns them, even after the parent was rebased and outgrew it
        (#15184 and draft #15563, 2026-10-18). Otherwise the one with the fewest commits (a child
        carrying its parent's commits, even an older copy of them, has more). An owner without a
        recorded base that holds the commit at the same SHA as a sibling (another carrier building on
        a parent they share, not on the owner) has inherited it: it is that parent's old commit whose
        rebased copy changed patch id, so the parent owns it (#15185 and #15563 on #15184). A commit at
        or below an item's recorded base is never that item's while another item carries it: a parent
        that gained fix commits can outgrow the child stacked on it (#15915 and relay-bg-input-main,
        2026-10-16)."""
        def build():
            holders, below = collections.defaultdict(list), collections.defaultdict(list)
            at, based = {}, set()
            for item in self.items:
                base, tip = item.entry.get("base"), self.tip(item)
                if base and tip and rev(self.repo, base) and is_ancestor(self.repo, base, tip):
                    based.add(item)
                under = set(rev_list(self.repo, base, f"^{self.main}")) if item in based else set()
                for sha, pid in self.pids(item).items():
                    if item not in holders[pid] + below[pid]:
                        (below if sha in under else holders)[pid].append(item)
                        at[pid, item] = sha
            out = {}
            for pid in set(holders) | set(below):
                carriers = set(holders.get(pid, [])) | set(below.get(pid, []))
                needed = set().union(*(self.declared_needs(i) for i in carriers)) & carriers
                pick = [i for i in holders.get(pid) or below[pid] if not self.declared_needs(i) & carriers]
                pick = [i for i in pick if i in needed] or pick or holders.get(pid) or below[pid]
                owner = out[pid] = min(pick, key=lambda i: (len(self.commits(i)), i.sort_id))
                if owner in based:
                    continue
                for other in sorted(carriers - {owner}, key=lambda i: i.sort_id):
                    common = self.declared_needs(owner) & self.declared_needs(other)
                    if common and owner not in self.declared_needs(other) and at[pid, other] == at[pid, owner]:
                        out[pid] = max(common, key=lambda i: (len(self.declared_needs(i)), i.sort_id))
                        break
            return out
        return self.memo("owners", build)

    def declared_needs(self, item):
        """The items `item` builds on, transitively: by its recorded needs, else (an open PR the
        manifest lacks) by its body. Never inferred from shared commits, which ownership decides."""
        def build():
            found, todo = set(), [item]
            while todo:
                cur = todo.pop()
                needs = cur.entry.get("needs")
                if needs is None:
                    needs = [f"#{n}" for n in body_needs(cur.body, set(self.by_number) - {cur.number})]
                for need in needs:
                    number = int(need[1:]) if need.startswith("#") and need[1:].isdigit() else None
                    entry = None if number in self.by_number else find_entry(self.manifest, need)
                    other = self.by_number.get(number) or (entry and self.by_id.get(entry["id"]))
                    if other and other is not item and other not in found:
                        found.add(other)
                        todo.append(other)
            return found
        return self.memo(("declared", item.label), build)

    def main_pids(self, item):
        """Patch ids of commits by our author that `main` gained after `item` left it: our commits a
        maintainer merged (or rebased and merged) since."""
        return self.main_pids_since(self.tip(item))

    def main_pids_since(self, tip):
        if not tip:
            return set()
        mb = git_out(self.repo, "merge-base", self.main, tip)
        email = git_out(self.repo, "config", "user.email")

        def build():
            shas = rev_list(self.repo, "--author", email, self.main, f"^{mb}")
            return set(self.patch_ids(shas).values())
        return self.memo(("main", mb), build)

    def content_on_main(self, tip):
        """Whether every commit of `tip` past main is on main already, as is or by patch id."""
        if not tip:
            return False
        if is_ancestor(self.repo, tip, self.main):
            return True
        shas = rev_list(self.repo, tip, f"^{self.main}")
        pids = self.patch_ids(shas)
        return bool(shas) and len(pids) == len(shas) and set(pids.values()) <= self.main_pids_since(tip)

    def closed_landed(self, number=None, branch=None):
        """A closed need still counts as met when its current content is on main (a maintainer
        cherry-picked it, or we closed it after `plan` said its commits had landed): the entry's branch
        on the fork, else the head GitHub last saw for its latest PR. An older PR of the same entry
        landing says nothing about what was added since."""
        tip = rev(self.repo, f"refs/remotes/{STORE_REMOTE}/{branch}") if branch else None
        if not tip and number:
            tip = self.memo(("pull", number), lambda: self._pull_head(number))
        return self.content_on_main(tip)

    def need_pids(self, item):
        """Patch ids of the commits of `item`'s needs that are no longer open: a needed entry's branch,
        and each merged or closed PR's head as GitHub last saw it. An open need's commits are its own,
        so ownership already sets them apart."""
        pids = set()
        for need in self.needs(item):
            entry = find_entry(self.manifest, need)
            numbers = [int(need[1:])] if need.startswith("#") else []
            if entry:
                numbers = [n for n in [entry.get("pr")] + entry.get("closed_prs", []) if n]
                ref = f"refs/remotes/{STORE_REMOTE}/{entry['branch']}"
                if rev(self.repo, ref):
                    pids |= set(self.patch_ids(rev_list(self.repo, ref, f"^{self.main}")).values())
            for n in numbers:
                if n in self.by_number:
                    continue
                head = self.memo(("pull", n), lambda n=n: self._pull_head(n))
                if head:
                    pids |= set(self.patch_ids(rev_list(self.repo, head, f"^{self.main}")).values())
        return pids

    def _pull_head(self, number):
        if git(self.repo, "fetch", "-q", "origin", f"pull/{number}/head").returncode:
            return None
        return rev(self.repo, "FETCH_HEAD")

    def own(self, item, use_base=True):
        """`item`'s own commits, oldest first: above its recorded base when that is still an ancestor,
        else every commit past main that no other item owns and main or a needed PR does not have."""
        def build():
            tip = self.tip(item)
            if not tip:
                return []
            base = item.entry.get("base")
            if use_base and base and rev(self.repo, base) and is_ancestor(self.repo, base, tip):
                return rev_list(self.repo, tip, f"^{base}", f"^{self.main}")
            pids, owners = self.pids(item), self.owners()
            foreign = self.main_pids(item) | self.need_pids(item)
            return [s for s in self.commits(item)
                    if s not in pids or (pids[s] not in foreign and owners.get(pids[s], item) is item)]
        return self.memo(("own", item.label, use_base), build)

    def base(self, item):
        """The commit `item`'s own commits sit on: the recorded base while it is an ancestor of the tip,
        else the parent of the first own commit when the own commits are the branch's top. None when
        they are interleaved with commits of others."""
        def build():
            tip = self.tip(item)
            if not tip:
                return None
            recorded = item.entry.get("base")
            if recorded and rev(self.repo, recorded) and is_ancestor(self.repo, recorded, tip):
                return rev(self.repo, recorded)
            own = self.own(item, use_base=False)
            if not own:
                return git_out(self.repo, "merge-base", self.main, tip)
            candidate = rev(self.repo, f"{own[0]}^")
            if candidate and set(rev_list(self.repo, tip, f"^{candidate}", f"^{self.main}")) == set(own):
                return candidate
            return None
        return self.memo(("base", item.label), build)

    def merges(self, item):
        """Merge commits between `item`'s base and tip: the branch merged main (or a need) after it
        was branched. Then base..tip also holds what those merges brought in, so landing and
        `advance` take its own commits alone (`own`), never the base..tip diff or a replay from base."""
        def build():
            tip, base = self.tip(item), self.base(item)
            return git_out(self.repo, "rev-list", "--merges", tip, f"^{base}").split() if tip and base else []
        return self.memo(("merges", item.label), build)

    def carried(self, item):
        """{other item: count} of `item`'s commits that another item owns, plus {"main": count} of
        commits main already has under another SHA."""
        out = collections.Counter()
        owners, on_main = self.owners(), self.main_pids(item)
        for pid in self.pids(item).values():
            if pid in on_main:
                out["main"] += 1
            elif owners.get(pid, item) is not item:
                out[owners[pid]] += 1
        return out

    # --- landing on main ---------------------------------------------------------------------------

    def landing(self, item, whole=None):
        """How `item` lands on main: for an open PR, the whole branch as the maintainer would merge it;
        for a queued change, its own commits alone (what opens once it is rebased). A queued change
        whose needs have not merged is judged on main with those needs merged in (`onto`): its own
        commits sit on them, so their changes are no conflict of its own. Such a landing has no
        commit, since it does not land on main alone yet."""
        whole = item.state == "open" if whole is None else whole

        def build():
            tip = self.tip(item)
            if not tip:
                return Landing(["(branch missing on the fork)"], [], None)
            if whole:
                tree, paths = merge_tree(self.repo, self.main, tip)
                code, generated = classify(paths)
                return Landing(code, generated, commit_tree(self.repo, tree, self.main) if not code else None)
            onto, held = self.onto(item)
            base = self.base(item)
            if base and not self.merges(item):
                tree, paths = merge_tree(self.repo, onto, tip, base=base)
                code, generated = classify(paths)
                land = Landing(code, generated, commit_tree(self.repo, tree, onto) if not code else None)
            else:
                land = self._replay(item, onto)
            if onto == self.main:
                return land
            theirs = {p for _, paths in held for p in paths}
            return Landing([p for p in land.code if p not in theirs], land.generated, None)
        return self.memo(("landing", item.label, whole), build)

    def onto(self, item):
        """(commit, [(need label, paths)]): main with the tips of `item`'s unmerged needs merged in,
        and for each need that conflicts with main there, the code paths it conflicts in. `landing`
        leaves those paths out of `item`'s own conflict and `select` names the need instead (a
        draft need has no row of its own to show it). main alone once every need has merged."""
        def build():
            cur, held = self.main, []
            for need, met, _ in self.need_status(item):
                other = None if met else self.by_id.get(need) or (
                    self.by_number.get(int(need[1:])) if re.fullmatch(r"#\d+", need) else None)
                tip = self.tip(other) if other else None
                if tip and not is_ancestor(self.repo, tip, cur):
                    tree, paths = merge_tree(self.repo, cur, tip)
                    code, _ = classify(paths)
                    if code:
                        held.append((other.label, code))
                    cur = commit_tree(self.repo, tree, cur)
            return cur, held
        return self.memo(("onto", item.label), build)

    def _replay(self, item, onto):
        cur, generated = onto, []
        for sha in self.own(item):
            tree, paths = merge_tree(self.repo, cur, sha, base=f"{sha}^")
            code, gen = classify(paths)
            if code:
                return Landing(code, generated + gen, None)
            generated += gen
            cur = commit_tree(self.repo, tree, cur)
        return Landing([], list(dict.fromkeys(generated)), cur)

    def files(self, item, whole=None):
        """Paths `item` changes on main: the landed diff, or (when it does not land) the paths its
        commits touch; never a base..tip diff, which would include a `main` merged into the branch."""
        land = self.landing(item, whole)
        if land.commit:
            out = git_out(self.repo, "diff", "--name-only", "--no-renames", "-z", self.main, land.commit)
        else:
            whole = item.state == "open" if whole is None else whole
            shas = self.commits(item) if whole else self.own(item)
            out = git(self.repo, "log", "--no-walk=unsorted", "--stdin", "--name-only", "--no-renames", "-z",
                      "--format=",
                      input="\n".join(shas) + "\n").stdout if shas else ""
        return {p.strip("\n") for p in out.split("\0") if p.strip()}

    def pair(self, a, b, whole=None):
        """(code, generated) paths that conflict when both land on main, or None."""
        key = ("pair",) + tuple(sorted((a.label, b.label))) + (whole,)

        def build():
            # Renames count from both ends (`files` lists the old path too), so two renames of one file meet.
            shared = {f for f in self.files(a, whole) & self.files(b, whole) if not f.endswith("CHANGELOG.md")}
            if not shared:
                return None
            la, lb = self.landing(a, whole), self.landing(b, whole)
            if la.commit and lb.commit:
                _, paths = merge_tree(self.repo, la.commit, lb.commit, base=self.main)
            else:
                # Raw heads also "conflict" on what main changed between their bases: keep shared paths.
                _, paths = merge_tree(self.repo, self.tip(a), self.tip(b))
                paths = [p for p in paths if p in shared]
            code, generated = classify(paths)
            return (code, generated) if code or generated else None
        return self.memo(key, build)

    # --- what GitHub shows ----------------------------------------------------------------------------
    # GitHub's mergeability ignores the `merge=union` `.gitattributes` sets for CHANGELOGs, so a branch
    # our checks land cleanly can read CONFLICTING there in a CHANGELOG alone (#16119, #15105, #15184
    # on 2026-10-18). Information only: no rule counts it and it is no push of its own; the next push
    # we need anyway rebases onto main (Cadence).

    def github(self, item, whole=None):
        """CHANGELOGs GitHub reads `item`'s branch, as pushed, as conflicting with main in, when it
        lands on main alone with no code conflict; else []."""
        def build():
            if not self.landing(item, whole).commit:
                return []
            return github_changelog_conflicts(self.main, self.tip(item), cwd=self.repo)
        return self.memo(("github", item.label, whole), build)

    def github_pair(self, a, b, whole=None):
        """CHANGELOGs GitHub reads the second of `a` and `b` to merge as conflicting in once the first
        has merged, when both land on main with no code conflict; else []."""
        key = ("github-pair",) + tuple(sorted((a.label, b.label))) + (whole,)

        def build():
            la, lb = self.landing(a, whole), self.landing(b, whole)
            logs = {f for f in self.files(a, whole) & self.files(b, whole) if f.endswith("CHANGELOG.md")}
            if not (la.commit and lb.commit and logs):
                return []
            return github_changelog_conflicts(la.commit, lb.commit, cwd=self.repo, base=self.main, attrs=self.main)
        return self.memo(key, build)

    def github_rows(self, items, whole=None):
        """{label: {"main": [CHANGELOGs], "pairs": [(other label, [CHANGELOGs])]}} over `items`, which
        land together: pairs that carry one another's commits or conflict in code are left out (`pair`
        reports those)."""
        out = {i.label: {"main": self.github(i, whole), "pairs": []} for i in items}
        for x, a in enumerate(items):
            for b in items[x + 1:]:
                if self.carried(a).get(b) or self.carried(b).get(a) or (self.pair(a, b, whole) or [[]])[0]:
                    continue
                hit = self.github_pair(a, b, whole)
                if hit:
                    out[a.label]["pairs"].append((b.label, hit))
                    out[b.label]["pairs"].append((a.label, hit))
        return out

    # --- one build unit ---------------------------------------------------------------------------

    def units(self, item):
        return self.memo(("units", item.label), lambda: build_units(self.files(item)))

    def sharing(self, item, others):
        """[(other, units)] for each of `others` that changes a crate or package `item` changes. One
        carrying the other's commits is left out: a need is built on, not merged beside."""
        mine, found = set(self.units(item)), []
        for other in others:
            if other is item or self.carried(item).get(other) or self.carried(other).get(item):
                continue
            shared = sorted(mine & set(self.units(other)))
            if shared:
                found.append((other, shared))
        return found

    def code_id(self, item):
        """The patch id of what `item` changes outside CHANGELOGs since it left main: the same
        through a clean rebase and the CHANGELOG link `open` adds, new once its code changes.
        Attributes come from main and blob ids are full: a checkout on an old branch lacked
        `rules.json binary`, and patch-id hashes a binary file's abbreviated index line, whose
        length differs by clone, so two hosts recorded different ids for one tip."""
        def build():
            tip = self.tip(item)
            if not tip:
                return None
            left = git_out(self.repo, "merge-base", self.main, tip)
            diff = git(self.repo, f"--attr-source={self.main}", "diff", "--no-color", "--no-renames", "--full-index",
                       left, tip, "--", ".", ":(exclude,glob)**/CHANGELOG.md").stdout
            out = git_out(self.repo, "patch-id", "--stable", input=diff) if diff else ""
            return out.split()[0] if out else None
        return self.memo(("code", item.label), build)

    def built(self, item, other):
        """Whether a `pr-queue built` record on either entry covers `item` and `other` as their code is now."""
        pair = {self.code_id(item), self.code_id(other)}
        return None not in pair and any({r.get("code"), r.get("with_code")} == pair
                                        for e in (item.entry, other.entry) for r in e.get("built") or [])

    def build_steps(self, item, others):
        """[{label, units, built, excluded}] for each of `others` sharing a crate or package with `item`.
        One that itself conflicts with `main` in code is `excluded` (the reason), not built beside: no
        tree holds both until its own rebase, and that rebase is built with everything open then. So
        is one `item` conflicts with in code (an opening over a P2, `opens_over`): no tree merges the
        pair, and whichever merges second rebases onto main and builds then."""
        steps = []
        for o, units in self.sharing(item, others):
            code = self.landing(o).code
            clash = (self.pair(item, o) or [[]])[0]
            excluded = (f"it conflicts with main in {', '.join(code)}" if code else
                        f"it conflicts with this one in {', '.join(clash)}: whichever merges second rebases "
                        "onto main" if clash else "")
            steps.append({"label": o.label, "units": units, "built": self.built(item, o), "excluded": excluded})
        return steps

    # --- needs, ordering, areas -----------------------------------------------------------------

    def needs(self, item):
        """Recorded needs; for an open PR the manifest lacks, the open PRs it carries commits of or
        whose number its body builds on."""
        if item.entry.get("needs") is not None:
            return item.entry["needs"]
        return self.memo(("needs", item.label), lambda: self.inferred_needs(item))

    def inferred_needs(self, item):
        found = [o.label for o in self.carried(item) if o != "main" and o.number]
        found += [f"#{n}" for n in body_needs(item.body, set(self.by_number) - {item.number})]
        return list(dict.fromkeys(found))

    def need_status(self, item):
        """[(need, met, label)] for each need of `item`."""
        out = []
        unknown = [int(n[1:]) for n in self.needs(item) if n.startswith("#") and int(n[1:]) not in self.by_number
                   and not find_entry(self.manifest, n) and int(n[1:]) not in self._states]
        if unknown:
            self._states.update(self.gh.states(unknown))
        for need in self.needs(item):
            if need.startswith("#") and int(need[1:]) in self.by_number:
                other = self.by_number[int(need[1:])]
                out.append((need, False, f"{need} ({'draft' if other.draft else 'open'})"))
                continue
            entry = find_entry(self.manifest, need)
            if entry:
                state = entry["state"]
                if state == "open" and entry.get("pr") not in self.prs:
                    state = self.gh.states([entry["pr"]]).get(entry["pr"], "OPEN").lower()
                label = f"#{entry['pr']}" if entry.get("pr") else entry["id"]
                latest = entry.get("pr") or (entry.get("closed_prs") or [None])[-1]
                met = state == "merged" or (state == "closed" and self.closed_landed(latest, entry["branch"]))
                out.append((need, met, f"{label} ({state}{', content on main' if met and state == 'closed' else ''})"))
            elif need.startswith("#"):
                state = self._states.get(int(need[1:]), "unknown").lower()
                met = state == "merged" or (state == "closed" and self.closed_landed(int(need[1:])))
                out.append((need, met, f"{need} ({state}{', content on main' if met and state == 'closed' else ''})"))
            else:
                out.append((need, False, f"{need} (no such entry)"))
        return out

    def active(self):
        if self._active is None:
            ready = [i.number for i in self.items if i.number and not i.draft]
            self._active = self.gh.active(ready, self.config["active_days"]) if ready else set()
        return self._active

    def order_key(self, item):
        """A PR a maintainer is reviewing first, then P0 > P1 > P2 > P3 > unranked, fixes before
        features, an open PR before a queued change, older first."""
        return (0 if item.number in self.active() else 1, RANKS.get(item.priority, 4), kind_rank(item.title),
                0 if item.state == "open" else 1, item.sort_id)

    def area(self, item):
        return item.entry.get("area") or self.memo(
            ("area", item.label), lambda: infer_area(sorted(self.files(item)), self.config["areas"]))

    def ready_items(self):
        return [i for i in self.items if i.state == "open" and not i.draft]

    # --- opening over an old P2 (shaping.md, Open-PR rule 3) -----------------------------------------

    def open_for(self, item):
        """How long `item`'s PR has been open (a timedelta), or None without a creation time."""
        try:
            return now() - datetime.datetime.fromisoformat(item.created.replace("Z", "+00:00"))
        except ValueError:
            return None

    def opens_over(self, item, other):
        """Whether queued `item` may open despite a code conflict with open ready `other`: `item`
        ranks P0 or P1, and `other` is P2 (roboomp's label, else its entry's priority) and has been
        open more than `over_p2_days`. A P1 waiting on an old P2 misses the merge waves, which take
        P0 and P1 first (10-22 09:00Z merged 9 PRs of ours, all P0). `select` applies it only when
        such conflicts are all that holds `item`."""
        age = self.open_for(other)
        return (item.state == "queued" and item.priority in ("P0", "P1") and other.state == "open"
                and not other.draft and bool(other.number) and other.priority == "P2" and age is not None
                and age > datetime.timedelta(days=self.config["over_p2_days"]))

    def paired(self, a, b):
        """Whether one of open PRs `a` and `b` opened over the other (`opens_over`): `open` marks the
        P2's entry with `rebases_after: [the opener's number]`. Their code conflict is accepted:
        whichever merges second rebases onto main."""
        return bool(a.number and b.number) and (a.number in (b.entry.get("rebases_after") or [])
                                                or b.number in (a.entry.get("rebases_after") or []))

    def could_open_over(self, item):
        """Whether queued `item` meets `select`'s other conditions for opening over P2s, as far as a
        check without the whole plan sees: no hold, no unmet need, no conflict with main itself or
        through a need, and each code conflict with an open ready PR one it `opens_over`. A conflict
        with another queued opening shows in plan alone."""
        def build():
            if item.state != "queued" or entry_hold(item.entry):
                return False
            if not all(met for _, met, _ in self.need_status(item)) or self.landing(item).code or self.onto(item)[1]:
                return False
            for other in self.ready_items():
                if other is item or self.carried(item).get(other) or self.carried(other).get(item):
                    continue
                if (self.pair(item, other) or [[]])[0] and not self.opens_over(item, other):
                    return False
            return True
        return self.memo(("over-ok", item.label), build)

    def pair_note(self, item, other):
        """What `item`'s code conflict with `other` is when the rule accepts it, else ""."""
        if self.paired(item, other):
            if other.number in (item.entry.get("rebases_after") or []):
                return f"{other.label} opened over this P2: this one rebases onto main once {other.label} merges"
            return f"this opened over P2 {other.label}: {other.label} rebases onto main once this merges"
        if self.opens_over(item, other) and self.could_open_over(item):
            days = self.open_for(other).days
            return (f"{other.label} is P2, open {days}d: plan opens this over it unless another queued opening "
                    f"conflicts with it, and the one that merges second rebases onto main")
        return ""

    # --- audit and plan -----------------------------------------------------------------------------

    def audit(self, numbers=None, github=True):
        """Rule breaks of our open PRs (shaping.md, *Open-PR rule*): [{number, title, area, draft,
        flags: [(kind, detail)], github}]. `numbers` limits the rows, not the comparisons. `github`
        (`github_rows`, information only, never a flag) is computed unless `github` is False."""
        ours = set(self.by_number)
        ready = sorted(self.ready_items(), key=self.order_key)
        carries = {i.label: self.carried(i) for i in self.items if i.number}
        conflicts = collections.defaultdict(list)
        for x, a in enumerate(ready):
            for b in ready[x + 1:]:
                if carries[a.label].get(b) or carries[b.label].get(a) or self.paired(a, b):
                    continue  # a pair one opened over (`paired`) breaks nothing: the second to merge rebases
                hit = self.pair(a, b, whole=True)
                if hit and hit[0]:
                    conflicts[a.label].append((b.label, hit[0]))
                    conflicts[b.label].append((a.label, hit[0]))
        shown = self.github_rows(ready, whole=True) if github else {}
        rows = []
        for item in sorted((i for i in self.items if i.number), key=lambda i: i.number):
            if numbers and item.number not in numbers:
                continue
            flags = []
            lines = merge_order_lines(item.body, ours - {item.number})
            if lines:
                flags.append(("merge-order", lines))
            others = [(o.label, n) for o, n in carries[item.label].items() if o != "main"]
            if others:
                flags.append(("carries", sorted(others)))
            if carries[item.label].get("main"):
                flags.append(("carries-main", carries[item.label]["main"]))
            land = self.landing(item, whole=True)
            if land.code:
                flags.append(("conflicts-main", land.code))
            if conflicts.get(item.label):
                flags.append(("conflicts-pr", conflicts[item.label]))
            age = self.age_days(item)
            if item.draft and age >= self.config["draft_days"]:
                flags.append(("stale-draft", age))
            if item.base_ref != "main":
                flags.append(("base", item.base_ref))
            gh = shown.get(item.label) or {"main": self.github(item, whole=True) if github else [], "pairs": []}
            rows.append({"number": item.number, "title": item.title, "area": self.area(item), "draft": item.draft,
                         "priority": item.priority, "age_days": age, "generated": land.generated, "flags": flags,
                         "github": gh})
        return rows

    def age_days(self, item):
        try:
            created = datetime.datetime.fromisoformat(item.created.replace("Z", "+00:00"))
        except ValueError:
            return 0
        return (now() - created).days

    def ready_limit(self):
        """(budget, tier, cap): ready events this hour, from the manifest's config `ready_budget`, else
        two under roboomp's cap for the fork owner's tier (`roboomp_tier`; a maintainer has none)."""
        tier, cap = self.gh.tier()
        if self.config.get("ready_budget") is not None:
            return self.config["ready_budget"], tier, cap
        return (99 if cap is None else max(1, cap - 2)), tier, cap

    def plan(self, ready_used=None, github=True):
        """What stays open, what opens, what waits, over open ready PRs and queued changes (`select`).
        Opens past the hourly ready budget show as `next-hour`. Each row's `github` is what GitHub will
        show (`github_rows`, information only); `github=False` skips computing it."""
        limit, tier, cap = self.ready_limit()
        used = self.gh.ready_events_since(now() - datetime.timedelta(hours=1)) if ready_used is None else ready_used
        candidates = [i for i in self.items if i.state == "queued" or (i.state == "open" and not i.draft)]
        drafts = [{"label": i.label, "area": self.area(i), "title": i.title, "age_days": self.age_days(i),
                   "created": i.created} for i in self.items if i.state == "open" and i.draft]
        return {"budget": {"limit": limit, "used": used, "left": max(0, limit - used), "tier": tier, "cap": cap},
                "pause": self.config.get("pause") or None,
                "supervised_opens": omp_config.load().supervised_opens,
                "rows": self.select(candidates, max(0, limit - used), github), "drafts": drafts,
                "stale": [e["id"] for e in self.stale]}

    def select(self, candidates, left, github=True):
        """Open ready PRs first, then queued changes, each greedy in `order_key` order.

        An open PR is kept when its needs have merged, it carries no other open PR's commits and it
        conflicts with no open PR kept before it; a conflict with `main` alone makes it `rebase`
        (rebased in place, still open), anything else `requeue`.
        A queued change opens when its needs have merged, it lands on `main` alone and it conflicts
        with nothing kept or opened; else it waits. A hold on its entry (`entry_hold`: `set --hold`, or
        an unapproved P2 decision under `autonomy.open_p2 = "hold"`) makes it `held` instead, whatever
        else holds: it is chosen for nothing; `awaiting_user` marks a row held only by its P2 decision. Past the hour's ready
        events left it is `next-hour`; while the queue's opening pause is set (`opening_pause`) it is
        `paused` instead of either. A queued change never displaces an open PR: it waits for it.
        One exception (shaping.md, Open-PR rule 3): a queued P0 or P1 held only by
        code conflicts with open P2s it `opens_over` opens anyway, its row's `over` naming them; once
        it is open the pair is `paired` and neither counts the conflict (`note` says which rebases).
        An opening row's `build_with` lists what is kept or opened beside it in one of its crates or
        packages: git sees no conflict there, so the merged tree is built and tested first. A kept or
        opening row's `github` lists the CHANGELOGs GitHub reads as conflicting, with main and with
        the other kept or opening rows once one merges; nothing here counts them. `blocked_by` and
        `needs` list what a waiting row's conflicts and unmet needs name (QUEUE.md reads them)."""
        chosen, rows, opening = [], [], []
        ordered = sorted(candidates, key=self.order_key)
        for item in [i for i in ordered if i.state == "open"] + [i for i in ordered if i.state != "open"]:
            area, reasons = self.area(item), []
            status = self.need_status(item)
            unmet = [label for _, met, label in status if not met]
            if unmet:
                reasons.append("needs " + ", ".join(unmet))
            if item.state == "open":
                needed = {need for need, _, _ in status}
                foreign = [o.label for o in self.carried(item) if o != "main" and o.label not in needed]
                if foreign:
                    reasons.append("carries commits of " + ", ".join(foreign))
            if item.state == "open" and item.base_ref != "main":
                reasons.append(f"targets {item.base_ref}, not main")
            blocked, paired = [], []
            for other in chosen:
                if self.carried(item).get(other) or self.carried(other).get(item):
                    continue  # reported as a need or carried commits above
                hit = self.pair(item, other)
                if hit and hit[0]:
                    (paired if self.paired(item, other) else blocked).append((other, hit[0]))
            need_main = [f"its need {label} conflicts with main in {', '.join(paths)}"
                         for label, paths in self.onto(item)[1]] if item.state != "open" else []
            land = self.landing(item)
            main_conflict = f"conflicts with main in {', '.join(land.code)}" if land.code else ""
            over = []
            hold = entry_hold(item.entry) if item.state != "open" else None
            if (blocked and not reasons and not need_main and not main_conflict and not hold
                    and all(self.opens_over(item, other) for other, _ in blocked)):
                over = [other.label for other, _ in blocked]
            else:
                reasons += [f"conflicts with {other.label} in {', '.join(paths)}" for other, paths in blocked]
            reasons += need_main
            mates = [o for o in self.ready_items() if o is not item and self.paired(item, o)]
            notes = [f"rebases after {o.label} merges" if o.number in (item.entry.get("rebases_after") or [])
                     else f"opened over P2 {o.label}" for o in mates]
            pids = self.pids(item)
            if item.state == "open" and pids and set(pids.values()) <= self.main_pids(item):
                action, reasons = "close", ["its commits are already on main"]
            elif hold:
                action = "held"
                reasons = [f"held: {hold}"] + reasons + ([main_conflict] if main_conflict else [])
            elif reasons or (main_conflict and item.state != "open"):
                reasons += [main_conflict] if main_conflict else []
                action = "requeue" if item.state == "open" else "wait"
            else:
                chosen.append(item)
                if item.state == "open":
                    action = "rebase" if main_conflict else "keep"
                    reasons = [main_conflict] if main_conflict else []
                    if merge_order_lines(item.body, set(self.by_number) - {item.number}):
                        notes.append("drop its merge-order lines")
                else:
                    base = self.base(item)
                    if not base or not is_ancestor(self.repo, base, self.main):
                        notes.append("advance first")
                    if self.config.get("pause"):
                        action = "paused"
                    else:
                        action = "open" if left > 0 else "next-hour"
                        left = max(0, left - 1)
                    opening.append((len(rows), item))
            rows.append({"label": item.label, "number": item.number, "id": item.entry["id"], "state": item.state,
                         "area": area, "priority": item.priority, "title": item.title, "action": action,
                         "active": item.number in self.active(), "reasons": reasons, "note": "; ".join(notes),
                         "over": over, "paired": [o.label for o in mates],
                         "awaiting_user": action == "held" and awaiting_user(item.entry),
                         "p2_decision": item.entry.get("p2_decision"),
                         "blocked_by": [] if over else [o.label for o, _ in blocked],
                         "needs": [need for need, met, _ in status if not met], "created": item.created,
                         "generated": land.generated, "build_with": [], "github": {"main": [], "pairs": []}})
        for at, item in opening:
            rows[at]["build_with"] = self.build_steps(item, chosen)
        if github:
            shown = self.github_rows(chosen)
            for row in rows:
                row["github"] = shown.get(row["label"], row["github"])
        return rows

    # --- ad-hoc checks (precheck) -------------------------------------------------------------------

    def adhoc(self, ref, number=None, branch=None):
        """An item for a ref (precheck on a branch): the open PR or entry it is, else a new one.
        `branch` names it when `ref` is `HEAD` in its worktree (an unpushed fix moves the tip)."""
        remote = re.escape(STORE_REMOTE)
        branch = branch or re.sub(rf"^(refs/remotes/{remote}/|refs/heads/|{remote}/)", "", ref)
        tip = rev(self.repo, ref)
        item = self.by_number.get(number) if number else next(
            (i for i in self.items if i.entry["branch"] == branch or (tip and self.tip(i) == tip)), None)
        if item:
            item.ref = ref
            return item
        item = Item(new_entry(ref, id=f"({ref})", state="queued", needs=[]), ref=ref)
        self.items.append(item)
        self._cache.pop("owners", None)
        return item

    def conflicts_with_ready(self, item):
        """[(label, code, generated, accepted)] for our open ready PRs that conflict with `item` landed on
        main; `accepted` is `pair_note`'s text when the rule lets that code conflict stand, else ""."""
        found = []
        for other in self.ready_items():
            if other is item or self.carried(item).get(other) or self.carried(other).get(item):
                continue
            hit = self.pair(item, other, whole=True)
            if hit:
                found.append((other.label, hit[0], hit[1], self.pair_note(item, other) if hit[0] else ""))
        return found
