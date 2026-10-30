"""QUEUE.md: the queue manifest as a page on the fork's queue branch (queue.md, *The manifest*).
`Store.update` renders it into every manifest commit, so it never lags `queue.json`. Its groups come
from the last `pr-queue plan` cached in the manifest (`plan_record`): plan's conflict analysis
builds merge trees and asks GitHub for the hour's ready events, too slow and too costly for every
write, so the page stamps when that plan ran. The branch is public: no stored bodies, no paths on
our hosts."""
import datetime
import urllib.parse

from omp_pr import CONFIG, REPO

VIEW = "QUEUE.md"
# The plan row fields the cache keeps: what QUEUE.md shows, nothing GitHub-side (`github`) or bulky.
PLAN_FIELDS = ("id", "label", "number", "state", "area", "priority", "title", "action", "reasons", "note", "over",
               "paired", "blocked_by", "needs", "created")
# A cached plan unchanged for this long is rewritten anyway, so its stamp shows plan still runs.
PLAN_HEARTBEAT = datetime.timedelta(hours=1)
OPENABLE = ("open", "next-hour", "paused")
GROUPS = (("openable", "Openable now"), ("conflict", "Conflict-held"), ("stacked", "Stacked"), ("held", "Held"),
          ("open", "Open PRs"), ("unplanned", "Queued since the last plan"))


def action_label(row):
    """A row's action as plan prints it: an opening over old P2s (shaping.md, Open-PR rule 3) says
    so, `open (over P2 #N)`."""
    return f"{row['action']} (over P2 {', '.join(row['over'])})" if row.get("over") else row["action"]


def plan_record(result, at, host):
    """The manifest's `plan` cache of a `Queue.plan` result: when and where it ran, the ready budget,
    and each row's PLAN_FIELDS."""
    return {"at": at, "host": host, "budget": result["budget"],
            "rows": [{k: r.get(k) for k in PLAN_FIELDS} for r in result["rows"]],
            "drafts": [{"label": d["label"], "created": d.get("created")} for d in result["drafts"]]}


def plan_due(prev, record):
    """Whether `record` should replace the cached plan `prev`: what it says changed, or `prev` is
    older than PLAN_HEARTBEAT."""
    if not prev:
        return True
    same = all(prev.get(k) == record.get(k) for k in ("budget", "rows", "drafts"))
    return not same or parse(record["at"]) - parse(prev["at"]) >= PLAN_HEARTBEAT


def parse(at):
    return datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))


def plan_stamp():
    """A plan's start time to the microsecond: two plans started in one second still order."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def started_no_earlier(record, cached):
    """Whether plan `record` started no earlier than the `cached` one (None: nothing cached), so it
    may replace it: a slow plan never overwrites one started after it."""
    return not cached or parse(cached["at"]) <= parse(record["at"])


def when(at):
    return parse(at).strftime("%Y-%m-%d %H:%MZ")


def age(since, at):
    try:
        delta = parse(at) - parse(since)
    except (AttributeError, ValueError):
        return ""
    return f"{delta.days}d" if delta.days else f"{delta.seconds // 3600}h"


def cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def pr_link(label):
    number = label.lstrip("#")
    return f"[#{number}](https://github.com/{REPO}/pull/{number})"


def compare_link(branch):
    head = urllib.parse.quote(f"{CONFIG.fork_repo.replace('/', ':')}:{branch}", safe="/:")
    return f"[compare](https://github.com/{REPO}/compare/main...{head})"


def need_text(need, entries):
    """A need as a link when it is a PR: `#N`, or an entry id with its PR."""
    if need.startswith("#") and need[1:].isdigit():
        return pr_link(need)
    entry = entries.get(need)
    return f"{cell(need)} ({pr_link(str(entry['pr']))})" if entry and entry.get("pr") else cell(need)


def blocker_text(row):
    """What holds a waiting row: each conflicting PR as a link (a queued opening by its id), and
    main when it conflicts with main itself or through a need."""
    out = [pr_link(b) if b.startswith("#") else cell(b) for b in row.get("blocked_by") or []]
    if any("conflicts with main" in r for r in row.get("reasons") or []):
        out.append("main")
    return ", ".join(out) or cell("; ".join(row.get("reasons") or []))


def group_of(entry, row):
    from omp_queue import entry_hold  # omp_queue imports this module
    if entry["state"] == "open":
        return "open"
    if entry_hold(entry):
        return "held"
    if not row or row["action"] == "held":  # unplanned, or its hold was lifted since the plan
        return "unplanned"
    if row["action"] in OPENABLE:
        return "openable"
    return "stacked" if row.get("needs") else "conflict"


def render(manifest, at):
    """QUEUE.md for `manifest` as of `at` (the write's time)."""
    plan = manifest.get("plan") or {}
    rows = {r["id"]: r for r in plan.get("rows") or []}
    drafts = {d["label"]: d.get("created") for d in plan.get("drafts") or []}
    entries = {e["id"]: e for e in manifest["entries"]}
    owners = any(e.get("owner") for e in manifest["entries"])
    groups = {key: [] for key, _ in GROUPS}
    for e in manifest["entries"]:
        if e["state"] in ("queued", "open"):
            groups[group_of(e, rows.get(e["id"]))].append((e, rows.get(e["id"])))
    # Open PRs of ours the manifest has not imported yet (the next `sync` does).
    known = {e.get("pr") for e in manifest["entries"] if e["state"] == "open"}
    for r in plan.get("rows") or []:
        if r["state"] == "open" and r["id"] not in entries and r.get("number") not in known:
            groups["open"].append(({"id": r["id"], "branch": "", "title": r["title"], "area": r["area"],
                                    "priority": r["priority"], "pr": r["number"], "state": "open"}, r))
    pause = (manifest.get("config") or {}).get("pause")
    out = ["# Our oh-my-pi PR queue", "",
           f"Rendered by `pr-queue` from `queue.json` with every write; last write {when(at)}. Read-only: "
           "change the queue through `pr-queue` alone.", ""]
    out.append(f"**Opening:** paused ({cell(pause)})" if pause else "**Opening:** not paused")
    if plan:
        b = plan["budget"]
        out.append(f"**Ready budget:** {b['used']} of {b['limit']} ready events used in the hour before the last "
                   f"plan, {b['left']} left (plan of {when(plan['at'])} on {cell(plan.get('host'))}; groups below "
                   "are from it, states from the manifest)")
    else:
        out.append("**Ready budget:** unknown: no `pr-queue plan` cached yet")
    counts = [f"{title[0].lower()}{title[1:]} {len(groups[key])}" for key, title in GROUPS
              if groups[key] or key != "unplanned"]
    history = {s: sum(1 for e in manifest["entries"] if e["state"] == s) for s in ("merged", "closed")}
    out.append(f"**Counts:** {', '.join(counts)}; merged {history['merged']}, closed {history['closed']}")
    head = ["id", "title", "area", "priority", "age"]
    for key, title in GROUPS:
        items = groups[key]
        if key == "unplanned" and not items:
            continue
        out += ["", f"## {title} ({len(items)})", ""]
        if not items:
            out.append("none")
            continue
        extra = {"openable": ["plan"], "conflict": ["blocked by"], "stacked": ["needs"], "held": ["hold"],
                 "unplanned": []}.get(key)
        cols = (["PR", "id", "title", "area", "rank", "open", "plan"] if key == "open" else head + extra)
        cols += ["branch"] + (["owner"] if owners else [])
        out += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for e, r in items:
            r = r or {}
            if key == "open":
                label = r.get("label") or f"#{e.get('pr')}"
                plan_cell = "draft" if label in drafts else r.get("action") or ""
                cells = [pr_link(str(e["pr"])), cell(e["id"]), cell(e.get("title") or r.get("title")),
                         cell(e.get("area") or r.get("area")), cell(r.get("priority") or e.get("priority")),
                         age(r.get("created") or drafts.get(label) or e.get("opened") or e.get("added"), at),
                         cell("; ".join(filter(None, [plan_cell, r.get("note")])))]
            else:
                cells = [cell(e["id"]), cell(e.get("title")), cell(e.get("area")), cell(e.get("priority")),
                         age(e.get("added"), at)]
                if key == "openable":
                    cells.append(cell("; ".join(filter(None, [action_label(r), r.get("note")]))))
                elif key == "conflict":
                    cells.append(blocker_text(r))
                elif key == "stacked":
                    cells.append(", ".join(need_text(n, entries) for n in r.get("needs") or []))
                elif key == "held":
                    from omp_queue import entry_hold
                    cells.append(cell(entry_hold(e)))
            cells.append(compare_link(e["branch"]) if e.get("branch") else "")
            if owners:
                cells.append(cell(e.get("owner")))
            out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"
