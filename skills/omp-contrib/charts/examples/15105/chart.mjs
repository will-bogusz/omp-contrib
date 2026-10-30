// #15105 What: what happens to the Chrome relay extension after an omp upgrade, as a decision flow.
// It replaces the What table (main vs this PR per case), which moves verbatim into <details> under it.
// Drawn from the PR's code at 5946e037; every question and outcome names its source in source/README.md.
//   bun <skill>/charts/run.mjs .
//
// The toolkit's decision-flow example (references/charts.md, *Drawn figures*): the questions run down one
// spine, each exit goes to the side, main's path and the PR's in their colours, the outcome that changed
// last. Exits that share an outcome (left alone, with a note) are joined into one box on the wide layout.
// Phone layout: the same steps in one column; each exit drops under its question, indented.
import { W, NARROW, svg, circle, line } from "omp-charts/look.mjs";
import { title, note, box, arrow, label, tone } from "omp-charts/draw.mjs";

export const meta = { pr: 15105 };

// ---------------------------------------------------------------- the flow
// A step is a question on the spine (`ask`) or the point where main and this PR part (`fork`).
//   who:  whose path the question is on ("pr", or "both" before the fork)
//   go:   the answer that continues down the spine
//   exit: the other answer and where it leads: a box of its own, `shared: true` for the shared note
//         box, `loop: true` for a wait that asks the same question again.
const TITLE = "After an omp upgrade, the relay now updates its Chrome extension itself once nothing is using it";
const START = "omp is upgraded. The extension in Chrome, still from the older omp, says hello to the relay.";
const STEPS = [
  { ask: "Does the extension speak the relay protocol?", who: "both", go: "yes",
    exit: { on: "no", who: "both", kicker: "main and this PR", text: "Every open fails: “extension is out of date”, as before." } },
  { fork: { who: "main", kicker: "main", text: "The old extension keeps running, silently, until you reinstall it and click Reload." } },
  { ask: "Was it installed by an omp with this change, so it can reload itself?", who: "pr", go: "yes",
    exit: { on: "no", shared: true } },
  { ask: "Has the relay already reloaded it once from this version, in this browser?", who: "pr", go: "no",
    exit: { on: "yes", shared: true } },
  { ask: "Is it loaded from omp's install folder, and are the files there not from a newer omp?", who: "pr", go: "yes",
    exit: { on: "no", shared: true } },
  { ask: "Is any CDP client connected (an omp browser session, a puppeteer script), or a tab attached?", who: "pr", go: "no",
    exit: { on: "yes", who: "pr", kicker: "waits", loop: true, text: "Opens carry the note meanwhile. Asks again when the last client leaves." } },
];
const END = { who: "pr", kicker: "updates, no clicks",
  text: "omp rewrites the extension's files; if still nothing uses it, the extension reloads itself and reconnects on the new omp. No note." };
const SHARED = { who: "pr", kicker: "left alone, with a note",
  text: "Left alone; it still works. Every open adds a note: out of date, run omp browser-relay install and reload it in Chrome." };
// The phone layout can't join exits from three rows into one box: the first draws it, the others point back.
const SHARED_AGAIN = { who: "pr", kicker: "left alone, with a note", text: "The same note as above." };
const FOOT = "Drawing of the PR's relay code. It asks about clients and tabs before the folder, and again after the rewrite; same outcomes.";

const GAP = 30; // the height of a down arrow between two spine boxes

// Where the next down arrow on the spine starts: { y, c: its colour, on: the answer it carries (none out
// of the start box), labelY / fill: where and in what colour that answer sits, if not just below y in fg }.
const answer = (x, from, t) => (from.on ? label(x + 8, from.labelY ?? from.y + 18, from.on, t, { fill: from.fill ?? t.fg }) : "");
// The down arrow into the next spine box, whose top is at y1.
const down = (x, from, y1, t) => arrow(x, from.y, x, y1, from.c) + answer(x, from, t);

// ---------------------------------------------------------------- wide: spine on the left, exits to the right
function wide(t) {
  const SPINE = 400, SIDE = 470, SIDE_W = W - SIDE, cx = SPINE / 2;
  const head = title(TITLE, W);
  let s = head.svg, y = head.y + 4;
  const start = box(0, y, SPINE, { text: START }, t);
  s += start.svg; y += start.h;
  let from = { y, c: t.ref };
  const sharedRows = []; // the y of each exit that joins the shared note box
  for (const step of STEPS) {
    if (step.fork) {
      // main turns right at a dot; this PR carries on down the spine.
      const side = box(0, 0, SIDE_W, step.fork, t), mid = y + GAP + side.h / 2;
      s += line(cx, from.y, cx, mid, from.c, 1.5) + answer(cx, from, t);
      s += circle(cx, mid, 4, t.fg);
      s += arrow(cx + 4, mid, SIDE, mid, t.main) + label(cx + 14, mid - 7, "on main", t, { fill: t.main });
      s += box(SIDE, y + GAP, SIDE_W, step.fork, t).svg;
      y += GAP + side.h;
      from = { y: mid + 4, c: t.pr, on: "with this PR", fill: t.pr, labelY: y + 16 };
      continue;
    }
    // A question row: the question and its exit box (if any) centred on each other.
    const q = { text: step.ask, who: step.who, strong: true, square: true };
    const qh = box(0, 0, SPINE, q, t).h;
    const sideH = step.exit.shared ? 0 : box(0, 0, SIDE_W, step.exit, t).h;
    const top = y + GAP, rowH = Math.max(qh, sideH), qy = top + (rowH - qh) / 2, mid = qy + qh / 2;
    s += down(cx, from, qy, t);
    s += box(0, qy, SPINE, q, t).svg;
    if (step.exit.shared) {
      sharedRows.push(mid);
      s += label(SPINE + 10, mid - 6, step.exit.on, t, { fill: t.fg });
    } else {
      const c = tone(t, step.exit.who), ay = step.exit.loop ? mid - 6 : mid;
      s += box(SIDE, top + (rowH - sideH) / 2, SIDE_W, step.exit, t).svg;
      s += arrow(SPINE, ay, SIDE, ay, c) + label(SPINE + 10, ay - 6, step.exit.on, t, { fill: t.fg });
      if (step.exit.loop) s += arrow(SIDE, mid + 8, SPINE, mid + 8, t.ref, { dash: true }); // asks again
    }
    y = top + rowH;
    from = { y: qy + qh, c: tone(t, step.who), on: step.go };
  }
  // The outcome that changed: the last box on the spine.
  const end = box(0, y + GAP, SPINE, END, t);
  s += down(cx, from, y + GAP, t) + end.svg;
  y += GAP + end.h;
  // The shared note box, centred on the exits that reach it, joined by one bracket.
  const shared = box(0, 0, SIDE_W, SHARED, t);
  const first = sharedRows[0], last = sharedRows[sharedRows.length - 1], ny = (first + last) / 2 - shared.h / 2, jx = SIDE - 22;
  s += box(SIDE, ny, SIDE_W, SHARED, t).svg;
  s += line(jx, first, jx, last, t.pr, 1.5);
  for (const r of sharedRows) s += line(SPINE, r, jx, r, t.pr, 1.5);
  s += arrow(jx, ny + shared.h / 2, SIDE, ny + shared.h / 2, t.pr);
  const foot = note(y + 26, FOOT, W, t);
  return svg(W, foot.y - 8, t, s + foot.svg);
}

// ---------------------------------------------------------------- phone: one column
function narrow(t) {
  const cx = 18, SIDE = 24, SIDE_W = NARROW - SIDE;
  const head = title(TITLE, NARROW);
  let s = head.svg, y = head.y + 4;
  const start = box(0, y, NARROW, { text: START }, t);
  s += start.svg; y += start.h;
  let from = { y, c: t.ref };
  let sharedDrawn = false;
  // An exit under its question: a stub down the spine, a short arrow right, the answer, then the box.
  const exitBox = (b, on, c) => {
    let out = line(cx, y, cx, y + 22, c, 1.5) + arrow(cx, y + 22, SIDE, y + 22, c) + label(SIDE + 4, y + 18, on, t, { fill: t.fg });
    const e = box(SIDE, y + 30, SIDE_W, b, t);
    out += e.svg;
    y += 30 + e.h;
    return out;
  };
  for (const step of STEPS) {
    if (step.fork) {
      s += line(cx, from.y, cx, y + GAP, from.c, 1.5) + answer(cx, from, t);
      y += GAP;
      const forkY = y;
      s += circle(cx, y + 6, 4, t.fg) + line(cx, y + 6, cx, y + 24, t.main, 1.5);
      s += arrow(cx, y + 24, SIDE, y + 24, t.main) + label(cx + 12, y + 18, "on main", t, { fill: t.main });
      const side = box(SIDE, y + 34, SIDE_W, step.fork, t);
      s += side.svg;
      y += 34 + side.h + 8;
      s += line(cx, forkY + 10, cx, y, t.pr, 1.5); // this PR's spine runs on past main's box
      from = { y, c: t.pr, on: "with this PR", fill: t.pr };
      continue;
    }
    const q = box(0, y + GAP, NARROW, { text: step.ask, who: step.who, strong: true, square: true }, t);
    s += down(cx, from, y + GAP, t) + q.svg;
    y += GAP + q.h;
    const qBottom = y, c = tone(t, step.exit.shared ? "pr" : step.exit.who);
    if (step.exit.shared) {
      s += exitBox(sharedDrawn ? SHARED_AGAIN : SHARED, step.exit.on, c);
      sharedDrawn = true;
    } else {
      s += exitBox(step.exit, step.exit.on, c);
      if (step.exit.loop) { s += label(SIDE, y + 16, "↑ then asks again", t); y += 22; }
    }
    s += line(cx, qBottom, cx, y + 4, c, 1.5); // the spine continues past the exit
    y += 4;
    from = { y, c: tone(t, step.who), on: step.go };
  }
  const end = box(0, y + GAP, NARROW, END, t);
  s += down(cx, from, y + GAP, t) + end.svg;
  y += GAP + end.h;
  const foot = note(y + 22, FOOT, NARROW, t);
  return svg(NARROW, foot.y - 8, t, s + foot.svg);
}

// ---------------------------------------------------------------- the chart and where it goes
export const charts = {
  flow: {
    fn: (_d, t) => wide(t),
    narrow: (_d, t) => narrow(t),
    alt: () =>
      "After an omp upgrade, main keeps running the old relay extension silently until you reinstall it; with this PR the relay rewrites the extension's files and it reloads itself on the new omp, no clicks, once no CDP client is connected and no tab attached. An extension it can't update this way is left working and every open adds an out-of-date note; the cases are in the table below.",
    takeaway:
      "After an omp upgrade, main keeps running the old extension silently; with this PR the relay rewrites the extension's files and it reloads itself on the new version with no clicks, waiting until no CDP client is connected and no tab attached, and an extension it cannot update (installed before this change, already reloaded once, another folder or a newer omp's files) is left working with an out-of-date note; one without the relay protocol still fails as before.",
  },
};

const TABLE = "| Extension in Chrome after an omp upgrade |";
export function place(body, _d, h) {
  return h.swapTable(body, TABLE, `${h.picture("flow")}\n\n${h.details("Each case, main vs this PR", h.table(body, TABLE))}`);
}
