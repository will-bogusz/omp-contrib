"""Shared helpers for the omp-contrib scripts (pr-trace, precheck, pr-queue)."""
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import omp_config

CONFIG = omp_config.load()
REPO = CONFIG.upstream_repo
ME = CONFIG.fork_owner
MAINTAINERS = CONFIG.maintainers
CHECKOUT = CONFIG.checkout


def run(*args, cwd=None):
    return subprocess.run(args, capture_output=True, text=True, cwd=cwd)


# Every GitHub call the scripts make, one JSON line each (`graphql`, `gh_json`): when, host, caller
# (script and subcommand), query, and for our own GraphQL queries GitHub's `rateLimit` cost and the
# points left. A token has 5000 GraphQL points an hour, shared by every agent and the queue watcher
# using it; once it ran out twice in a day and nothing said who spent it. `gh pr view/list`
# are GraphQL too but gh hides their cost, so their lines carry `cost: null`.
SPEND_LOG = omp_config.cache_dir("gh-spend.jsonl")
RATE = "rateLimit{cost remaining resetAt}"


def caller(argv=None):
    """`script subcommand` for the spend log (`pr-queue plan`, `pr-trace --wait-change`): its first
    word that is not an option's value, else its first option; never a PR number or a path."""
    argv = sys.argv if argv is None else argv
    args = argv[1:]
    words = [a for i, a in enumerate(args) if a[:1].isalpha() and not (i and args[i - 1].startswith("-"))]
    sub = (words or [a for a in args if a.startswith("--")] or [""])[0]
    return f"{os.path.basename(argv[0]) if argv else '?'} {sub}".strip()


def log_spend(query, cost=None, remaining=None, reset=None, api="graphql", path=None):
    row = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "host": socket.gethostname().split(".")[0], "caller": caller(), "pid": os.getpid(), "api": api,
           "query": query, "cost": cost, "remaining": remaining, "reset": reset}
    path = path or SPEND_LOG
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:  # one short append per line: concurrent writers do not interleave
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


class GhError(RuntimeError):
    pass


class RateLimited(GhError):
    """GitHub refused the query: the hour's GraphQL points are spent. `reset` is when they return."""

    def __init__(self, reset):
        self.reset = reset
        at = f"{reset:%H:%MZ}, in {max(0, (reset - now_utc()).total_seconds()) // 60:.0f} min" if reset else "within the hour"
        super().__init__(f"GitHub GraphQL budget for {ME} is spent (5000 points an hour, shared by every agent "
                         f"and the queue watcher on this token); it resets at {at}. Retry after that, or see gh-spend.jsonl "
                         "for who spent it")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def query_name(query):
    """A short label for a query: its operation name, else the fields under `repository`/the root."""
    m = re.match(r"\s*(?:query|mutation)\s+(\w+)", query)
    if m:
        return m.group(1)
    body = query[query.index("{") + 1:] if "{" in query else query
    body = re.sub(r"\([^)]*\)", "", body.replace(RATE, ""))
    fields = re.findall(r"(?:^|[{\s])(?:\w+\s*:\s*)?(\w+)\s*\{", body)
    out = [f for f in fields[:2] if f not in ("nodes", "edges", "node")]
    if out and out[0] == "repository":
        rest = sorted(set(re.findall(r"(?:^|[{\s])(?:\w+\s*:\s*)?(pullRequest|issueOrPullRequest|issue|discussion|ref"
                                     r"|search|object)\s*\{", body)))
        return "repository." + "+".join(rest) if rest else "repository"
    return ".".join(out) or "?"


def with_rate(query):
    """`query` asking for GitHub's `rateLimit` too: right after the selection set opens. Mutations
    have no `rateLimit` field and pass unchanged."""
    if "rateLimit" in query or re.match(r"\s*mutation\b", query):
        return query
    i = query.index("{") + 1
    return f"{query[:i]}{RATE} {query[i:]}"


def rate_limited(text):
    """Whether gh's output says the GraphQL points are spent (gh: `GraphQL: API rate limit already
    exceeded for user ID …`; the JSON error type RATE_LIMITED)."""
    return bool(re.search(r"RATE_LIMITED|GraphQL: API rate limit|rate limit already exceeded", text))


def graphql(query, name=None, **variables):
    """`data` of a GraphQL query through `gh api graphql`, logging its cost (SPEND_LOG). Integer
    variables go as `-F`, others as `-f`. `rateLimit` stays in `data` only when `query` asked for
    it. Raises RateLimited when the hour's points are spent, GhError on any other failure."""
    args = ["gh", "api", "graphql", "-f", f"query={with_rate(query)}"]
    for k, v in variables.items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    p = run(*args)
    try:
        body = json.loads(p.stdout)
    except ValueError:
        body = None
    data = body.get("data") if isinstance(body, dict) else None
    keep = "rateLimit" in query
    rate = ((data.get if keep else data.pop)("rateLimit", None) if isinstance(data, dict) else None) or {}
    log_spend(name or query_name(query), rate.get("cost"), rate.get("remaining"), rate.get("resetAt"))
    if rate_limited(p.stdout + p.stderr):
        raise RateLimited(budget()[1])
    if not data:
        raise GhError(f"gh api graphql: {(p.stderr or p.stdout).strip()[:300]}")
    return data


def budget():
    """(points left, reset time) of the GraphQL hour; (None, None) when gh cannot say. A query of
    `rateLimit` alone is not charged (2026-10-19: `used` unchanged over repeated probes). REST
    `rate_limit` is no substitute: its `graphql` bucket read 4300 left at 23:26Z on 2026-10-18
    while GraphQL refused every query until the 00:03Z reset."""
    p = run("gh", "api", "graphql", "-f", "query={rateLimit{remaining resetAt}}",
            "--jq", ".data.rateLimit | [.remaining, .resetAt] | @tsv")
    try:
        left, reset = p.stdout.split()
        return int(left), datetime.datetime.fromisoformat(reset.replace("Z", "+00:00"))
    except ValueError:
        return None, None


def gh_label(args):
    """(api, label) for a `gh` call in the spend log, PR numbers dropped so calls group."""
    if args[:1] == ("api",):
        if args[1:2] == ("graphql",):
            query = next((a.split("=", 1)[1] for a in args if a.startswith("query=")), "")
            return "graphql", query_name(query)
        return "rest", "api " + re.sub(r"/\d+", "/N", args[1].split("?")[0])
    fields = args[args.index("--json") + 1] if "--json" in args[:-1] else ""
    return "graphql", f"{' '.join(args[:2])} {fields}".strip()


def gh_json(*args):
    """JSON output of `gh ARGS`, exiting on failure. An `api graphql` query also asks for its
    `rateLimit`, logged and dropped from the result; one under `--cache` is logged unpriced (a hit
    replays the cached body, so its `rateLimit` would be an old call's)."""
    api, label = gh_label(args)
    cached = "--cache" in args
    query = None if cached else next((a[6:] for a in args if a.startswith("query=")), None)
    asked = query is not None and "rateLimit" in query  # the caller reads it: leave it in
    if query is not None:
        args = tuple(f"query={with_rate(a[6:])}" if a.startswith("query=") else a for a in args)
    out = run("gh", *args)
    try:
        result = json.loads(out.stdout) if out.returncode == 0 else None
    except ValueError:
        result = None
    data = result.get("data") if query is not None and isinstance(result, dict) else None
    rate = ((data.get if asked else data.pop)("rateLimit", None) if isinstance(data, dict) else None) or {}
    log_spend(label + (" (cached)" if cached else ""), rate.get("cost"), rate.get("remaining"), rate.get("resetAt"),
              api=api)
    if out.returncode != 0:
        if rate_limited(out.stdout + out.stderr):
            sys.exit(f"gh {' '.join(args[:2])}: {RateLimited(budget()[1])}")
        sys.exit(f"gh {' '.join(args)}: {out.stderr.strip()}")
    return json.loads(out.stdout) if result is None else result


def has_ref(ref, cwd=CHECKOUT):
    return run("git", "rev-parse", "-q", "--verify", ref, cwd=cwd).returncode == 0


def by_maintainer(commit):
    """Whether a maintainer authored the commit (`gh pr view --json commits` shape). Not "anyone but
    ME": the user may commit under a second account from another machine."""
    return any(a.get("login") in MAINTAINERS for a in commit.get("authors") or [])


# A merged PR's commits never change, so `gh api --cache` keeps them on this host for a day: every
# summary and watcher run listing the same merges asks GitHub once (`pr-trace --summary` spent 28 of
# its 105 points on them on 2026-10-19, one `gh pr view` per merge).
MERGED_COMMITS = ('query{repository(owner:"%s",name:"%s"){pullRequest(number:%d){commits(first:100){nodes{commit{'
                  'messageHeadline authors(first:100){nodes{user{login}}}}}}}}}')


def merged_commits(number):
    """A merged PR's commits as [{messageHeadline, authors: [{login}]}] (by_maintainer's shape)."""
    query = MERGED_COMMITS % (*REPO.split("/"), number)
    nodes = gh_json("api", "graphql", "--cache", "24h", "-f", f"query={query}")["data"]["repository"][
        "pullRequest"]["commits"]["nodes"]
    return [{"messageHeadline": c["commit"]["messageHeadline"],
             "authors": [{"login": (a.get("user") or {}).get("login") or ""} for a in c["commit"]["authors"]["nodes"]]}
            for c in nodes]


def merged_prs(since, after=""):
    """Our PRs merged on or after the date `since` (and after the time `after`, `...Z`), oldest first:
    {number, title, url, merged_at, merged_by, merge_commit, maintainer_commits}, the last being the
    headlines of the non-merge commits a maintainer authored before merging."""
    rows = gh_json("pr", "list", "-R", REPO, "--author", ME, "--state", "merged", "--limit", "100",
                   "--search", f"merged:>={since.isoformat()}", "--json",
                   "number,title,mergedAt,mergedBy,url,mergeCommit")
    out = []
    for pr in sorted((r for r in rows if r["mergedAt"] > after), key=lambda r: r["mergedAt"]):
        # Commits per PR: asking for them in the list query exceeds GitHub's GraphQL node limit.
        added = [c["messageHeadline"] for c in merged_commits(pr["number"])
                 if by_maintainer(c) and not c["messageHeadline"].startswith("Merge ")]
        out.append({"number": pr["number"], "title": pr["title"], "url": pr["url"], "merged_at": pr["mergedAt"],
                    "merged_by": (pr.get("mergedBy") or {}).get("login", "?"), "maintainer_commits": added,
                    "merge_commit": (pr.get("mergeCommit") or {}).get("oid")})
    return out


def first_release(sha, cwd=CHECKOUT):
    """The earliest `v*` tag containing commit `sha`, "unreleased" when no tag does yet, None when the
    commit is not in the checkout (fetch origin with its tags)."""
    if not sha or not has_ref(f"{sha}^{{commit}}", cwd=cwd):
        return None
    tags = run("git", "tag", "--contains", sha, "--list", "v*", "--sort=v:refname", cwd=cwd).stdout.split()
    return tags[0] if tags else "unreleased"


CODEX = "chatgpt-codex-connector"


def bot(node):
    return ((node.get("author") or node.get("user") or {}).get("login") or "").removesuffix("[bot]")


# A finding Codex writes in its review body, with no thread (`codex-code-review-finding`, first seen
# 2026-10-15): "blob/<sha>/<path>#L<a>[-L<b>]" then the badge. All five through 10-18 (#15402,
# #15489, #15574, #15174, #16119) came after the merge, none of 200 PRs had one while open, so a
# future one on an open head would otherwise read as settled.
BODY_FINDING = re.compile(r"https://github\.com/" + re.escape(REPO) + r"/blob/([0-9a-f]{40})/(\S+?)#L(\d+)(?:-L(\d+))?"
                          r"\s*\n\*\*<sub><sub>!\[(P\d) Badge\]")


# Bot findings posted on a PR after it merged: Codex's last pass on the head often ends minutes after
# the merge, and nothing else we run looks at a merged PR again. Our 43 merges 2026-10-15..18 drew 25
# (9 P1) on 10 PRs; the maintainer fixed 22 (afdc8bd10e, e7fe318910, 13d09929b7: 12 on #15562, #15193,
# #15195, #16140; 1a97f79d28 on #16119) and 3 P2s stayed open (references/evidence.md).
POST_MERGE_BOTS = (CODEX, "roboomp")
POST_MERGE_QUERY = '{repository(owner:"%s",name:"%s"){%%s}}' % tuple(REPO.split("/"))
POST_MERGE_PR = """pr%d: pullRequest(number:%d){
  reviews(last:30){nodes{url submittedAt body author{login}}}
  reviewThreads(last:60){nodes{isResolved comments(first:1){nodes{url createdAt body author{login} path
    originalLine originalStartLine originalCommit{oid}}}}}}"""
BADGE = re.compile(r"!\[(P\d) Badge\]")
# A main commit counts as taking a finding up when it names the PR (#N) or rewrites a line within this
# many of the finding's range: of the 22 fixed above, the flagged lines alone caught 12, this span 16,
# the PR named in the commit message the other 6 (none of the 3 open ones matched either).
POST_MERGE_SPAN = 3


def post_merge_findings(node, merged_at):
    """Bot findings in `node` (POST_MERGE_PR) posted after `merged_at`: [{bot, severity, path, start,
    end, commit, url}], from thread openers and from Codex review bodies that carry findings. A
    resolved thread is settled: we resolve one after disproving or declining it in the thread."""
    found = []
    for t in node["reviewThreads"]["nodes"]:
        c = (t["comments"]["nodes"] or [{}])[0]
        if t.get("isResolved"):
            continue
        if bot(c) in POST_MERGE_BOTS and (c.get("createdAt") or "") > merged_at and c.get("originalLine"):
            badge = BADGE.search(c.get("body") or "")
            found.append({"bot": bot(c), "severity": badge.group(1) if badge else "", "path": c["path"],
                          "start": c.get("originalStartLine") or c["originalLine"], "end": c["originalLine"],
                          "commit": (c.get("originalCommit") or {}).get("oid"), "url": c["url"]})
    for r in node["reviews"]["nodes"]:
        if bot(r) not in POST_MERGE_BOTS or (r.get("submittedAt") or "") <= merged_at:
            continue
        for m in BODY_FINDING.finditer(r.get("body") or ""):
            found.append({"bot": bot(r), "severity": m.group(5), "path": m.group(2), "start": int(m.group(3)),
                          "end": int(m.group(4) or m.group(3)), "commit": m.group(1), "url": r["url"]})
    return found


def taken_up(finding, number, merge_commit, merged_at, cwd=CHECKOUT):
    """The origin/main commit after `merge_commit` that names PR `number` or rewrites the finding's lines
    (within POST_MERGE_SPAN), as a short sha; None when no later main commit touched it. A commit
    naming the PR counts only when committed after `merged_at`: another branch's older commits
    reach main through later merges."""
    named = run("git", "log", "--no-merges", "--format=%H", "-E", f"--grep=#{number}([^0-9]|$)",
                f"--since={merged_at}", f"{merge_commit}..origin/main", cwd=cwd).stdout.split()
    if named:
        return named[-1][:10]
    base = finding["commit"]
    if not base or run("git", "merge-base", "--is-ancestor", base, "origin/main", cwd=cwd).returncode:
        base = merge_commit  # a squash merge: the reviewed head is not on main
    lines = f"{max(1, finding['start'] - POST_MERGE_SPAN)},+{finding['end'] - finding['start'] + 1 + 2 * POST_MERGE_SPAN}"
    blame = run("git", "blame", "--reverse", "-s", "-l", "-L", lines, f"{base}..origin/main", "--", finding["path"],
                cwd=cwd)
    if blame.returncode:
        # The range runs past the end of the file: retry with the finding's own lines.
        blame = run("git", "blame", "--reverse", "-s", "-l", "-L", f"{finding['start']},{finding['end']}",
                    f"{base}..origin/main", "--", finding["path"], cwd=cwd)
    tip = run("git", "rev-parse", "origin/main", cwd=cwd).stdout.strip()
    # --reverse names the last commit that still had each line; the next on the path rewrote it.
    last = [s.lstrip("^") for s in (line.split()[0] for line in blame.stdout.splitlines()) if s.lstrip("^") != tip]
    if not last:
        return None
    after = run("git", "rev-list", "--reverse", "--ancestry-path", f"{last[0]}..origin/main", "--", finding["path"],
                cwd=cwd).stdout.split()
    return after[0][:10] if after else last[0][:10]


# Our follow-up PR for a merge's post-merge findings opens its body "Follow-up to #N" (workflow
# step 10; #16552 and #16564 on 2026-10-21), or links the finding itself (a review or thread URL).
FOLLOW_UP = re.compile(r"\bFollow-up to (?:#|https://github\.com/" + re.escape(REPO) + r"/pull/)(\d+)\b", re.I)


def addressed_by(finding, number, prs):
    """The open or merged PR in `prs` ({number, state, body}) that follows up merge `number`
    (FOLLOW_UP) or links `finding`'s URL, lowest number first; None when none does. A follow-up
    closed without merging addresses nothing."""
    link = re.compile(re.escape(finding["url"]) + r"(?![\w-])")
    for pr in sorted(prs, key=lambda p: p["number"]):
        body = pr.get("body") or ""
        if pr["state"] in ("OPEN", "MERGED") and (
                number in map(int, FOLLOW_UP.findall(body)) or link.search(body)):
            return pr["number"]
    return None


def post_merge_review(merges, cwd=CHECKOUT):
    """Adds `post_merge` to each merge: its bot findings posted after the merge, each with `taken_up`
    (the main commit that touched it, or None: still ours to fix) and `addressed_by` (our open or
    merged follow-up PR naming it, addressed_by(); None when there is none, or when taken up). One GraphQL query
    for all, 17 points for 28 merges (2026-10-19), cached on the host for 5 min (`gh api --cache`):
    summaries run by several agents in one round share it, and a finding a few minutes late changes
    nothing. Our PRs created since the oldest such merge are one more `gh pr list`, asked only when a
    finding is not taken up."""
    if not merges:
        return
    query = POST_MERGE_QUERY % " ".join(POST_MERGE_PR % (m["number"], m["number"]) for m in merges)
    repo = gh_json("api", "graphql", "--cache", "5m", "-f", f"query={query}")["data"]["repository"]
    for m in merges:
        m["post_merge"] = [{**f, "taken_up": taken_up(f, m["number"], m["merge_commit"], m["merged_at"], cwd=cwd)
                            if m["merge_commit"] else None}
                           for f in post_merge_findings(repo[f"pr{m['number']}"], m["merged_at"])]
    still = [m for m in merges if any(not f["taken_up"] for f in m["post_merge"])]
    prs = gh_json("pr", "list", "-R", REPO, "--author", ME, "--state", "all", "--limit", "200", "--search",
                  f"created:>={min(m['merged_at'] for m in still)[:10]}", "--json",
                  "number,state,body") if still else []
    for m in merges:
        for f in m["post_merge"]:
            f["addressed_by"] = None if f["taken_up"] else addressed_by(f, m["number"], prs)


def post_merge_counts(findings):
    """"Codex P1 x2, Codex P2 x1" over `findings`, the most severe first."""
    counts = {}
    for f in findings:
        name = {CODEX: "Codex"}.get(f["bot"], f["bot"]) + (f" {f['severity']}" if f["severity"] else "")
        counts[name] = counts.get(name, 0) + 1
    return ", ".join(f"{k} x{v}" for k, v in sorted(counts.items(), key=lambda kv: kv[0].split()[-1]))


# --- What maintainers did with a merged PR of ours (pr-trace --learn) ----------------------------------
# Reading only <merge>^1..<merge>^2 misses most of it: in the week to 2026-11-02, 8 of 13 instructive
# maintainer commits on our PRs landed on main after the merge ("chore: post-merge cleanup for #N",
# "fixup! Merge PR #N", unlabelled rewrites of our lines), some edits sat inside the merge commit, and
# #16910 was closed and squash-landed by H4vC as his own `c80715be71 … (#16910)`.
LEARN_CACHE = omp_config.cache_dir("learn")
LEARN_VERSION = 1
LEARN_DAYS = 7
# A commit touching more files is a repo-wide sweep (H4vC's `0fa4a8a570` touched 3; Can's 10-29 test
# sweep `20a20268d6` dozens): listed apart.
SWEEP_FILES = 50
# Generated or merged-by-union files: a merge's edits there say nothing about our code.
LEARN_SKIP = re.compile(r"(^|/)(CHANGELOG\.md|models\.json|rules\.json|index\.d\.ts)$|(^|/)native/index\.js$")
# Maintainers (`github.maintainers`) as git records them: an author name equal to the login (can1357
# commits as `can1357`), or the login's GitHub noreply address (H4vC commits under another name as
# `…+H4vC@users.noreply.github.com`); roboomp, their bot, as `roboomp`.
_LOGINS = "|".join(map(re.escape, MAINTAINERS)) or "(?!)"
MAINTAINER_NAMES = re.compile(rf"^(?:{_LOGINS})$", re.I)
MAINTAINER_EMAILS = re.compile(rf"^(?:\d+\+)?({_LOGINS})@users\.noreply\.github\.com$", re.I)
BOT_GIT = re.compile(r"^roboomp$", re.I)


def git_author_kind(name, email):
    """"maintainer", "bot" (roboomp) or None for a git author."""
    if MAINTAINER_NAMES.match(name or "") or MAINTAINER_EMAILS.search(email or ""):
        return "maintainer"
    if BOT_GIT.match(name or ""):
        return "bot"
    return None


def git_author_label(name, email):
    """The name --learn shows for a git author: the maintainer's login when the address is their
    GitHub noreply one (a commit under another display name), else the git name."""
    m = MAINTAINER_EMAILS.search(email or "")
    return m.group(1) if m else name


def git_commits(*args, cwd=CHECKOUT):
    """[{sha, name, email, who, at, subject, body, files}] of `git log --no-merges ARGS`; `who` is
    git_author_label's."""
    out = run("git", "log", "--no-merges", "--format=%x00%H%x1f%an%x1f%ae%x1f%cI%x1f%s%x1f%b%x1e", "--name-only",
              *args, cwd=cwd).stdout
    found = []
    for chunk in out.split("\x00")[1:]:
        head, _, files = chunk.partition("\x1e")
        sha, name, email, at, subject, body = (head.split("\x1f", 5) + [""] * 6)[:6]
        found.append({"sha": sha, "name": name, "email": email, "who": git_author_label(name, email), "at": at,
                      "subject": subject, "body": body, "files": [f for f in files.splitlines() if f.strip()]})
    return found


def merge_edits(merge, p1, p2, cwd=CHECKOUT):
    """What the merge commit changed beyond git's own merge of its parents: [{path, kind, new}], from
    `git merge-tree --write-tree p1 p2` against the merge, LEARN_SKIP files left out. `new` counts
    the merge's lines found in neither parent. kind "resolved": a conflicted file settled with lines
    of either side (a resolution against main's concurrent work); "resolved+edited": a conflicted
    file with new lines too; "edited": a file that merged cleanly and was changed anyway."""
    out = run("git", "merge-tree", "--write-tree", "--name-only", "--no-messages", p1, p2, cwd=cwd)
    lines = out.stdout.splitlines()
    if not lines:
        return []
    conflicted = set(lines[1:]) if out.returncode == 1 else set()
    edits = []
    for path in run("git", "diff", "--name-only", "--no-renames", lines[0], merge, cwd=cwd).stdout.split():
        if LEARN_SKIP.search(path):
            continue
        sides = set()
        for parent in (p1, p2):
            sides |= set(run("git", "show", f"{parent}:{path}", cwd=cwd).stdout.splitlines())
        new = [l for l in run("git", "show", f"{merge}:{path}", cwd=cwd).stdout.splitlines()
               if l.strip() and l not in sides]
        kind = ("resolved+edited" if new else "resolved") if path in conflicted else "edited"
        edits.append({"path": path, "kind": kind, "new": len(new)})
    return edits


def rewritten_lines(sha, paths, own, cwd=CHECKOUT):
    """How many lines commit `sha` removed or rewrote in `paths` that `git blame` at its parent
    assigns to a commit in `own`."""
    total = 0
    for path in paths:
        diff = run("git", "diff", "-U0", "--no-color", "--no-renames", f"{sha}^", sha, "--", path, cwd=cwd).stdout
        ranges = [["-L", f"{a},+{b or 1}"] for a, b in re.findall(r"^@@ -(\d+)(?:,(\d+))? \+", diff, re.M)
                  if b != "0"]
        if not ranges:
            continue
        out = run("git", "blame", "--porcelain", *[x for r in ranges for x in r], f"{sha}^", "--", path,
                  cwd=cwd).stdout
        total += sum(1 for m in re.finditer(r"^([0-9a-f]{40}) \d+ \d+", out, re.M) if m.group(1) in own)
    return total


def landed_commit(number, since, cwd=CHECKOUT):
    """The maintainer commit on origin/main whose subject ends `(#number)`, committed on or after the
    time `since`: a closed PR of ours a maintainer squash-landed as his own (#16910, `c80715be71`)."""
    for c in git_commits("-F", f"--grep=(#{number})", f"--since={since}", "origin/main", cwd=cwd):
        if c["subject"].rstrip().endswith(f"(#{number})") and git_author_kind(c["name"], c["email"]):
            return c["sha"]
    return None


def merge_learning(number, merge, landed=False, cwd=CHECKOUT, cache=None, now=None, scan=True):
    """What maintainers did with merged PR `number` (merge commit, or with `landed` the commit a
    maintainer squash-landed it as): {number, merge, merged_at, landed, before, in_merge, after,
    final}. `before`: maintainer and roboomp commits on our branch before the merge; `in_merge`:
    merge_edits (None for a squash); `after`: their commits on origin/main within LEARN_DAYS of the
    merge (its commit time: maintainers merge locally and push hours later) that name the PR (`#N`
    in the message: "post-merge cleanup for #N", "fixup! Merge PR #N", "Follow-up to #N") or rewrite
    lines `git blame` gives to the PR's own commits, as {sha, author, kind, at, subject, lines,
    named, files, sweep}. Cached per merge under LEARN_CACHE; a result whose window has closed is
    final, otherwise the next call scans only main commits new since the last. `scan=False` returns
    the cached result or None without touching git. None when the merge is not in the checkout."""
    cache = cache or LEARN_CACHE
    path = os.path.join(cache, f"{merge}.json")
    try:
        with open(path) as f:
            got = json.load(f)
        if got.get("version") != LEARN_VERSION:
            got = None
    except (OSError, ValueError):
        got = None
    if got and (got["final"] or not scan):
        return got
    if not scan or not has_ref(f"{merge}^{{commit}}", cwd=cwd):
        return got
    if not got:
        parents = run("git", "rev-list", "--parents", "-n1", merge, cwd=cwd).stdout.split()[1:]
        merged_at, name, email = (run("git", "log", "-1", "--format=%cI%x1f%an%x1f%ae", merge, cwd=cwd).stdout.strip()
                                  .split("\x1f") + ["", ""])[:3]
        by = git_author_label(name, email)
        got = {"version": LEARN_VERSION, "number": number, "merge": merge, "merged_at": merged_at, "by": by,
               "landed": landed, "before": [], "in_merge": None, "after": [], "scanned": None, "final": False}
        if len(parents) >= 2 and not landed:
            p1, p2 = parents[:2]
            branch = git_commits(f"{p1}..{p2}", cwd=cwd)
            got["own"] = [c["sha"] for c in branch if not git_author_kind(c["name"], c["email"])]
            got["before"] = [{"sha": c["sha"], "author": c["who"], "subject": c["subject"]} for c in branch
                             if git_author_kind(c["name"], c["email"])]
            got["files"] = run("git", "diff", "--name-only", "--no-renames", f"{p1}...{p2}", cwd=cwd).stdout.split()
            got["in_merge"] = merge_edits(merge, p1, p2, cwd=cwd)
        else:
            got["own"] = [merge]
            got["files"] = run("git", "diff", "--name-only", "--no-renames", f"{merge}^", merge, cwd=cwd).stdout.split()
    start = datetime.datetime.fromisoformat(got["merged_at"])
    end = start + datetime.timedelta(days=LEARN_DAYS)
    tip = run("git", "rev-parse", "origin/main", cwd=cwd).stdout.strip()
    own, files = set(got["own"]), set(got["files"])
    named = re.compile(rf"#{number}(?!\d)")
    span = [f"{merge}..{tip}"] + ([f"^{got['scanned']}"] if got["scanned"] else [])
    for c in reversed(git_commits(*span, f"--since={start.isoformat()}", f"--until={end.isoformat()}", cwd=cwd)):
        kind = git_author_kind(c["name"], c["email"])
        if not kind or c["sha"] in own:
            continue
        lines = rewritten_lines(c["sha"], [f for f in c["files"] if f in files and not LEARN_SKIP.search(f)], own,
                                cwd=cwd)
        says = bool(named.search(c["subject"] + "\n" + c["body"]))
        if lines or says:
            got["after"].append({"sha": c["sha"], "author": c["who"], "kind": kind, "at": c["at"],
                                 "subject": c["subject"], "lines": lines, "named": says, "files": len(c["files"]),
                                 "sweep": len(c["files"]) > SWEEP_FILES})
    got["scanned"] = tip
    got["final"] = (now or now_utc()) > end
    try:
        os.makedirs(cache, exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump(got, f)
        os.replace(path + ".tmp", path)
    except OSError:
        pass
    return got


def learn_line(got):
    """The one-line count --summary prints under a merge: "post-merge: H4vC 2 commit(s) rewrote 30 of
    our lines; roboomp 1 commit(s) rewrote 4 of our lines; 1 sweep; edited in merge", or "" when
    nothing applies."""
    parts, by = [], {}
    for c in got["after"]:
        if not c["sweep"]:
            n, lines = by.get(c["author"], (0, 0))
            by[c["author"]] = (n + 1, lines + c["lines"])
    parts += [f"{who} {n} commit(s) rewrote {lines} of our lines" for who, (n, lines) in sorted(by.items())]
    sweeps = sum(1 for c in got["after"] if c["sweep"])
    parts += [f"{sweeps} sweep(s)"] if sweeps else []
    parts += ["edited in merge"] if any(e["kind"] != "resolved" for e in got.get("in_merge") or []) else []
    return "post-merge: " + "; ".join(parts) if parts else ""



TS = (".ts", ".tsx", ".mts", ".cts")
CODE = TS + (".js", ".mjs", ".cjs", ".rs", ".py", ".swift", ".go")


class Diff:
    """`git diff -U0 base ref`, parsed. `added` {path: [(new line, text)]}, `removed` {path: [text]}
    (files the head still has), `contexts` {path: [hunk context]}, `removed_at` {old path: [(old
    line, hunk context, text)]} (deleted files included), `added_in` {(path, new line): hunk
    context}. The hunk context is the declaration line git prints after `@@`."""

    def __init__(self, base, ref, cwd):
        out = run("git", "diff", "-U0", "--no-color", base, ref, cwd=cwd).stdout
        self.added, self.removed, self.contexts, self.removed_at, self.added_in = {}, {}, {}, {}, {}
        path = old_path = None
        line = old_line = 0
        ctx = ""
        for raw in out.splitlines():
            if raw.startswith("--- "):
                old_path = raw[6:] if raw.startswith("--- a/") else None
            elif raw.startswith("+++ "):
                path = raw[6:] if raw.startswith("+++ b/") else None
            elif raw.startswith("@@"):
                m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", raw)
                old_line, line = int(m.group(1)), int(m.group(2))
                ctx = raw.split("@@", 2)[-1].strip()
                if path:
                    self.contexts.setdefault(path, []).append(ctx)
            elif path and raw.startswith("+"):
                self.added.setdefault(path, []).append((line, raw[1:]))
                self.added_in[(path, line)] = ctx
                line += 1
            elif raw.startswith("-"):
                if path:
                    self.removed.setdefault(path, []).append(raw[1:])
                if old_path:
                    self.removed_at.setdefault(old_path, []).append((old_line, ctx, raw[1:]))
                old_line += 1


def is_test_path(path):
    return "/test/" in path or "/tests/" in path or ".test." in path


def package_of(path):
    if path.startswith("crates/pi-natives/"):
        return "packages/natives"
    m = re.match(r"(packages/[^/]+)/(.+)", path)
    if not m:
        return None
    rest = m.group(2)
    if (rest.startswith(("test/", "tests/", "bench/")) or ".test." in rest
            or rest in ("CHANGELOG.md", "README.md", "package.json")):
        return None
    return m.group(1)


def blamed_commits(diff, base, cwd=CHECKOUT):
    """{package: {sha}}: the commits that wrote the source lines `diff` removes or rewrites, blamed
    at `base`; tests and non-code files left out. Prompt markdown under `src/prompts/` ships as
    the model's instructions, so it counts as code: a rewrite of a prompt line no release ships
    needs no entry, as for code."""
    commits = {}
    for path, lines in diff.removed_at.items():
        pkg = package_of(path)
        shipped = path.endswith(CODE) or ("/src/prompts/" in path and path.endswith(".md"))
        if not pkg or not shipped or is_test_path(path):
            continue
        args, start, end = [], None, None
        for n, _, _ in lines + [(None, None, None)]:
            if start is not None and n != end + 1:
                args += ["-L", f"{start},{end}"]
                start = None
            if n is not None:
                start, end = (n, n) if start is None else (start, n)
        out = run("git", "blame", "--porcelain", *args, base, "--", path, cwd=cwd).stdout
        commits.setdefault(pkg, set()).update(re.findall(r"^([0-9a-f]{40}) \d+ \d+", out, re.M))
    return commits


def changed_files(ref, base="origin/main", cwd=CHECKOUT):
    """Files the branch changes relative to where it left `base`."""
    mb = run("git", "merge-base", base, ref, cwd=cwd).stdout.strip()
    if not mb:
        return set()
    return set(run("git", "diff", "--name-only", mb, ref, cwd=cwd).stdout.split())


def merge_conflicts(a, b, cwd=CHECKOUT):
    """(code, generated) files that conflict when merging refs a and b (`classify`), or None when
    the merge is clean."""
    out = run("git", "merge-tree", "--write-tree", "--name-only", "--no-messages", a, b, cwd=cwd)
    if out.returncode == 0:
        return None
    return classify([p for p in dict.fromkeys(out.stdout.splitlines()[1:]) if p.strip()])


def github_changelog_conflicts(a, b, cwd=CHECKOUT, base=None, attrs=None):
    """CHANGELOGs a plain merge of refs a and b conflicts in: the merge GitHub's mergeability computes,
    which ignores the `merge=union` `.gitattributes` sets for CHANGELOGs. With main at af7b2c50aa
    (2026-10-18) #16119, #15105 and #15184 showed CONFLICTING on GitHub, in
    packages/coding-agent/CHANGELOG.md alone, while `merge_conflicts` found them clean. Only union
    paths differ from `merge_conflicts`, so a CHANGELOG listed here never conflicts in our checks.
    `attrs` is the commit whose attributes apply (default `a`, the side GitHub merges into)."""
    args = ["--merge-base", base] if base else []
    out = run("git", f"--attr-source={_no_union_attrs(attrs or a, cwd)}", "merge-tree", "--write-tree",
              "--name-only", "--no-messages", *args, a, b, cwd=cwd)
    if out.returncode == 0:
        return []
    return [p for p in dict.fromkeys(out.stdout.splitlines()[1:]) if p.endswith("CHANGELOG.md")]


_ATTR_TREES = {}


def _no_union_attrs(ref, cwd):
    """A tree holding `ref`'s `.gitattributes` files with every `merge=union` removed, for
    `git --attr-source`; cached per commit."""
    sha = run("git", "rev-parse", "--verify", f"{ref}^{{commit}}", cwd=cwd).stdout.strip()
    key = (os.path.realpath(cwd or "."), sha)
    if key not in _ATTR_TREES:
        listing = run("git", "ls-tree", "-r", "-z", sha, cwd=cwd).stdout.split("\0")
        rows = []
        for row in listing:
            meta, _, path = row.partition("\t")
            if path.rsplit("/", 1)[-1] != ".gitattributes":
                continue
            text = run("git", "cat-file", "blob", meta.split()[2], cwd=cwd).stdout
            blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=text.replace("merge=union", ""),
                                  capture_output=True, text=True, cwd=cwd).stdout.strip()
            rows.append(f"100644 {blob}\t{path}")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
            subprocess.run(["git", "update-index", "--index-info"], input="".join(r + "\n" for r in rows),
                           capture_output=True, text=True, cwd=cwd, env=env, check=True)
            _ATTR_TREES[key] = subprocess.run(["git", "write-tree"], capture_output=True, text=True, cwd=cwd,
                                              env=env, check=True).stdout.strip()
    return _ATTR_TREES[key]


def open_prs():
    """{number: {"branch", "base", "draft", "created", "body", "title", "rank", "url"}} for every open PR
    of ours; rank is roboomp's label as "P0".."P3", or None."""
    rows = gh_json("pr", "list", "-R", REPO, "--author", ME, "--state", "open", "--limit", "200",
                   "--json", "number,headRefName,baseRefName,isDraft,createdAt,body,title,labels,url")
    return {r["number"]: {"branch": r["headRefName"], "base": r["baseRefName"], "draft": r["isDraft"],
                          "created": r["createdAt"], "body": r["body"] or "", "title": r["title"], "url": r["url"],
                          "rank": next((l["name"].removeprefix("review:").upper() for l in r["labels"]
                                        if l["name"].startswith("review:")), None)} for r in rows}


# Generated by `bun run gen:compat` / `gen:models` and marked binary in `.gitattributes`, so any two
# branches that regenerate them conflict; the maintainer regenerates at merge in one commit.
GENERATED = {"packages/catalog/src/models.json", "packages/catalog/src/compat/rules.json"}


def classify(paths):
    """(code conflicts, generated-file conflicts) among conflicted `paths`. CHANGELOGs merge with
    `merge=union` (`.gitattributes`), so they never count; the generated catalog files are
    regenerated by the maintainer at merge in one commit (`65124278f7`, `4627619e2e`), so they are
    reported apart from code. pr-queue and pr-trace both judge conflicts by this."""
    code = [p for p in paths if not p.endswith("CHANGELOG.md") and p not in GENERATED]
    return code, [p for p in paths if p in GENERATED]


def changelog_drift(ref, base="origin/main", cwd=CHECKOUT):
    """[(file, entry, section)] for entries the branch adds that land outside `## [Unreleased]` once
    `base` is merged into it. `.gitattributes` sets merge=union for CHANGELOGs, so an entry stays
    next to its old context: after a release cut on `base` it sits under the released heading. A
    `###` heading the union merge repeats inside Unreleased is not drift: `bun run release` runs
    `fix-changelogs`, which merges duplicate category headings (AGENTS.md *Changelog*; 2026-10-29,
    nine PRs flagged for main adding `### Added` to an empty Unreleased after our push)."""
    mb = run("git", "merge-base", base, ref, cwd=cwd).stdout.strip()
    tree = run("git", "merge-tree", "--write-tree", base, ref, cwd=cwd).stdout.split("\n", 1)[0].strip()
    if not mb or not tree:
        return []
    misplaced = []
    for path in sorted(f for f in changed_files(ref, base, cwd) if f.endswith("CHANGELOG.md")):
        diff = run("git", "diff", "-U0", "--no-color", mb, ref, "--", path, cwd=cwd).stdout
        base_text = run("git", "show", f"{base}:{path}", cwd=cwd).stdout
        # Lines base already has are base's, wherever a past merge put them on the branch.
        entries = {l[1:] for l in diff.splitlines() if l.startswith("+- ")} - set(base_text.splitlines())
        for line, section in line_sections(run("git", "show", f"{tree}:{path}", cwd=cwd).stdout):
            if line in entries and not section.startswith("## [Unreleased]"):
                misplaced.append((path, line, section))
    return misplaced


def line_sections(text):
    """[(line, enclosing "## " heading)] for every line of a CHANGELOG."""
    section, sections = "", []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line.strip()
        else:
            sections.append((line, section))
    return sections


VERDICTS = ("ready", "needs-changes")


def review_log(branch, cwd=CHECKOUT):
    """File recording the independent reviews of `branch` (workflow step 3). It lives in the repo's
    shared git dir, so every worktree and `precheck N` run from the main checkout read the same
    record; it is never committed or pushed. The name percent-encodes `%` and `/`, so two branch
    names never share a file."""
    common = run("git", "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd).stdout.strip()
    return os.path.join(common, "omp-reviews", branch.replace("%", "%25").replace("/", "%2F"))


def last_review(branch, cwd=CHECKOUT):
    """(sha, verdict, at, by) of the newest recorded review of `branch`, or None."""
    try:
        with open(review_log(branch, cwd)) as f:
            rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]
    except FileNotFoundError:
        return None
    return tuple((rows[-1] + ["", "", "", ""])[:4]) if rows else None


# --- Rust checks (scripts/rust-check) -----------------------------------------------------------------
# Fork PRs never run CI before the merge (every run waits for maintainer approval), and CI runs no
# Rust on pull requests at all: clippy, rustfmt, `bazel test //crates/...` and the cross-target addon
# builds run on main after the merge. So the maintainer's own build is the first to compile our Rust on another
# OS: #16202's Wayland input failed to compile (bf9fd4bd6a) and #16140's macOS key reroute failed
# clippy (ef7c45bd4b). `rust-check` runs the checks on the host's platform and records them per
# Rust diff; precheck asks for each platform the diff builds differently on.
RUST_PATHSPECS = (":(glob)crates/**/*.rs", ":(glob)**/Cargo.toml", "Cargo.lock", "rust-toolchain.toml")
# A path segment or file that compiles for one OS only: `desktop/macos/`, `oauth_callback/darwin.rs`,
# `applefm/`, `desktop/win32/`, `pi-iso/src/windows_block_clone.rs` (not `winnow_str.rs`).
PLATFORM_PATH = {
    "macos": re.compile(r"(^|/)(macos|darwin|apple|applefm|appkit)(/|_|\.rs$)"),
    "windows": re.compile(r"(^|/)(windows|win32)(/|_|\.rs$)"),
}
PLATFORM_CFG = {
    "macos": re.compile(r"""cfg\((.*\b)?(target_os\s*=\s*"macos"|target_vendor\s*=\s*"apple")"""),
    "windows": re.compile(r"""cfg\((.*\b)?(windows\b|target_os\s*=\s*"windows")"""),
}


def is_rust_path(path):
    return (path.startswith("crates/") and path.endswith(".rs")) or path.endswith("Cargo.toml") or path in (
        "Cargo.lock", "rust-toolchain.toml")


CFG_ATTR = re.compile(r"^\s*#!?\[cfg\((.*)\)\]", re.S)
RUST_NOISE = re.compile(r'//.*$|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)\'')


def gated_lines(text):
    """{line: {platform}}: the lines of a Rust file inside an item a `#[cfg(...)]` naming macOS or
    Windows gates (an inner `#![cfg(...)]` gates the whole file; an attribute may span lines), by
    brace depth with strings and `//` comments blanked; `cfg!(…)` in an expression gates nothing at
    compile time."""
    gated, frames, pending, depth, whole, attr = {}, [], set(), 0, set(), None
    for n, line in enumerate(text.splitlines(), 1):
        if attr is None and re.match(r"^\s*#!?\[cfg\(", line):
            attr = ""
        if attr is not None:
            attr += line + "\n"
            m = CFG_ATTR.match(attr)
            if not m:
                continue
            names = {name for name, rx in PLATFORM_CFG.items() if rx.search(f"cfg({' '.join(m.group(1).split())})")}
            (whole if attr.lstrip().startswith("#!") else pending).update(names)
            attr = None
            continue
        inside = whole | {p for _, names in frames for p in names} | pending
        if inside:
            gated[n] = inside
        code = RUST_NOISE.sub("", line)
        opens, closes = code.count("{"), code.count("}")
        if pending and opens > closes:
            frames.append((depth, pending))
        if pending and (opens or code.rstrip().endswith(";")):
            pending = set()
        depth += opens - closes
        while frames and depth <= frames[-1][0]:
            frames.pop()
    return gated


def rust_platforms(diff, base, ref, cwd=CHECKOUT):
    """The platforms whose build a Rust diff changes: Linux for any (it is CI's Rust platform),
    plus macOS or Windows when it touches a file under that OS's path, adds or removes a
    line gated on it (`#[cfg(target_os = "macos")]`), or changes a line inside an item such a gate
    encloses (read at `ref` for added lines, at `base` for removed ones). Empty when the diff has no
    Rust."""
    paths = [p for p in set(diff.added) | set(diff.removed_at) if is_rust_path(p)]
    if not paths:
        return set()
    found = {"linux"}
    texts = [t for p in paths for _, t in diff.added.get(p, [])] + [
        t for p in paths for _, _, t in diff.removed_at.get(p, [])]
    for name in ("macos", "windows"):
        if any(PLATFORM_PATH[name].search(p) for p in paths) or any(PLATFORM_CFG[name].search(t) for t in texts):
            found.add(name)
    for p in (p for p in paths if p.endswith(".rs")):
        for rev, lines in ((ref, [n for n, _ in diff.added.get(p, [])]),
                           (base, [n for n, _, _ in diff.removed_at.get(p, [])])):
            if lines and found != {"linux", "macos", "windows"}:
                gated = gated_lines(run("git", "show", f"{rev}:{p}", cwd=cwd).stdout)
                found |= {name for n in lines for name in gated.get(n, ())}
    return found


def rust_diff_id(base, ref, cwd=CHECKOUT):
    """`git patch-id --verbatim` of the branch's Rust changes (RUST_PATHSPECS) diffed without context,
    or None without any: a rebase that moves lines around ours or a CHANGELOG commit keeps it, a
    change to any Rust line, whitespace included, makes a new one. Every option a host's config can
    change is pinned (blob ids, renames, prefixes, algorithm, attributes from `base`), so every host
    keys one diff alike: once two definitions live at once keyed one PR's records 7f5ba285fd on one
    host and dab0c05dcf on another."""
    diff = run("git", f"--attr-source={base}", "diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
               "--full-index", "--no-renames", "--diff-algorithm=myers", "--src-prefix=a/", "--dst-prefix=b/",
               base, ref, "--", *RUST_PATHSPECS, cwd=cwd).stdout
    if not diff:
        return None
    p = subprocess.run(["git", "patch-id", "--verbatim"], input=diff, capture_output=True, text=True, cwd=cwd)
    return (p.stdout.split() or [None])[0]


def rust_checks(manifest, diff_id):
    """{platform: {sha, at, host}} recorded by rust-check for the Rust diff `diff_id`."""
    return (manifest.get("rust_checks") or {}).get(diff_id, {}) if diff_id else {}


