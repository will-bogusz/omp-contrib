// Building blocks for drawn figures (decision flows, routing diagrams, timelines, turn strips, literal
// text), on top of look.mjs: a figure is still pure (data, theme) -> SVG, in both layouts. Rules:
// ../../references/charts.md, *Drawn figures*. Each helper returns { svg, ... } with the space it took,
// so a layout stacks parts by adding heights instead of guessing them.
import { MIN_TEXT, esc, line, para, text, wrap } from "./look.mjs";

// The stroke for a party: "main" (orange), "pr" (blue), anything else (both, neither) the neutral ref.
export const tone = (t, who) => (who === "main" ? t.main : who === "pr" ? t.pr : t.ref);

// The figure's title (its takeaway, rule 1) from the top, wrapped to `width`; y = the next free baseline.
export const title = (s, width) => para(0, 20, s, width, { size: 15, weight: 600, lead: 20 });

// What was run or drawn from, muted, wrapped, starting at baseline `y`; ends the figure:
// L.svg(width, note.y - 8, t, body).
export const note = (y, s, width, t) => para(0, y, s, width, { size: MIN_TEXT, fill: t.muted, lead: 16 });

// A box `w` wide at (x, y) with wrapped text, its height grown to fit. `kicker` is a small bold line
// above the text in the party's colour (who decides, what happens); `strong` sets the text in 600 (a
// question in a flow); `square` gives sharp corners (questions) where outcomes stay rounded. A party's
// box gets a 1.75 px stroke in its colour, a shared one 1 px in ref. `mark` ("good" | "bad") makes it an
// outcome that stands out: a 2.25 px stroke and kicker in that outcome colour (give it a kicker such as
// "✓ …", so colour is not the only key). Returns { svg, h }.
export function box(x, y, w, { text: s, kicker, who, mark, strong = false, square = false, size = 12.5 }, t) {
  const pad = 10, lead = Math.round(size * 1.36), weight = strong ? 600 : 400;
  const lines = wrap(s, w - 2 * pad, size, weight);
  const kick = kicker ? MIN_TEXT + 6 : 0;
  const h = pad + kick + lines.length * lead + pad - 4;
  const party = who === "main" || who === "pr";
  const sw = mark ? 2.25 : party ? 1.75 : 1, stroke = mark ? t[mark] : tone(t, who);
  let out = `<rect x="${x + sw / 2}" y="${y + sw / 2}" width="${w - sw}" height="${h - sw}" rx="${square ? 3 : 8}" fill="${t.panel}" stroke="${stroke}" stroke-width="${sw}"/>`;
  if (kicker) out += text(x + pad, y + pad + MIN_TEXT - 1, kicker, { size: MIN_TEXT, weight: 600, fill: mark ? t[mark] : party ? tone(t, who) : t.muted });
  lines.forEach((l, i) => (out += text(x + pad, y + pad + kick + Math.round(size * 0.96) + i * lead, l, { size, weight })));
  return { svg: out, h };
}

// A straight arrow from (x1, y1) to (x2, y2), its head ending exactly on the target point; `dash` draws
// the shaft dashed (a loop back, a "then asks again").
export function arrow(x1, y1, x2, y2, c, { width = 1.5, dash = false } = {}) {
  const len = Math.hypot(x2 - x1, y2 - y1), k = 6;
  if (!len) return "";
  const ux = (x2 - x1) / len, uy = (y2 - y1) / len, bx = x2 - ux * k, by = y2 - uy * k, hw = k / 1.4;
  const tip = `${x2},${y2} ${bx - uy * hw},${by + ux * hw} ${bx + uy * hw},${by - ux * hw}`;
  return line(x1, y1, bx, by, c, width, dash ? ` stroke-dasharray="4 3"` : "") + `<polygon points="${tip}" fill="${c}"/>`;
}

// The small bold label on an edge ("yes", "on main", "with this PR"), 11.5 px.
export const label = (x, y, s, t, { fill, anchor } = {}) => text(x, y, s, { size: MIN_TEXT, weight: 600, fill: fill ?? t.muted, anchor });

// A colour key square for a lane or series, its top-left at (x, y - 10).
export const swatch = (x, y, fill) => `<rect x="${x}" y="${y - 10}" width="12" height="12" rx="2" fill="${fill}"/>`;

// Literal text the model or user reads (a snapshot, a prompt, a log line), in a monospace face. `mark` =
// substrings to box in an outcome colour (`as`: "bad" for what main leaks or gets wrong, "good" for the
// fix): a tinted, outlined box behind normal text, since coloured text on a tint misses 4.5:1. `width`
// (px) wraps a line too long for it after its last ": " or space that fits, never inside a mark, the
// rest indented 4 past the line's own indent; say "long lines wrapped" in the footer. Without `width`
// nothing wraps: size the font so the longest line fits. `gap` adds room under each row holding a mark,
// for a note pointing at it: px, or a function of that row's marks returning px (a two-line note needs
// more than a one-line one). Returns { svg, h, rows, marks: [{ s, line, row, x, y, w }] } (`line` =
// index in `lines`, `row` = drawn row, y = its baseline), so notes can point at a mark.
export const MONO = `ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace`;
const CHAR_EM = 0.602; // the advance of one character in SF Mono / Menlo, in em
export const monoWidth = (s, size) => String(s).length * size * CHAR_EM;
function wrapMono(l, max, mark) {
  const rows = [];
  let rest = l, lead = "";
  while (lead.length + rest.length > max) {
    const room = max - lead.length, inMark = i => mark.some(s => { for (let j = rest.indexOf(s); j >= 0; j = rest.indexOf(s, j + 1)) if (i > j && i < j + s.length) return true; return false; });
    let cut = -1;
    for (const sep of [": ", " "]) {
      for (let i = rest.lastIndexOf(sep, room - sep.length); i > 0; i = rest.lastIndexOf(sep, i - 1)) {
        if (rest.slice(0, i).trim() && !inMark(i + sep.length)) { cut = i + sep.length; break; }
      }
      if (cut > 0) break;
    }
    if (cut < 0) break; // no break point: the row runs long, and the PNG check shows it
    rows.push(lead + rest.slice(0, cut).trimEnd());
    if (!lead) lead = " ".repeat(l.length - l.trimStart().length + 4);
    rest = rest.slice(cut);
  }
  return [...rows, lead + rest];
}
export function code(x, y, lines, { size = 12.5, mark = [], as = "bad", width, gap = 0 }, t) {
  const lead = Math.round(size * 1.5), max = width ? Math.floor(width / (size * CHAR_EM)) : Infinity;
  let boxes = "", out = "", row = 0, by = y + Math.round(size * 1.1);
  const marks = [];
  lines.forEach((l, li) => {
    for (const r of width ? wrapMono(l, max, mark) : [l]) {
      const rowMarks = [];
      for (const s of mark) {
        for (let i = r.indexOf(s); i >= 0; i = r.indexOf(s, i + s.length)) {
          const mx = x + monoWidth(r.slice(0, i), size), w = monoWidth(s, size);
          rowMarks.push({ s, line: li, row, x: mx, y: by, w });
          boxes += `<rect x="${mx - 1}" y="${by - size + 1}" width="${w + 2}" height="${size + 4}" rx="3" fill="rgba(${t.rgb[as]},0.22)" stroke="${t[as]}" stroke-width="1"/>`;
        }
      }
      out += `<text x="${x}" y="${by}" font-family='${MONO}' font-size="${size}" xml:space="preserve">${esc(r)}</text>`;
      row++;
      marks.push(...rowMarks);
      by += lead + (rowMarks.length ? (typeof gap === "function" ? gap(rowMarks) : gap) : 0);
    }
  });
  return { svg: boxes + out, h: by - y - Math.round(size * 1.1) + Math.round(size * 0.4), rows: row, marks };
}
