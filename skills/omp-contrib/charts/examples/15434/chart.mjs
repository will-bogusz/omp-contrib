// #15434 Why, as published 2026-10-15: recall over repeated compactions, one line per image limit,
// small multiples per model, each run as a ring. data.json: derive.py (DriftCap scores + offline runs).
//   bun ../../run.mjs . --body body-before.md      (body-before.md: the body before the chart went in)
// Phone layout: the same two panels stacked, title and notes wrapped.
import { W, NARROW, svg, text, tspan, line, polyline, dot, footer, spread, linear, pct, num, mb, dashed, para } from "omp-charts/look.mjs";

export const meta = { pr: 15434 };

const OPUS = "claude-opus-5-5", ASTRA = "gpt-6-astra";
const recall = (d, m, cap) => d.models[m].caps[cap].recall;
const perCycle = (d, m, cap) => d.models[m].caps[cap].perCycle;
// Opus cap 80 sent the same archives as cap 40 at every compaction (frames and bytes match in the dry runs).
const opus80Is40 = d => [1, 2, 3, 4, 5].every(c =>
  perCycle(d, OPUS, 40)[c].frames === perCycle(d, OPUS, 80)[c].frames && perCycle(d, OPUS, 40)[c].imageBytes === perCycle(d, OPUS, 80)[c].imageBytes);
// `main` keeps 17 history images for Opus only (the published table scopes it so).
const capLabel = (m, cap, merged) =>
  cap === 17 ? (m === OPUS ? "17 images · main" : "17 images") : merged && cap === 40 ? "40 or 80 images" : `${cap} images`;
const role = { 17: "main", 40: "pr", 80: "alt" };

const title = d => `At 17 history images (Opus on main), recall falls to ${r5(d, OPUS, 17)}% by the 5th compaction; at 40 it stays at ${r5(d, OPUS, 40)}%`;
const SUB = "Recall of the session's early facts after each compaction (0 = as if no history, 100 = full); more images keep it in both models.";
const HEAD = m => (m === OPUS ? ": 40 images are enough" : ": needs 80 images");
const NOTE = m => (m === OPUS ? "It never used more than 37 images, so 80 behaves like 40." : "At 40 images it still forgets by the 5th; 80 holds.");
const FOOT1 = "One real 1,300-turn session per model, replayed with only the image limit changed; recall after 1, 3 and 5 compactions.";
const FOOT2 = "Rings: single runs (1 to 3 per point); line and labels: their mean.";

// One model's panel: header at y = T + 14, plot between T + 30 and T + 182, x axis labels below.
function panel(d, t, m, ox, T, x1) {
  const top = T + 30, bottom = T + 182, x0 = ox + 40;
  const X = linear(1, 5, x0, x1), Y = linear(0, 100, bottom, top);
  let b = text(ox, T + 14, `${tspan(d.models[m].label, { weight: 600 })}${tspan(HEAD(m), { fill: t.muted, weight: 400 })}`, { size: 14, raw: true });
  for (const g of [0, 25, 50, 75, 100]) {
    b += line(x0, Y(g), x1, Y(g), t.grid, g === 0 ? 1 : 0.6, g === 0 ? "" : dashed);
    if (g % 50 === 0) b += text(x0 - 7, Y(g) + 4, g === 100 ? "100%" : `${g}`, { anchor: "end", fill: t.muted, size: 11.5 });
  }
  for (const c of [1, 3, 5]) b += text(X(c), bottom + 17, `${c}`, { anchor: "middle", fill: t.muted, size: 11.5 });
  b += text((x0 + x1) / 2, bottom + 33, "times the session was compacted", { anchor: "middle", fill: t.muted, size: 11.5 });

  const merged = m === OPUS && opus80Is40(d);
  const caps = merged ? [17, 40] : [17, 40, 80];
  const ends = [];
  for (const cap of [...caps].reverse()) { // main drawn last, on top
    const col = t[role[cap]], r = recall(d, m, cap);
    const pts = [1, 3, 5].map(c => [X(c), Y(r[c].pct)]);
    b += polyline(pts, col, 2.25);
    // each run as a small open circle; the line joins their means
    for (const c of [1, 3, 5]) for (const v of r[c].runs) b += `<circle cx="${X(c)}" cy="${Y(v)}" r="5.5" fill="none" stroke="${col}" stroke-opacity="0.55" stroke-width="1"/>`;
    for (const [x, y] of pts) b += dot(x, y, 3.5, col, t);
    ends.push({ cap, y: Y(r[5].pct), v: r[5].pct, mb: perCycle(d, m, cap)[5].MB, name: capLabel(m, cap, merged) });
  }
  // values at compactions 1 and 3 (5 is in the end labels); muted where lines share a point
  const lab = (c, cap, where, fill = t[role[cap]]) => {
    const v = recall(d, m, cap)[c].pct;
    const at = { above: [0, -8, "middle"], below: [0, 17, "middle"], right: [8, 4, "start"], left: [-7, 4, "end"], aboveRight: [9, -9, "start"] }[where];
    return text(X(c) + at[0], Y(v) + at[1], num(v), { anchor: at[2], size: 12, weight: 600, fill });
  };
  b += m === OPUS
    ? lab(1, 17, "aboveRight", t.muted) + lab(3, 40, "above") + lab(3, 17, "right")
    : lab(1, 40, "aboveRight", t.muted) + lab(1, 17, "left") + lab(3, 80, "above") + lab(3, 40, "right") + lab(3, 17, "below");
  spread(ends, 30, top - 2, bottom + 6);
  for (const e of ends) {
    b += text(x1 + 10, e.y, `${tspan(pct(e.v), { fill: t[role[e.cap]], weight: 700, size: 14 })}${tspan(` ${e.name}`, { fill: t.fg, size: 12.5 })}`, { raw: true });
    b += text(x1 + 10, e.y + 14, `${mb(e.mb)} of images`, { fill: t.muted, size: 11.5 });
  }
  return b;
}

function chart(d, t) {
  const T = 50; // title block
  const H = T + 284, PW = W / 2;
  let b = text(0, 17, title(d), { size: 15, weight: 600 });
  b += text(0, 37, SUB, { fill: t.muted, size: 12 });
  for (const [i, m] of [OPUS, ASTRA].entries()) {
    const ox = i * PW;
    b += panel(d, t, m, ox, T, ox + 232);
    b += text(ox, H - 40, NOTE(m), { fill: t.muted, size: 12 });
  }
  b += footer(H - 20, FOOT1, t);
  b += footer(H - 4, FOOT2, t);
  return svg(W, H, t, b);
}

// Phone: the panels stacked at full width, each with its note under it; the plot narrows so the end labels fit.
function narrow(d, t) {
  const X1 = 172; // plot right edge; end labels run from X1 + 10 to about NARROW
  const ti = para(0, 17, title(d), NARROW, { size: 15, weight: 600, lead: 20 });
  let b = ti.svg;
  const sub = para(0, ti.y + 2, SUB, NARROW, { fill: t.muted, size: 12, lead: 16 });
  b += sub.svg;
  let y = sub.y + 4;
  for (const m of [OPUS, ASTRA]) {
    const T = y - 8; // the header baseline sits at T + 14
    b += panel(d, t, m, 0, T, X1);
    const note = para(0, T + 236, NOTE(m), NARROW, { fill: t.muted, size: 12, lead: 16 });
    b += note.svg;
    y = note.y + 22;
  }
  const f1 = para(0, y, FOOT1, NARROW, { fill: t.muted, size: 11.5, lead: 15 });
  const f2 = para(0, f1.y + 2, FOOT2, NARROW, { fill: t.muted, size: 11.5, lead: 15 });
  b += f1.svg + f2.svg;
  return svg(NARROW, f2.y - 4, t, b);
}

function r5(d, m, cap) { return Math.round(recall(d, m, cap)[5].pct); }
// largest gap between repeat runs of one point, in recall points
const maxSpread = d => Math.max(...Object.values(d.models).flatMap(m => Object.values(m.caps).flatMap(c => Object.values(c.recall).map(x => Math.max(...x.runs) - Math.min(...x.runs)))));
export const charts = {
  "recall-a": {
    fn: chart,
    narrow,
    alt: d => `Kept to 17 history images (Opus on main today), a long session forgets its start: after 5 compactions Opus recalls ${r5(d, OPUS, 17)}% of early facts and gpt-6-astra ${r5(d, ASTRA, 17)}%. With 40 images Opus keeps ${r5(d, OPUS, 40)}%; gpt-6-astra keeps ${r5(d, ASTRA, 40)}% at 40 and ${r5(d, ASTRA, 80)}% at 80.`,
    takeaway: "Keeping only 17 history images (what Opus gets on main), the model's recall of a long session's early facts collapses as the session is compacted again and again (to about 18-21% after 5 compactions); a larger limit keeps it (40 images holds Opus at 97%; gpt-6-astra holds only at 80, 83%).",
  },
};

// The recall table moves into <details>; the repeat spread in its summary is derived, not typed.
export function place(body, d, h) {
  const first = "| Frame cap";
  const block = `${h.picture("recall-a")}\n\n${h.details(`Exact numbers (one session per model, 1 to 3 runs per cell; repeats differ by up to ${Math.round(maxSpread(d))} points)`, h.table(body, first))}`;
  return h.replace(h.swapTable(body, first, block), "repeat spread up to about 13 points.", `repeat spread up to about ${Math.round(maxSpread(d))} points.`);
}
