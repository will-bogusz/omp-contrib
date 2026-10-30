"""`pr-queue watch`: what changed in the queue since the watcher's last run, kept in the manifest's
top-level `watch` record so `pr-trace --summary` on any host shows it without asking the watcher's host.

The record (all times UTC `...Z`):
  checked         the last successful run; refreshed at least every HEARTBEAT, so a record older
                  than STALE means the watcher stopped
  host, started   where it runs; its first run (the baseline: no events for what was already so)
  openable        {entry id: {since, title}}: queued entries `plan` marks open (or next-hour)
  conflicts       {#N: {since, title, files}}: open ready PRs whose landing on main conflicts in
                  code (omp_pr.classify: CHANGELOGs and generated catalogs apart)
  merged_through  mergedAt of the newest merge of ours seen
  unreleased      {N: {title, merge_commit, merged_at}}: merges no `v*` tag holds yet
  ready           numbers of our open ready PRs, so the next run sees one turn ready or leave
  post_merge      {N: {title, merge_commit, merged_at, findings}}: our merges of the last
                  POST_MERGE_DAYS, and older ones while bot findings posted after the merge stay
                  open (no later main commit took them up, thread not resolved): workflow step 10;
                  a finding's `addressed_by` is our open or merged follow-up PR for it (omp_pr.addressed_by)
  events          [{at, kind, ...}] of the last EVENT_DAYS: merged, openable, unopenable, conflict,
                  released, post-merge

Everything here is pure: the run gathers what it observed (`pr-queue watch`) and `observe` turns
the old record plus that into the new record and its events."""
import datetime

from omp_pr import post_merge_counts

HEARTBEAT = datetime.timedelta(hours=1)
STALE = datetime.timedelta(hours=2)
EVENT_DAYS = 7
SEED_DAYS = 14  # the first run tracks releases of merges this recent
# Codex reviews the head the maintainer pushes right before merging, so its findings land after the merge, within
# hours; a merge this recent is asked for new ones on every run.
POST_MERGE_DAYS = 2
OPENABLE = ("open", "next-hour")


def parse(at):
    return datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))


def fmt(at):
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def observe(prev, cur, at):
    """(record, events) from the last record `prev` (None on the first run) and this run's
    observations `cur`:
      openable   {id: title} queued entries plan marks open or next-hour
      rows       {id: {action, reasons}} plan rows of queued entries
      entries    {id: {state, pr}} manifest entries after sync
      conflicts  {#N: {title, files}} open ready PRs conflicting with main in code
      merges     [{number, title, merged_at, merged_by, merge_commit, maintainer_commits}] our
                 merges from merged_through's day on (SEED_DAYS on the first run)
      releases   {number: first `v*` tag, "unreleased", or None (commit not fetched)} for every
                 unreleased merge and every merge above
      host
      ready      [number] our open ready PRs
      post_merge {number: {title, merge_commit, merged_at, findings}} for each merge
                 `post_merge_candidates` named: its bot findings posted after the merge that no main
                 commit took up (omp_pr.post_merge_review); absent when that query failed, and then
      post_merge_unchecked  [{number, title, merge_commit, merged_at}] the candidates it asked about
    `at` is the run's time (`...Z`)."""
    first = prev is None
    prev = prev or {}
    events = []

    def event(kind, **fields):
        if not first:
            events.append({"at": at, "kind": kind, **fields})

    through = prev.get("merged_through")
    unreleased = {}
    for number, m in prev.get("unreleased", {}).items():
        tag = cur["releases"].get(int(number))
        if tag in ("unreleased", None):
            unreleased[number] = m
        else:
            event("released", number=int(number), title=m["title"], tag=tag)
    for m in sorted(cur["merges"], key=lambda m: m["merged_at"]):
        if through and m["merged_at"] <= through:
            continue
        event("merged", number=m["number"], title=m["title"], merged_by=m["merged_by"],
              maintainer_commits=len(m["maintainer_commits"]))
        tag = cur["releases"].get(m["number"])
        if tag in ("unreleased", None):
            if m.get("merge_commit"):
                unreleased[str(m["number"])] = {"title": m["title"], "merge_commit": m["merge_commit"],
                                                "merged_at": m["merged_at"]}
        else:
            event("released", number=m["number"], title=m["title"], tag=tag)
    merged_at = [m["merged_at"] for m in cur["merges"]] + ([through] if through else [])

    openable = {}
    for ident, title in cur["openable"].items():
        old = prev.get("openable", {}).get(ident)
        openable[ident] = {"since": old["since"] if old else at, "title": title}
        if not old:
            event("openable", id=ident, title=title)
    for ident, old in prev.get("openable", {}).items():
        if ident not in openable:
            event("unopenable", id=ident, title=old["title"], why=unopenable_why(ident, cur))

    conflicts = {}
    for label, hit in cur["conflicts"].items():
        old = prev.get("conflicts", {}).get(label)
        conflicts[label] = {"since": old["since"] if old else at, "title": hit["title"], "files": hit["files"]}
        if not old:
            event("conflict", label=label, title=hit["title"], files=hit["files"])

    # A run whose findings query failed (cur without `post_merge`) keeps the last record's and adds
    # the merges it could not ask about, so the next run asks: `merged_through` moves on regardless.
    post_merge = dict(prev.get("post_merge", {}))
    for m in cur.get("post_merge_unchecked", []) if cur.get("post_merge") is None else []:
        post_merge.setdefault(str(m["number"]), {**{k: m[k] for k in ("title", "merge_commit", "merged_at")},
                                                 "findings": []})
    if cur.get("post_merge") is not None:
        known = {f["url"] for m in post_merge.values() for f in m["findings"]}
        post_merge = {}
        for number, m in sorted(cur["post_merge"].items()):
            findings = [{**{k: f[k] for k in ("bot", "severity", "path", "end", "url")},
                         "addressed_by": f.get("addressed_by")} for f in m["findings"]]
            if findings or parse(at) - parse(m["merged_at"]) <= datetime.timedelta(days=POST_MERGE_DAYS):
                post_merge[str(number)] = {**{k: m[k] for k in ("title", "merge_commit", "merged_at")},
                                           "findings": findings}
            for f in findings:
                if f["url"] not in known:
                    event("post-merge", number=int(number), title=m["title"], **f)

    keep_after = fmt(parse(at) - datetime.timedelta(days=EVENT_DAYS))
    record = {"checked": at, "host": cur["host"], "started": prev.get("started", at), "openable": openable,
              "conflicts": conflicts, "merged_through": max(merged_at) if merged_at else None,
              "unreleased": unreleased, "ready": sorted(cur.get("ready", [])), "post_merge": post_merge,
              "events": [e for e in prev.get("events", []) if e["at"] > keep_after] + events}
    return record, events


def post_merge_candidates(prev, merges, at):
    """[{number, title, merge_commit, merged_at}]: the merges a run asks for post-merge findings,
    those in `prev`'s `post_merge` (findings still open, or merged in the last POST_MERGE_DAYS) and
    those in `merges` from the last POST_MERGE_DAYS, without a merge commit left out."""
    after = fmt(parse(at) - datetime.timedelta(days=POST_MERGE_DAYS))
    out = {int(n): {k: m[k] for k in ("title", "merge_commit", "merged_at")}
           for n, m in (prev or {}).get("post_merge", {}).items()}
    for m in merges:
        if m.get("merge_commit") and m["merged_at"] > after:
            out[m["number"]] = {k: m[k] for k in ("title", "merge_commit", "merged_at")}
    return [{"number": n, **m} for n, m in sorted(out.items())]


def unopenable_why(ident, cur):
    entry = cur["entries"].get(ident)
    if not entry:
        return "left the queue"
    if entry["state"] == "open":
        return f"opened as #{entry['pr']}" if entry.get("pr") else "opened"
    if entry["state"] != "queued":
        return entry["state"]
    row = cur["rows"].get(ident)
    if not row:
        return "plan no longer lists it"
    return f"plan: {row['action']}" + (f" ({'; '.join(row['reasons'])})" if row["reasons"] else "")


def changed(prev, record):
    """Whether the record says more than a fresher `checked`: only then, or once HEARTBEAT has passed,
    is it written (no queue commit every run)."""
    if prev is None:
        return True
    strip = ("checked",)
    return {k: v for k, v in prev.items() if k not in strip} != {k: v for k, v in record.items() if k not in strip}


def heartbeat_due(prev, at):
    return prev is None or parse(at) - parse(prev["checked"]) >= HEARTBEAT


# --- showing it -------------------------------------------------------------------------------------

def clock(at, now):
    """`10:30Z` today, `10-13 10:30Z` another day."""
    t = parse(at)
    return t.strftime("%H:%MZ") if t.date() == now.date() else t.strftime("%m-%d %H:%MZ")


def event_line(e, now):
    when = clock(e["at"], now)
    kind = e["kind"]
    if kind == "merged":
        n = e["maintainer_commits"]
        how = f"{n} maintainer commit{'s' if n != 1 else ''}" if n else "as sent"
        return f"{when} #{e['number']} merged by {e['merged_by']} ({how}): {e['title']}"
    if kind == "openable":
        return f"{when} {e['id']} ready to open: {e['title']}"
    if kind == "unopenable":
        return f"{when} {e['id']} no longer ready to open: {e['why']}"
    if kind == "conflict":
        return f"{when} {e['label']} now conflicts with main in {', '.join(e['files'])}"
    if kind == "released":
        return f"{when} #{e['number']} ships in {e['tag']}: {e['title']}"
    if kind == "post-merge":
        return (f"{when} #{e['number']} drew a post-merge {post_merge_counts([e]).removesuffix(' x1')} finding: "
                f"{e['path']}:{e['end']} {e['url']}")
    return f"{when} {kind}"


def stale(record, now):
    return record is None or now - parse(record["checked"]) > STALE


def headline(record, now, days=2, fetch_error=None):
    """The lines `pr-trace --summary` prints first: the watcher's health when it is stale, what is
    ready to open and since when, open PRs that started conflicting with main, merges with bot
    findings posted after the merge still open, and merges that reached a release in the last
    `days` days. `fetch_error`: why this host could not fetch the queue branch, so the record shown
    is this host's last copy and its age says nothing about the watcher."""
    if record is None:
        return ["Queue watcher: no run recorded in the queue yet (pr-queue watch; contrib/ has timer templates)"]
    lines = []
    if fetch_error:
        lines.append(f"Queue record not refreshed on this host ({fetch_error}); below is this host's copy, "
                     f"as of {clock(record['checked'], now)}")
    elif stale(record, now):
        age = (now - parse(record["checked"])).total_seconds() / 3600
        lines.append(f"Queue watcher silent since {clock(record['checked'], now)} ({age:.0f}h ago): check its timer "
                     f"on {record['host']} (`systemctl --user status pr-queue-watch.timer`, or `launchctl print "
                     f"gui/$(id -u)/dev.omp-contrib.pr-queue-watch` on macOS); below is as of then")
    groups = {}
    for ident, o in sorted(record["openable"].items(), key=lambda kv: (kv[1]["since"], kv[0])):
        groups.setdefault(o["since"], []).append(ident)
    if groups:
        lines.append("Ready to open " + "; ".join(f"since {clock(since, now)}: {', '.join(ids)}"
                                                  for since, ids in groups.items()))
    else:
        lines.append("Nothing ready to open")
    lines[-1] += f"  (queue watch, {record['host']} {clock(record['checked'], now)})"
    for label, c in sorted(record["conflicts"].items(), key=lambda kv: kv[1]["since"]):
        lines.append(f"{label} conflicts with main since {clock(c['since'], now)} in {', '.join(c['files'])}")
    merges = sorted((int(n), m) for n, m in record.get("post_merge", {}).items())
    open_findings = [(n, still) for n, m in merges if (still := [f for f in m["findings"] if not f.get("addressed_by")])]
    if open_findings:
        lines.append("Post-merge findings open (fix each as a follow-up off main, workflow step 10): " + "; ".join(
            f"#{n} {post_merge_counts(still)}" for n, still in open_findings))
    followed = [f"#{n} by #{pr}" for n, m in merges
                for pr in dict.fromkeys(f["addressed_by"] for f in m["findings"] if f.get("addressed_by"))]
    if followed:
        lines.append("Post-merge findings with a follow-up PR open or merged: " + ", ".join(followed))
    after = fmt(now - datetime.timedelta(days=days))
    released = [e for e in record["events"] if e["kind"] == "released" and e["at"] > after]
    if released:
        lines.append("Newly released: " + ", ".join(f"#{e['number']} in {e['tag']}" for e in released))
    return lines


def summary(record, now, days=2, fetch_error=None):
    """`pr-trace --summary --json`'s `queue_watch`: the headline lines, the last day's events as
    lines, and the record's current state."""
    after = fmt(now - datetime.timedelta(days=1))
    return {"checked": (record or {}).get("checked"), "host": (record or {}).get("host"),
            "stale": stale(record, now), "fetch_error": fetch_error,
            "lines": headline(record, now, days, fetch_error),
            "recent": [event_line(e, now) for e in (record or {}).get("events", []) if e["at"] > after],
            "openable": [{"id": i, **o} for i, o in sorted((record or {}).get("openable", {}).items())],
            "conflicts": [{"label": k, **c} for k, c in sorted((record or {}).get("conflicts", {}).items())],
            "post_merge": [{"number": int(n), **m} for n, m in sorted((record or {}).get("post_merge", {}).items())
                           if m["findings"]]}
