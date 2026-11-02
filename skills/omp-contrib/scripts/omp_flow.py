"""Step records for one contribution: what happened, what comes next, and the gates `pr-queue add`
checks (scripts/contrib is the CLI).

Code owns the procedure, the model owns judgement. Measured 2026-10-30: Haiku 5.5 wrote a correct fix
and then skipped the duplicate scan, the review, precheck and the queue, once ending on "should I
run pr-queue add?". So the steps a contribution has taken are recorded here (or derived from git,
the review stamp and the queue), `next` names the one step left, and `pr-queue add` refuses until the
chain before it is done.

Records are local, never pushed: one JSON file per contribution under the clone's shared git dir
(`<git common dir>/omp-contrib/<id>.json`), so every worktree and later session sees them; `active`
names the contribution in progress. Precheck results sit beside them per branch (`prechecks/`), like
review-stamp's `omp-reviews/`.
"""
import datetime
import hashlib
import json
import os
import re
import shlex
import subprocess
import time

import omp_config
from omp_pr import is_test_path, last_review

SCRIPTS = os.path.dirname(os.path.realpath(__file__))
SKILL = os.path.dirname(SCRIPTS)
MAIN = "origin/main"
STOP_REASONS = ("duplicate", "not-a-bug", "not-omp", "user-declined", "other")
OWN_WORDS_QUESTION = ("In a sentence, in your words: what should change, and why does it matter to you? "
                      "It goes first in the PR, verbatim.")
VERDICT = re.compile(r"^(none|(duplicate|related):#\d+(,#\d+)*)$")
# A worktree on a branch_prefix branch with no record counts as an unrecorded contribution when it
# was made this recently: older ones are someone's parked work, not this session's.
RECENT_SECONDS = 24 * 3600
ACTORS = ("agent", "user", "wait", "done", "stopped", "none")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def out(cwd, *args):
    p = git(cwd, *args)
    return p.stdout.strip() if p.returncode == 0 else ""


def rev(repo, ref):
    return out(repo, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}") or None


def is_ancestor(repo, a, b):
    return git(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


def script(name):
    return os.path.join(SCRIPTS, name)


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def sha256(text):
    return hashlib.sha256((text or "").encode()).hexdigest()


def slug(text, words=5):
    parts = re.findall(r"[a-z0-9]+", (text or "").lower())
    return "-".join(parts[:words]) or "fix"


def read_text(path):
    with open(path) as f:
        return f.read()


# --- where things live --------------------------------------------------------------------------------

def clone_of(cwd):
    """The oh-my-pi clone `cwd` belongs to (the main clone of a linked worktree), else the configured
    checkout. A clone of anything else does not count: Haiku 5.5 ran `contrib` from the plugin's own
    directory and `next` sent its worktree command to the plugin's repository (2026-11-01)."""
    common = out(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir") if os.path.isdir(cwd) else ""
    if common and os.path.basename(common.rstrip("/")) == ".git":
        main = os.path.dirname(common.rstrip("/"))
        if os.path.isdir(os.path.join(main, "packages", "coding-agent")):
            return main
    return omp_config.load().checkout


def store_dir(repo):
    common = out(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        raise SystemExit(f"{repo} is not a git clone: run this in your oh-my-pi clone or a worktree of it")
    return os.path.join(common, "omp-contrib")


def escape(branch):
    return branch.replace("%", "%25").replace("/", "%2F")


def load_all(repo):
    d = store_dir(repo)
    found = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.endswith(".json"):
            try:
                with open(os.path.join(d, name)) as f:
                    found.append(json.load(f))
            except (OSError, ValueError):
                continue
    return found


def save(repo, rec):
    d = store_dir(repo)
    os.makedirs(d, exist_ok=True)
    rec["updated"] = now()
    path = os.path.join(d, f"{rec['id']}.json")
    with open(path + ".tmp", "w") as f:
        json.dump(rec, f, indent=1)
    os.replace(path + ".tmp", path)
    return rec


def get_active(repo):
    try:
        with open(os.path.join(store_dir(repo), "active")) as f:
            ident = f.read().strip()
    except OSError:
        return None
    return next((r for r in load_all(repo) if r["id"] == ident), None)


def set_active(repo, ident):
    d = store_dir(repo)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "active"), "w") as f:
        f.write(ident + "\n")


def by_branch(repo, branch):
    hits = [r for r in load_all(repo) if r.get("branch") == branch]
    return max(hits, key=lambda r: r.get("started", "")) if hits else None


def body_path(repo, rec):
    """Where `contrib body` writes the PR body: the cache, outside the clone (the checkout guard refuses
    edits anywhere in the checkout, its .git included)."""
    return omp_config.cache_dir("bodies", f"{rec['id']}.md")


def worktrees(repo):
    found, path = {}, None
    for line in out(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/"):
            found[line[18:]] = path
    return found


def current_branch(cwd):
    return out(cwd, "symbolic-ref", "--short", "-q", "HEAD") if os.path.isdir(cwd) else ""


def prefix():
    return omp_config.load().branch_prefix or ""


def unrecorded(repo, since=None):
    """[(branch, worktree)] of worktrees on branch_prefix branches with no record, made recently (or
    after `since`, epoch seconds), newest first."""
    known = {r.get("branch") for r in load_all(repo)}
    pre, cutoff = prefix(), since or time.time() - RECENT_SECONDS
    rows = []
    for branch, path in worktrees(repo).items():
        if not branch.startswith(pre) or branch in known or os.path.realpath(path) == os.path.realpath(repo):
            continue
        try:
            made = os.stat(os.path.join(path, ".git")).st_mtime
        except OSError:
            continue
        if made >= cutoff:
            rows.append((made, branch, path))
    return [(b, p) for _, b, p in sorted(rows, reverse=True)]


def epoch(stamp):
    try:
        return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def resolve(cwd, ident=None):
    """(repo, record or None) for the contribution `cwd` works on: `ident`; else the one recorded for
    the worktree's branch; else the active one, bound to the worktree's branch (or a worktree made
    after it started) when its own branch does not exist yet."""
    repo = clone_of(cwd)
    if ident:
        rec = next((r for r in load_all(repo) if r["id"] == ident), None)
        if not rec:
            raise SystemExit(f"no contribution {ident!r}: `contrib status` lists them")
        return repo, rec
    here = current_branch(cwd)
    rec = by_branch(repo, here) if here else None
    if rec:
        return repo, rec
    rec = get_active(repo)
    if rec and not rec.get("stop") and not rev(repo, f"refs/heads/{rec['branch']}"):
        candidate = here if here.startswith(prefix()) and here and not by_branch(repo, here) else None
        if not candidate:
            found = unrecorded(repo, since=epoch(rec.get("started")))
            candidate = found[0][0] if found else None
        if candidate:
            rec["branch"] = candidate
            save(repo, rec)
    return repo, rec


# --- recording ----------------------------------------------------------------------------------------

def start(repo, subject, topic=None, branch=None, manifest=None):
    subject = norm(subject)
    if not subject:
        raise SystemExit("contrib start needs the subject: what omp got wrong, in a sentence")
    if branch:
        topic = topic or branch.split("/", 1)[-1]
    topic = slug(topic or subject, words=8 if topic else 5)
    branch = branch or prefix() + topic
    existing = by_branch(repo, branch)
    if existing and not existing.get("stop") and not existing.get("queued"):
        existing["subject"] = existing.get("subject") or subject
        existing.pop("pause", None)
        if manifest:
            existing["manifest"] = os.path.abspath(manifest)
        save(repo, existing)
        set_active(repo, existing["id"])
        return existing, False
    ident, n = topic, 2
    taken = {r["id"] for r in load_all(repo)}
    while ident in taken:
        ident, n = f"{topic}-{n}", n + 1
    rec = {"id": ident, "subject": subject, "topic": topic, "branch": branch, "started": now(),
           "manifest": os.path.abspath(manifest) if manifest else None, "dup_scan": None, "repro": None,
           "own_words": [], "review_answered": None, "queued": None, "stop": None}
    save(repo, rec)
    set_active(repo, ident)
    return rec, True


def record_dup_scan(repo, rec, queries, checked, verdict):
    queries = [q.strip() for q in queries if q.strip()]
    if not queries:
        raise SystemExit("--queries: the searches you ran (gh search, git log -S, …), at least one")
    if not VERDICT.match(verdict or ""):
        raise SystemExit("--verdict is none, duplicate:#N or related:#N[,#M]")
    checked = [c.strip() for c in re.split(r"[,\s]+", checked or "") if c.strip()]
    rec["dup_scan"] = {"queries": queries, "checked": checked, "verdict": verdict, "at": now()}
    if verdict.startswith("duplicate:"):
        rec["stop"] = {"reason": "duplicate", "evidence": verdict.split(":", 1)[1], "at": now()}
    return save(repo, rec)


def record_own_words(repo, rec, text):
    text = (text or "").strip()
    if not text:
        raise SystemExit("own-words: the user's sentence, verbatim")
    if norm(text) not in {norm(t["text"]) for t in rec["own_words"]}:
        rec["own_words"].append({"text": text, "at": now()})
    return save(repo, rec)


def record_no_repro(repo, rec, why):
    if not norm(why):
        raise SystemExit("--none / --no-repro needs the reason no reproduction applies (docs or prompt text only)")
    rec["repro"] = {"kind": "none", "why": norm(why), "at": now()}
    return save(repo, rec)


def pause(repo, rec, reason):
    """The user asked to stop for now: `next` hands the step to them until a later record or resume. Not
    `stop`, which ends the contribution."""
    rec["pause"] = {"reason": norm(reason) or "the user asked to pause", "at": now()}
    return save(repo, rec)


def resume(repo, rec):
    """Lift a pause (any later `contrib start`, `record`, `body` or `resume`)."""
    if rec.pop("pause", None):
        save(repo, rec)
    return rec


def stop(repo, rec, reason, evidence):
    if reason not in STOP_REASONS:
        raise SystemExit(f"reason is one of {', '.join(STOP_REASONS)}")
    if not norm(evidence):
        raise SystemExit("--evidence: what shows it (a PR or issue number, a main commit, the code path)")
    rec["stop"] = {"reason": reason, "evidence": norm(evidence), "at": now()}
    return save(repo, rec)


def tail(text, lines=12):
    return "\n".join((text or "").rstrip().splitlines()[-lines:])


def run_shell(cmd, cwd, timeout):
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        text = (e.stdout or b"") + (e.stderr or b"")
        return 124, (text.decode(errors="replace") if isinstance(text, bytes) else text) + f"\n[timed out after {timeout}s]"


def record_repro(repo, rec, before, after=None, timeout=900, log=print):
    """Run the repro for real: `before` with the branch's source changes reverted to the merge base
    (its tests kept) must fail, `after` at HEAD must pass. The worktree must be clean; the revert is
    undone whatever happens."""
    f = facts(repo, rec)
    wt, tip, base = f["worktree"], f["tip"], f["base"]
    if not wt or not tip or not f["commits"]:
        raise SystemExit("record the repro once the fix is committed in the branch's worktree")
    if out(wt, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"{wt} has uncommitted changes: commit them first")
    changed = out(wt, "diff", "--name-only", base, "HEAD").split()
    source = [p for p in changed if not is_test_path(p) and not p.endswith("CHANGELOG.md")]
    if not source:
        raise SystemExit("the branch changes only tests and CHANGELOGs: nothing to revert. A docs or prompt-only "
                         "change records `contrib record repro --none \"<why>\"`")
    after = after or before
    at_base = set(out(wt, "ls-tree", "-r", "--name-only", base, "--", *source).split())
    at_head = set(out(wt, "ls-tree", "-r", "--name-only", "HEAD", "--", *source).split())
    try:
        for path in source:
            full = os.path.join(wt, path)
            if path in at_base:
                git(wt, "checkout", base, "--", path)
            elif os.path.exists(full):
                os.remove(full)
        log(f"before (fix reverted in {len(source)} source file(s), tests kept): {before}")
        before_code, before_out = run_shell(before, wt, timeout)
    finally:
        if at_head:
            git(wt, "checkout", "HEAD", "--", *sorted(at_head))
        for path in sorted(set(source) - at_head):
            git(wt, "rm", "-q", "--cached", "--ignore-unmatch", "--", path)
            if os.path.exists(os.path.join(wt, path)):
                os.remove(os.path.join(wt, path))
    if out(wt, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"{wt} did not return to HEAD cleanly after the revert: check `git status` there")
    log(tail(before_out))
    if before_code == 0:
        raise SystemExit(f"`{before}` passes with the fix reverted, so it does not reproduce the bug: add or "
                         "point to a test that fails without the fix")
    log(f"after (HEAD {tip[:10]}): {after}")
    after_code, after_out = run_shell(after, wt, timeout)
    log(tail(after_out))
    if after_code != 0:
        raise SystemExit(f"`{after}` fails at HEAD (exit {after_code}): the fix does not pass its own test yet")
    rec["repro"] = {"kind": "verified", "before": before, "after": after, "base": base, "sha": tip,
                    "reverted": source, "before_exit": before_code, "after_exit": after_code,
                    "before_tail": tail(before_out, 6), "after_tail": tail(after_out, 6),
                    "before_hash": sha256(before_out), "after_hash": sha256(after_out), "at": now()}
    return save(repo, rec)


def record_repro_unverified(repo, rec, why, before_output, after_output):
    """A repro that cannot run as a command here (a TUI or provider behaviour): the observed outputs'
    hashes, marked unverified."""
    if not norm(why):
        raise SystemExit("--unverified needs why the repro cannot run as a command here")
    texts = []
    for path in (before_output, after_output):
        try:
            with open(path, errors="replace") as fh:
                texts.append(fh.read())
        except (OSError, TypeError):
            raise SystemExit("--unverified needs --before-output FILE and --after-output FILE: what you observed "
                             "on origin/main and at HEAD")
    rec["repro"] = {"kind": "unverified", "why": norm(why), "sha": facts(repo, rec)["tip"],
                    "before_tail": tail(texts[0], 6), "after_tail": tail(texts[1], 6),
                    "before_hash": sha256(texts[0]), "after_hash": sha256(texts[1]), "at": now()}
    return save(repo, rec)


def record_review_answered(repo, rec, evidence):
    f = facts(repo, rec)
    if not norm(evidence):
        raise SystemExit("--evidence: for each must-fix the review raised, why it needs no code change")
    rec["review_answered"] = {"sha": f["tip"], "evidence": norm(evidence), "at": now()}
    return save(repo, rec)


# --- precheck results (written by scripts/precheck) -------------------------------------------------

def precheck_path(repo, branch):
    return os.path.join(store_dir(repo), "prechecks", escape(branch))


def note_precheck(repo, branch, sha, ok, body=None, body_file=None):
    path = precheck_path(repo, branch)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"sha": sha, "ok": bool(ok), "body": sha256(body) if body is not None else None,
                   "body_file": os.path.abspath(body_file) if body_file else None, "at": now()}, f)


def last_precheck(repo, branch):
    try:
        with open(precheck_path(repo, branch)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def own_words_for(repo, branch):
    """The own-words sentences recorded for `branch`, or None when it has no contribution record."""
    rec = by_branch(repo, branch) if branch else None
    return [t["text"] for t in rec["own_words"]] if rec else None


def what_paragraph(body):
    """The first paragraph under `## What`: where the own-words sentence goes."""
    if "## What" not in (body or ""):
        return ""
    return body.split("## What", 1)[1].strip().split("\n\n", 1)[0].strip()


def own_words_match(body, sentences):
    return norm(what_paragraph(body)) in {norm(s) for s in sentences or []}


def rename_branch(repo, old, new):
    """Move a contribution's record and precheck result to a renamed branch (pr-queue set --branch)."""
    rec = by_branch(repo, old)
    if rec:
        rec["branch"] = new
        save(repo, rec)
    path = precheck_path(repo, old)
    if os.path.exists(path):
        os.replace(path, precheck_path(repo, new))


def note_queued(repo, branch, ident, manifest):
    rec = by_branch(repo, branch)
    if rec:
        rec["queued"] = {"id": ident, "manifest": os.path.abspath(manifest) if manifest else None, "at": now()}
        save(repo, rec)


# --- what is true now ---------------------------------------------------------------------------------

def facts(repo, rec, manifest=None):
    branch = rec["branch"]
    tip = rev(repo, f"refs/heads/{branch}")
    main = rev(repo, MAIN)
    base = out(repo, "merge-base", MAIN, tip) if tip and main else None
    commits = int(out(repo, "rev-list", "--count", f"{MAIN}..{tip}") or 0) if tip and main else 0
    wt = worktrees(repo).get(branch)
    dirty = bool(wt and out(wt, "status", "--porcelain", "--untracked-files=no"))
    review = last_review(branch, repo) if tip else None
    review_ok = bool(review and review[0] and rev(repo, review[0]) and is_ancestor(repo, review[0], tip)
                     and not (main and is_ancestor(repo, review[0], main)))
    pre = last_precheck(repo, branch) if tip else None
    return {"branch": branch, "tip": tip, "main": main, "base": base, "commits": commits, "worktree": wt,
            "dirty": dirty, "review": review if review_ok else None, "precheck": pre,
            "precheck_ok": bool(pre and pre.get("ok") and pre.get("sha") == tip),
            "entry": queue_entry(repo, rec, manifest)}


def queue_entry(repo, rec, manifest=None):
    """The queue entry for the contribution's branch, read without fetching: from the manifest it was
    queued in (or `manifest`), else the fork's queue branch as last fetched."""
    queued = rec.get("queued") or {}
    path = manifest or queued.get("manifest") or rec.get("manifest")
    try:
        from omp_queue import Store
        store = Store(repo, path if path else None)
        data, _ = store.load(fetch=False)
    except Exception:  # noqa: BLE001 — the queue is context for `next`, never a reason to fail it
        return None
    entries = [e for e in data.get("entries", []) if e.get("branch") == rec["branch"]
               or (queued.get("id") and e.get("id") == queued["id"])]
    if not entries:
        return None
    entry = dict(entries[-1])
    entry["_manifest"] = os.path.abspath(path) if path else None
    return entry


def pq(rec, manifest=None):
    path = manifest or (rec.get("queued") or {}).get("manifest") or rec.get("manifest")
    return f"{script('pr-queue')}" + (f" --manifest {shlex.quote(path)}" if path else "")


def step(name, actor, why, command="", **extra):
    return {"step": name, "actor": actor, "why": why, "command": command, **extra}


def next_step(repo, rec, manifest=None, cwd=None):
    """The single next required step of the contribution, as {step, actor, why, command, …}."""
    contrib = script("contrib")
    if rec is None:
        found = unrecorded(repo)
        if found:
            branch, wt = found[0]
            return step("start", "agent", f"worktree {wt} on {branch} has no contribution record, so nothing tracks "
                        "its duplicate scan, repro, review or queueing",
                        f"{contrib} start \"<what omp got wrong, in a sentence>\" --branch {branch}")
        return step("none", "none", "no contribution in progress in this clone",
                    f"{contrib} start \"<what omp got wrong, in a sentence>\"")
    base = {"id": rec["id"], "branch": rec["branch"], "subject": rec.get("subject"), "started": rec.get("started")}
    if rec.get("stop"):
        s = rec["stop"]
        return {**base, **step("stopped", "stopped", f"ended: {s['reason']} ({s['evidence']})")}
    if rec.get("pause"):
        return {**base, **step("paused", "user", f"paused: {rec['pause']['reason']}; resume with /contribute or by "
                               "asking", f"{script('contrib')} resume")}
    f = facts(repo, rec, manifest)
    pending = []
    if not rec["own_words"]:
        pending.append(f"own-words sentence: ask the user once, if not asked yet: \"{OWN_WORDS_QUESTION}\" and record "
                       f"the reply verbatim with `{contrib} record own-words \"<their sentence>\"`; never write one "
                       "for them")
    base["pending_user"] = pending

    def ret(*args, **kw):
        return {**base, **step(*args, **kw)}

    checkout = repo
    cfg = omp_config.load()
    wt_path = os.path.join(cfg.worktrees, rec["branch"].split("/", 1)[-1])
    if not rec.get("subject"):
        return ret("start", "agent", "the contribution has no subject recorded",
                   f"{contrib} start \"<what omp got wrong, in a sentence>\" --branch {rec['branch']}")
    if not rec.get("dup_scan"):
        return ret("dup-scan", "agent", "the duplicate scan comes first, before reading code for a fix "
                   f"(references/duplicates.md: merged fixes on {MAIN}, open and closed PRs, issues)",
                   f"{contrib} record dup-scan --queries \"<search 1>\" \"<search 2>\" --checked \"#N,#M\" "
                   "--verdict none|related:#N|duplicate:#N")
    if not f["tip"]:
        return ret("worktree", "agent", "the fix is made in its own worktree from origin/main, never in the checkout "
                   "(workflow.md step 2)", f"git -C {checkout} fetch -q origin main && git -C {checkout} worktree add "
                   f"{wt_path} -b {rec['branch']} {MAIN}")
    if not f["commits"] or f["dirty"]:
        where = f["worktree"] or wt_path
        why = ("uncommitted changes in the worktree" if f["dirty"] and f["commits"] else
               "no commit beyond origin/main yet")
        return ret("fix", "agent", f"{why}: reproduce on origin/main, fix with a test that fails without the fix, "
                   "commit (Conventional Commits, scoped to the package)",
                   f"cd {where} && git add -A && git commit -m \"fix(<package>): <what>\"")
    if not rec.get("repro"):
        return ret("repro", "agent", "the before/after repro is not recorded: contrib runs your test with the fix "
                   "reverted (must fail) and at HEAD (must pass). A docs or prompt-only change: record repro --none "
                   "\"<why>\"; one no command reproduces: --unverified \"<why>\" --before-output F --after-output F",
                   f"cd {f['worktree'] or wt_path} && {contrib} record repro --before \"<test command, e.g. bun test "
                   "packages/<pkg>/test/<file>.test.ts>\"")
    if not f["review"]:
        return ret("review", "agent", "one independent reviewer, briefed with references/review-brief.md, before the "
                   "PR is queued (one round per PR)",
                   f"task: agent \"reviewer\", brief = {os.path.join(SKILL, 'references', 'review-brief.md')} filled in "
                   f"for {rec['branch']} in {f['worktree'] or wt_path}; then, in the worktree, "
                   f"{script('review-stamp')} ready|needs-changes --by <reviewer id> --sha <reviewed sha>")
    sha, verdict = f["review"][0], f["review"][1]
    answered = (rec.get("review_answered") or {}).get("sha") == f["tip"]
    if verdict == "needs-changes" and sha == f["tip"] and not answered:
        return ret("review-fixes", "agent", "the review asked for changes and nothing is committed since: fix each "
                   "must-fix (behaviour fixes with a test that fails on revert) and commit; no second review",
                   f"commit the fixes in {f['worktree']}, or if every finding needs no code change: {contrib} record "
                   "review-answered --evidence \"<why, per finding>\"")
    pre = f["precheck"] or {}
    where = f["worktree"] or wt_path
    if not rec["own_words"]:
        if not f["precheck_ok"]:
            return ret("precheck", "agent", "precheck has not passed at the branch tip: run it on the code now (the body "
                       "waits for the user's own-words sentence) and fix its FIX lines",
                       f"cd {where} && {script('precheck')}")
        return ret("own-words", "user", "the PR body opens with one sentence in the user's own words (upstream "
                   "CONTRIBUTING.md); it is theirs to write, never generated",
                   f"ask the user: \"{OWN_WORDS_QUESTION}\" then {contrib} record own-words \"<their sentence>\"")
    path = pre.get("body_file") if pre.get("body_file") and os.path.exists(pre["body_file"]) else body_path(repo, rec)
    if not f["precheck_ok"] or not pre.get("body"):
        return ret("body", "agent", "precheck has not passed at the branch tip with the PR body. `contrib body` "
                   f"writes {path} opening with the user's sentence under ## What (or use your own body file): keep "
                   "that sentence verbatim, write the rest per references/framing.md, then run precheck on it and fix "
                   "its FIX lines", f"{contrib} body && cd {where} && {script('precheck')} --body {path}", body=path)
    if not os.path.exists(path) or pre["body"] != sha256(read_text(path)):
        return ret("precheck", "agent", f"{path} changed since precheck passed: run precheck on the body you queue",
                   f"cd {where} && {script('precheck')} --body {path}", body=path)
    entry = f["entry"]
    if not entry and not rec.get("queued"):
        dry = " --no-push" if (manifest or rec.get("manifest")) else ""
        return ret("queue", "agent", "everything before the queue is done: queue the branch"
                   + ("" if dry else " (a dry run adds --manifest FILE --no-push)"),
                   f"{pq(rec, manifest)} add {rec['branch']} --title \"fix(<scope>): <what>\" --body {path}{dry}",
                   body=path)
    if not entry:
        return ret("queued", "wait", "queued; its entry is not in the local copy of the queue: "
                   f"`{script('pr-queue')} show {rec['queued']['id']}` fetches it")
    ident = entry["id"]
    state = entry.get("state")
    if entry.get("_manifest"):
        return ret("done", "done", f"queued as {ident} in the dry-run manifest {entry['_manifest']}: only the push "
                   "and `pr-queue open` wait, and a dry run never opens")
    if state == "merged":
        return ret("done", "done", f"merged ({ident})")
    if state == "closed":
        return ret("done", "done", f"closed ({ident})")
    if state == "open":
        return ret("bots", "wait", f"#{entry.get('pr')} is open: the bots review it; settle every finding "
                   "(workflow.md step 7)", f"{script('pr-trace')} --wait-codex {entry.get('pr')}")
    from omp_queue import awaiting_user, entry_hold
    if awaiting_user(entry):
        return ret("p2-decision", "user", f"held for the user's OK on its maintainer decision: {entry['p2_decision']}",
                   f"after the user approves: {script('pr-queue')} approve {ident}")
    hold = entry_hold(entry)
    if hold:
        return ret("held", "wait", f"held: {hold}")
    if cfg.supervised_opens > 0:
        return ret("supervised-open", "user", f"supervised start ({cfg.supervised_opens} open(s) left): show the user "
                   f"the body ({path}), a diff summary and their own-words sentence; if the fix's scope changed from "
                   "what the sentence says, ask them to keep or rewrite it",
                   f"after their OK: {script('pr-queue')} open {ident} --user-approved")
    return ret("open", "wait", f"queued as {ident}: it opens when `pr-queue plan` marks it open (the watcher, or "
               f"`{script('pr-queue')} open {ident}` then)")


def gate(repo, branch, body=None, manifest=None):
    """Why `pr-queue add` must refuse `branch` now (the `contrib next` text), or None."""
    rec = by_branch(repo, branch)
    if not rec:
        rec_any = get_active(repo)
        hint = (f"the active contribution {rec_any['id']} is on {rec_any['branch']}, not {branch}"
                if rec_any else "no contribution is recorded for it")
        return (f"{branch}: {hint}. Record it first:\n  {script('contrib')} start \"<what omp got wrong>\" "
                f"--branch {branch}\nthen follow `contrib next` (duplicate scan, repro, review, own words, precheck).")
    nxt = next_step(repo, rec, manifest)
    pre = last_precheck(repo, branch) or {}
    # An entry queued without a body (`set --body` adds it later) needs precheck passed at the tip alone;
    # `open` reruns precheck on the stored body, own-words check included.
    bodyless_ok = body is None and nxt["step"] == "body" and pre.get("ok") and pre.get("sha") == rev(
        repo, f"refs/heads/{branch}")
    if nxt["step"] != "queue" and not bodyless_ok:
        return "the contribution is not ready to queue:\n" + render(nxt)
    if body is not None and not own_words_match(body, [t["text"] for t in rec["own_words"]]):
        return ("the body's first paragraph under ## What is not the user's recorded own-words sentence. Put it "
                f"there verbatim (`{script('contrib')} body` writes a body that starts with it); never write a "
                "substitute. Recorded:\n" + "\n".join(f"  {t['text']}" for t in rec["own_words"]))
    pre = last_precheck(repo, branch) or {}
    if body is not None and pre.get("body") != sha256(body):
        return (f"precheck passed without this body: run {script('precheck')} --body <the file you queue> in the "
                "worktree, then add again")
    return None


def render(nxt):
    lines = [f"next: {nxt['step']} ({nxt['actor']})" + (f"  [{nxt['id']} on {nxt['branch']}]" if nxt.get("id") else ""),
             f"why: {nxt['why']}"]
    if nxt.get("command"):
        lines.append(f"run: {nxt['command']}")
    for p in nxt.get("pending_user") or []:
        if nxt["step"] != "own-words":
            lines.append(f"pending from the user: {p}")
    return "\n".join(lines)


def status(repo, rec, manifest=None):
    f = facts(repo, rec, manifest)
    lines = [f"{rec['id']}: {rec.get('subject')}", f"  branch     {rec['branch']}"
             + (f" in {f['worktree']}" if f["worktree"] else " (no worktree)")
             + (f", {f['commits']} commit(s) past {MAIN}" if f["tip"] else "")]
    d = rec.get("dup_scan")
    lines.append(f"  dup-scan   {d['verdict']} ({len(d['queries'])} quer{'y' if len(d['queries']) == 1 else 'ies'}, "
                 f"checked {', '.join(d['checked']) or 'none'})" if d else "  dup-scan   -")
    r = rec.get("repro")
    lines.append(f"  repro      {r['kind']}" + (f" at {r['sha'][:10]}: {r['before']}" if r and r.get("before") else
                                                f": {r.get('why')}" if r else "") if r else "  repro      -")
    lines.append(f"  review     {f['review'][1]} at {f['review'][0][:10]} by {f['review'][3] or '?'}" if f["review"]
                 else "  review     -")
    lines.append("  own-words  " + (" | ".join(t["text"] for t in rec["own_words"]) or "-"))
    p = f["precheck"]
    lines.append(f"  precheck   {'pass' if p['ok'] else 'FIX'} at {p['sha'][:10]}"
                 + ("" if p["sha"] == f["tip"] else " (not the tip)") if p else "  precheck   -")
    e = f["entry"]
    lines.append(f"  queue      {e['id']} {e.get('state')}" + (f" (dry run {e['_manifest']})" if e.get("_manifest") else "")
                 if e else "  queue      -")
    if rec.get("stop"):
        lines.append(f"  stopped    {rec['stop']['reason']}: {rec['stop']['evidence']}")
    if rec.get("pause"):
        lines.append(f"  paused     {rec['pause']['reason']} ({rec['pause']['at']})")
    return "\n".join(lines)

