#!/usr/bin/env python3
"""Cold read: can a cheap vision model with no project context get each chart's point?

For each chart in DIR/out/manifest.json (written by run.mjs) and each of its layouts (the wide one
and the phone one), RUNS one-shot calls through omp (`omp -p`, no tools, rules, skills, session or
project files, cwd an empty temp dir) see only the light PNG and say what is compared, the takeaway
and which labels were unclear. GRADES more calls grade each answer against the chart's `takeaway`
(chart.mjs) by majority, and flag misread numbers or units. Cached in DIR/out/cold-read.json by
image hash + takeaway + model, so a rerun only calls for what changed.

The model is `models.cold_read` from the omp-contrib config (references/config.md), default omp's
`@smol` role: a cheap vision model, like a reader skimming. It must accept images.

    python3 cold-read.py [--layout wide|narrow] DIR [DIR ...]

A small model is noisy at two reads: act on a miss, a misread, or the same partial twice; read the
answers (cold-read.json) to see what the reader took away instead.
"""
import concurrent.futures as cf
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import omp_config  # noqa: E402

RUNS, GRADES = 2, 3
MODEL = omp_config.load().cold_read_model or "@smol"
EMPTY = tempfile.mkdtemp(prefix="cold-read-")

ASK = """This image is a chart from a software project's pull request. You have no other context.
Answer only with JSON: {"compared": "<what is being compared, one sentence>", "takeaway": "<the chart's main takeaway, one sentence>", "unclear": ["<each label, term or unit you found unclear>"]}. Use an empty list if nothing was unclear."""

GRADE = """Intended takeaway of a chart:
{intended}

A reader who saw only the chart answered:
compared: {compared}
takeaway: {takeaway}

Grade the reader's takeaway against the intended one:
- match: states the same main point (direction and what improved/worsened), even if worded differently or less detailed
- partial: gets part of it (e.g. the direction but not what is compared, or only a secondary point)
- miss: wrong, inverted, or only describes the chart without the point
Also set "misread" to true if the reader states a number or unit that contradicts the intended takeaway (e.g. a percentage where the change is in turns, or a wrong magnitude).
Answer only with JSON: {{"grade": "match|partial|miss", "misread": true|false, "why": "<one short sentence>"}}"""


def omp(args):
    cmd = ["omp", "-p", "--model", MODEL, "--no-tools", "--no-session", "--no-rules", "--no-skills",
           "--no-extensions", "--no-lsp", "--no-title", "--thinking", "low", "--cwd", EMPTY, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=240, cwd=EMPTY).stdout


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {"error": text.strip()[-400:]}
    except json.JSONDecodeError:
        return {"error": m.group(0)[:400]}


def read_once(img, takeaway, cached):
    if cached and len(cached.get("grades", [])) == GRADES:
        return cached
    rec = cached if cached and "takeaway" in cached.get("answer", {}) else {"answer": parse(omp([f"@{img}", ASK]))}
    ans = rec["answer"]
    if "takeaway" not in ans:
        return {**rec, "grade": "error", "grades": []}
    prompt = GRADE.format(intended=takeaway, compared=ans.get("compared", ""), takeaway=ans["takeaway"])
    gs = [parse(omp([prompt])) for _ in range(GRADES)]
    votes = [g.get("grade", "error") for g in gs]
    top = max(set(votes), key=votes.count)
    grade = top if votes.count(top) > 1 else "partial"
    return {**rec, "grades": votes, "grade": grade,
            "misread": sum(bool(g.get("misread")) for g in gs) > GRADES // 2,
            "why": next((g.get("why", "") for g in gs if g.get("grade") == grade), gs[0].get("why", ""))}


def main(dirs, layouts):
    rows = ["| Chart | Layout | Grade per read | Misread | Unclear labels |", "|---|---|---|---|---|"]
    for d in (pathlib.Path(a).resolve() for a in dirs):  # omp runs in an empty dir: paths must be absolute
        out = d / "out"
        manifest = json.loads((out / "manifest.json").read_text())
        cache_f = out / "cold-read.json"
        cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
        jobs, shown = [], []
        for cid, c in manifest["charts"].items():
            for layout in layouts:
                light = c["light"] if layout == "wide" else c.get("narrow", {}).get("light")
                if not light:
                    continue
                img = out / light
                h = hashlib.sha1(img.read_bytes() + c["takeaway"].encode() + MODEL.encode()).hexdigest()[:12]
                jobs += [(cid, img, c["takeaway"], f"{cid}/{h}/{r}", layout) for r in range(RUNS)]
                shown.append((cid, layout))
        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            done = ex.map(lambda j: (j, read_once(j[1], j[2], cache.get(j[3]))), jobs)
            fresh = {j[3]: {**rec, "chart": j[0], "layout": j[4]} for j, rec in done}
        cache_f.write_text(json.dumps({**cache, **fresh}, indent=1))
        for cid, layout in shown:
            recs = [r for r in fresh.values() if r["chart"] == cid and r["layout"] == layout]
            unclear = list(dict.fromkeys(u for r in recs for u in (r["answer"].get("unclear") or [])))
            # A body drafted before its PR has no number yet: name the chart by its directory instead.
            rows.append(f"| {manifest.get('pr') or d.name} {cid} | {layout} | {' / '.join(r['grade'] for r in recs)} | "
                        f"{sum(bool(r.get('misread')) for r in recs)} | {len(unclear)}: {'; '.join(unclear)} |")
    print("\n".join(rows))


if __name__ == "__main__":
    args = sys.argv[1:]
    layouts = ("wide", "narrow")
    if "--layout" in args:
        i = args.index("--layout")
        layouts = (args[i + 1],)
        del args[i:i + 2]
    if not args or not set(layouts) <= {"wide", "narrow"}:
        sys.exit(__doc__)
    main(args, layouts)
