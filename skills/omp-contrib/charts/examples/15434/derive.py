#!/usr/bin/env python3
"""Derive data.json (everything the visuals plot) from the DriftCap run outputs.

Sources (the study's run outputs, its DriftCap/ folder, copied into source/; not kept in this
example, data.json is the result):
  scores.json                    recall per measured cell (score_driftcap.py output)
  dry/<model>-cap<N>-c5.compactions.json   offline compaction-only runs: frames, image bytes
                                 and truncated history for every compaction 1..5
Cells never sent because their request was byte-identical to another cell (DriftCap report,
"decisions"): Opus cap 40 c1 = cap 17 c1, Opus cap 80 = cap 40 at every cycle, Astra cap 80 c1 =
cap 40 c1. This script re-checks the identity on image bytes and frame counts before reusing.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "source"
MODELS = {"claude-opus-5-5": "Opus 5.5", "gpt-6-astra": "gpt-6-astra"}
CAPS = [17, 40, 80]

scores = json.loads((SRC / "scores.json").read_text())


def per_cycle(model, cap):
    rows = json.loads((SRC / "dry" / f"{model}-cap{cap}-c5.compactions.json").read_text())
    out = {}
    for r in rows:
        if r.get("frameCount") is None:
            continue
        out[r["cycle"]] = {
            "frames": r["frameCount"],
            "imageBytes": r["replayedImageBytes"],
            "truncatedChars": r["truncatedChars"],
            "tokensAfter": r["tokensAfter"],
        }
    assert sorted(out) == [1, 2, 3, 4, 5], (model, cap, sorted(out))
    return out


IDENTICAL = {  # (model, cap, cycle) -> (cap it reuses)
    ("claude-opus-5-5", 40, 1): 17,
    ("claude-opus-5-5", 80, 1): 17,
    ("claude-opus-5-5", 80, 3): 40,
    ("claude-opus-5-5", 80, 5): 40,
    ("gpt-6-astra", 80, 1): 40,
}

data = {"source": {
    "scores": "source/scores.json (DriftCap/score_driftcap.py)",
    "perCycle": "source/dry/*.compactions.json (DriftCap offline runs)",
    "archive": "the study's working folder, archived with the PR's notes (not shipped)",
    "note": "recall measured after 1, 3 and 5 compactions only; frames, bytes and truncated history exist for all 5",
}, "models": {}}

for model, label in MODELS.items():
    cells = {(c["cap"], c["cycles"]): c for c in scores["models"][model]["cells"]}
    pc = {cap: per_cycle(model, cap) for cap in CAPS}
    m = {"label": label, "caps": {}}
    for cap in CAPS:
        recall = {}
        for cyc in (1, 3, 5):
            src_cap = IDENTICAL.get((model, cap, cyc), cap)
            c = cells[(src_cap, cyc)]
            if src_cap != cap:
                a, b = pc[cap][cyc], pc[src_cap][cyc]
                assert (a["frames"], a["imageBytes"]) == (b["frames"], b["imageBytes"]), (model, cap, cyc)
            assert c["imageBytes"] == pc[src_cap][cyc]["imageBytes"], (model, cap, cyc)
            recall[cyc] = {
                "pct": c["accuracy"] * 100,
                "n": c["n"],
                "runs": [v * 100 for v in c["values"]],  # pct is their mean
                "spread": None if c["spread"] is None else c["spread"] * 100,
                "sameAsCap": None if src_cap == cap else src_cap,
            }
        m["caps"][cap] = {
            "recall": recall,
            "perCycle": {k: {**v, "MB": v["imageBytes"] / 1e6} for k, v in pc[cap].items()},
        }
    data["models"][model] = m

(HERE / "data.json").write_text(json.dumps(data, indent=1))
for model, m in data["models"].items():
    for cap, c in m["caps"].items():
        r = c["recall"]
        print(f"{m['label']:12} cap {cap:>2}: recall " + " / ".join(f"{r[k]['pct']:.1f}" for k in (1, 3, 5))
              + "  MB " + " ".join(f"{c['perCycle'][k]['MB']:.2f}" for k in range(1, 6))
              + "  cut " + " ".join(str(c['perCycle'][k]['truncatedChars']) for k in range(1, 6)))
