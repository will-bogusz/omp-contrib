// Drawn figures from a spec, so the two common ones need a JSON file instead of a chart.mjs: a timeline
// (#15569) and a decision flow (#15105). run.mjs uses fromFigures when DIR has figures.json and no chart.mjs.
// Rules: ../../references/charts.md, *Drawn figures*.
//
// figures.json: { pr?, repo?, figures: [spec, …] }; every spec has id, title, takeaway, alt, note (the
// footer: what the figure is drawn from), optional details (the <details> summary), and exactly one of
//   at: "<!-- figure: x -->"   a line in the body, replaced by the picture
//   replaces: "| Case |"       a table's header start: the picture, then the table verbatim in <details>
// shape "timeline": steps: [2-6 strings, in order, not to scale],
//   lanes: [{ who: "main" | "pr" | other, label, cells: [one per step: "" / null (the lane runs on),
//            "text", or { text, outcome?: "good" | "bad", kicker? }] }]
// shape "flow": questions: [{ q, exit: "yes" | "no", out: outcome }], end: outcome. The exit answer leaves
//   to `out`; the other answer continues down the spine, which ends in `end`.
//   outcome: { text, who?: "main" | "pr" | "both", kicker? } or, where main and this PR differ, { main, pr }.
import { W, NARROW, svg, line, para, circle } from "./look.mjs";
import { title, note, box, arrow, label, tone } from "./draw.mjs";

const SIZE = 12.5; // box and header text
const PARTY = { main: "main", pr: "this PR", both: "main and this PR" };
// A cell or outcome kicker: an outcome mark says so in words, not just colour.
const MARK = { good: "✓ fixed", bad: "✗ broken" };

// ---------------------------------------------------------------- shared

// The figure's frame: title on top, `body(y)` -> { svg, y } below it, the note last.
function frame(width, spec, body) {
  const head = title(spec.title, width);
  const b = body(head.y + 6);
  const foot = note(b.y + 24, spec.note, width, b.t);
  return svg(width, foot.y - 8, b.t, head.svg + b.svg + foot.svg);
}
const cellOf = c => (c == null || c === "" ? null : typeof c === "string" ? { text: c } : c);

// ---------------------------------------------------------------- timeline

function timelineWide(spec, t) {
  const n = spec.steps.length, LABEL = 104, GAP = 12, colW = (W - LABEL) / n, size = n > 4 ? 12 : SIZE;
  return frame(W, spec, y0 => {
    let s = "", hy = 0;
    // Step headers across equal columns, a tick above each; the tallest sets the header band.
    spec.steps.forEach((st, i) => {
      const x = LABEL + i * colW;
      s += line(x, y0 + 4, x + colW - GAP, y0 + 4, t.border, 1);
      const p = para(x, y0 + 22, st, colW - GAP, { size: SIZE, weight: 600, lead: 17 });
      s += p.svg; hy = Math.max(hy, p.y);
    });
    let y = hy + 4;
    for (const lane of spec.lanes) {
      const c = tone(t, lane.who);
      const cells = lane.cells.map(cellOf);
      const opts = cells.map(cl => cl && { text: cl.text, who: lane.who, mark: cl.outcome, kicker: cl.kicker ?? MARK[cl.outcome], size });
      const hs = opts.map(o => (o ? box(0, 0, colW - GAP, o, t).h : 0));
      const lab = para(0, 0, lane.label, LABEL - 14, { size: SIZE, weight: 600, lead: 17 });
      const rowH = Math.max(...hs, lab.y - 4, 30), mid = y + rowH / 2;
      // The lane line runs from its label to its last box, under the boxes.
      const last = cells.findLastIndex(Boolean);
      if (last >= 0) s += line(LABEL - 8, mid, LABEL + last * colW + (colW - GAP) / 2, mid, c, 2);
      s += para(0, mid - (lab.y - 17) / 2 + 4, lane.label, LABEL - 14, { size: SIZE, weight: 600, lead: 17, fill: lane.who === "main" || lane.who === "pr" ? c : t.fg }).svg;
      opts.forEach((o, i) => { if (o) s += box(LABEL + i * colW, mid - hs[i] / 2, colW - GAP, o, t).svg; });
      y += rowH + 14;
    }
    return { svg: s, y: y - 14, t };
  });
}

function timelineNarrow(spec, t) {
  return frame(NARROW, spec, y0 => {
    let s = "", y = y0;
    spec.steps.forEach((st, i) => {
      s += line(0, y + 4, NARROW, y + 4, t.border, 1);
      const p = para(0, y + 22, `${i + 1}. ${st}`, NARROW, { size: SIZE, weight: 600, lead: 17 });
      s += p.svg; y = p.y - 6;
      for (const lane of spec.lanes) {
        const cl = cellOf(lane.cells[i]);
        if (!cl) continue;
        const kick = cl.kicker ?? (cl.outcome ? `${lane.label}: ${MARK[cl.outcome]}` : lane.label);
        const b = box(0, y, NARROW, { text: cl.text, who: lane.who, mark: cl.outcome, kicker: kick }, t);
        s += b.svg; y += b.h + 8;
      }
      y += 10;
    });
    return { svg: s, y: y - 18, t };
  });
}

// ---------------------------------------------------------------- flow

const changed = o => o.main !== undefined;
// The boxes one outcome draws: one, or main's then this PR's.
const outBoxes = o => (changed(o)
  ? [{ text: o.main, who: "main", kicker: "main" }, { text: o.pr, who: "pr", kicker: "this PR" }]
  : [{ text: o.text, who: o.who, kicker: o.kicker ?? PARTY[o.who] }]);
const other = a => (a === "yes" ? "no" : "yes");
const GAP = 30; // a down arrow between two spine boxes

function flowWide(spec, t) {
  const SPINE = 400, SIDE = 470, SIDE_W = W - SIDE, cx = SPINE / 2;
  return frame(W, spec, y0 => {
    let s = "", y = y0 - GAP, from = null;
    const down = (y1) => (from ? arrow(cx, from.y, cx, y1, t.ref) + label(cx + 8, from.y + 18, from.on, t, { fill: t.fg }) : "");
    for (const q of spec.questions) {
      const qb = { text: q.q, strong: true, square: true };
      const qh = box(0, 0, SPINE, qb, t).h;
      const outs = outBoxes(q.out), hs = outs.map(o => box(0, 0, SIDE_W, o, t).h);
      const sideH = hs.reduce((a, b) => a + b, 0) + 8 * (hs.length - 1);
      const top = y + GAP, rowH = Math.max(qh, sideH), qy = top + (rowH - qh) / 2, mid = qy + qh / 2;
      s += down(qy) + box(0, qy, SPINE, qb, t).svg;
      const c = tone(t, changed(q.out) ? "both" : q.out.who);
      let by = top + (rowH - sideH) / 2;
      const centres = [];
      outs.forEach((o, i) => { s += box(SIDE, by, SIDE_W, o, t).svg; centres.push(by + hs[i] / 2); by += hs[i] + 8; });
      if (centres.length === 1) s += arrow(SPINE, mid, SIDE, mid, c);
      else {
        // One exit into two boxes: a bracket, an arrow into each.
        const jx = SIDE - 18;
        s += line(SPINE, mid, jx, mid, c, 1.5) + line(jx, centres[0], jx, centres.at(-1), c, 1.5);
        for (const cy of centres) s += arrow(jx, cy, SIDE, cy, c);
      }
      s += label(SPINE + 8, mid - 6, q.exit, t, { fill: t.fg });
      y = top + rowH;
      from = { y: qy + qh, on: other(q.exit) };
    }
    const ends = outBoxes(spec.end);
    if (ends.length === 1) {
      const e = box(0, y + GAP, SPINE, ends[0], t);
      s += down(y + GAP) + e.svg;
      return { svg: s, y: y + GAP + e.h, t };
    }
    // A changed end: main's under the spine, this PR's to its right, the spine forking into both.
    const fy = y + GAP / 2 + 4, top = y + GAP + 8, px = SIDE + SIDE_W / 2;
    const m = box(0, top, SPINE, ends[0], t), p = box(SIDE, top, SIDE_W, ends[1], t);
    s += line(cx, from.y, cx, fy, t.ref, 1.5) + label(cx + 8, from.y + 18, from.on, t, { fill: t.fg });
    s += circle(cx, fy, 3.5, t.fg) + arrow(cx, fy, cx, top, t.main);
    s += line(cx, fy, px, fy, t.pr, 1.5) + arrow(px, fy, px, top, t.pr);
    s += m.svg + p.svg;
    return { svg: s, y: top + Math.max(m.h, p.h), t };
  });
}

function flowNarrow(spec, t) {
  const cx = 18, SIDE = 24, SIDE_W = NARROW - SIDE;
  return frame(NARROW, spec, y0 => {
    let s = "", y = y0 - GAP, from = null, spine = 0; // spine: where the last branch arrow left it
    // Boxes under the spine, indented: the spine runs on from `top` past them, an arrow into each, the
    // answer that leads there (if any) above the first.
    const branch = (boxes, on, top) => {
      let out = label(SIDE + 4, y + 18, on, t, { fill: t.fg });
      y += 10;
      for (const o of boxes) {
        const b = box(SIDE, y + 14, SIDE_W, o, t), cy = y + 14 + Math.min(b.h / 2, 20);
        out += line(cx, top, cx, cy, t.ref, 1.5) + arrow(cx, cy, SIDE, cy, tone(t, o.who));
        out += b.svg;
        spine = top = cy; y += 14 + b.h;
      }
      return out;
    };
    for (const q of spec.questions) {
      const qb = box(0, y + GAP, NARROW, { text: q.q, strong: true, square: true }, t);
      if (from) s += arrow(cx, from.y, cx, y + GAP, t.ref) + label(cx + 8, from.y + 18, from.on, t, { fill: t.fg });
      s += qb.svg;
      y += GAP + qb.h;
      s += branch(outBoxes(q.out), q.exit, y);
      s += line(cx, spine, cx, y + 4, t.ref, 1.5); // the spine continues past the exit
      y += 4;
      from = { y, on: other(q.exit) };
    }
    const ends = outBoxes(spec.end);
    if (ends.length === 1) {
      const e = box(0, y + GAP, NARROW, ends[0], t);
      s += arrow(cx, from.y, cx, y + GAP, t.ref) + label(cx + 8, from.y + 18, from.on, t, { fill: t.fg }) + e.svg;
      return { svg: s, y: y + GAP + e.h, t };
    }
    s += branch(ends, from.on, from.y);
    return { svg: s, y, t };
  });
}

// ---------------------------------------------------------------- specs

const SHAPES = { timeline: [timelineWide, timelineNarrow], flow: [flowWide, flowNarrow] };

function check(spec, where) {
  const fail = m => { throw new Error(`figures.json: ${where}: ${m}`); };
  const str = (v, name) => { if (typeof v !== "string" || !v.trim()) fail(`${name} is missing (a non-empty string)`); };
  if (!SHAPES[spec.shape]) fail(`unknown shape ${JSON.stringify(spec.shape)}: one of ${Object.keys(SHAPES).join(", ")}`);
  for (const k of ["id", "title", "takeaway", "alt", "note"]) str(spec[k], k);
  if ((spec.at === undefined) === (spec.replaces === undefined)) fail("needs exactly one of at (a line in the body) or replaces (a table's header start)");
  str(spec.at ?? spec.replaces, spec.at !== undefined ? "at" : "replaces");
  const outcome = (o, name) => {
    if (!o || typeof o !== "object") fail(`${name} is missing ({ text, who? } or { main, pr })`);
    if (o.main !== undefined || o.pr !== undefined) { str(o.main, `${name}.main`); str(o.pr, `${name}.pr`); }
    else str(o.text, `${name}.text`);
  };
  if (spec.shape === "timeline") {
    const n = spec.steps?.length;
    if (!Array.isArray(spec.steps) || n < 2 || n > 6) fail("steps must list 2 to 6 events or phases");
    spec.steps.forEach((st, i) => str(st, `steps[${i}]`));
    if (!Array.isArray(spec.lanes) || !spec.lanes.length) fail("lanes is missing");
    spec.lanes.forEach((l, i) => {
      str(l.who, `lanes[${i}].who`); str(l.label, `lanes[${i}].label`);
      if (!Array.isArray(l.cells) || l.cells.length !== n) fail(`lanes[${i}] (${l.label}) has ${l.cells?.length ?? 0} cells for ${n} steps`);
      l.cells.forEach((c, j) => {
        if (c && typeof c === "object") {
          str(c.text, `lanes[${i}].cells[${j}].text`);
          if (c.outcome !== undefined && !MARK[c.outcome]) fail(`lanes[${i}].cells[${j}].outcome must be "good" or "bad"`);
        } else if (c != null && typeof c !== "string") fail(`lanes[${i}].cells[${j}] must be "", null, a string or { text, outcome? }`);
      });
    });
  } else {
    if (!Array.isArray(spec.questions) || !spec.questions.length) fail("questions is missing");
    spec.questions.forEach((q, i) => {
      str(q.q, `questions[${i}].q`);
      if (q.exit !== "yes" && q.exit !== "no") fail(`questions[${i}].exit must be "yes" or "no"`);
      outcome(q.out, `questions[${i}].out`);
    });
    outcome(spec.end, "end");
  }
}

// One chart entry per shape for a chart.mjs that wants it; fromFigures checks the spec first.
export const timeline = spec => entry({ ...spec, shape: "timeline" });
export const flow = spec => entry({ ...spec, shape: "flow" });
function entry(spec) {
  const [wide, narrow] = SHAPES[spec.shape];
  return { fn: (_d, t) => wide(spec, t), narrow: (_d, t) => narrow(spec, t), alt: () => spec.alt, takeaway: spec.takeaway };
}

// figures.json -> run.mjs's { meta, charts, place }, every spec checked.
export function fromFigures(json) {
  if (json.pr !== undefined && !Number.isInteger(json.pr)) throw new Error("figures.json: pr must be a PR number (or left out for a body drafted before its PR)");
  if (!Array.isArray(json.figures) || !json.figures.length) throw new Error("figures.json: figures is missing (a list of figure specs)");
  const charts = {};
  json.figures.forEach((spec, i) => {
    check(spec, `figures[${i}]${spec?.id ? ` (${spec.id})` : ""}`);
    if (charts[spec.id]) throw new Error(`figures.json: figures[${i}]: id ${JSON.stringify(spec.id)} is used twice`);
    charts[spec.id] = entry(spec);
  });
  const place = (body, _d, h) => json.figures.reduce((b, f) => (f.at !== undefined
    ? h.replace(b, f.at, h.picture(f.id))
    : h.swapTable(b, f.replaces, `${h.picture(f.id)}\n\n${h.details(f.details ?? "Exact table", h.table(b, f.replaces))}`)), body);
  return { meta: { pr: json.pr, repo: json.repo }, charts, place };
}
