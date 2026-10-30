// The look every PR chart shares: canvas, font, GitHub (Primer) palettes, SVG primitives.
// Chart modules import it as "omp-charts/look.mjs" (run.mjs links it into the chart's folder) and stay
// pure: (data, theme) -> SVG string. Rules: ../../references/charts.md.

export const W = 780; // PR body content width at a 1440 px window (814 px comment box - 2 x 16 px padding), measured on github.com
// Phone layout width: the PR column is 324 px at a 390 px window (309 at 375, 364 at 430), so at 320 the
// 11.5 px text stays at least 11 px from 375 px up. pr-images shows it below a 1244 px window.
export const NARROW = 320;
// pr-images shows the phone layout up to 440 px wide (a half-width desktop window, 768-1243 px), so it
// renders at 3x: 960 px keeps 2 device pixels per CSS pixel there and covers a 3x phone at 320.
export const SCALE = 2, NARROW_SCALE = 3;
export const MIN_TEXT = 11.5; // the smallest text a chart draws, in CSS px at its own width
export const FONT = `-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif`;

// Primer tokens read from GitHub's own CSS (data-*-theme=dark|light), 2026-10-15.
// Roles: main = how `main` behaves today; pr = this PR; alt = a third arm; ref = reference lines;
// good / bad = outcome marks. `rgb` keeps the same roles as "r,g,b" for translucent fills.
export const THEMES = {
  dark: {
    name: "dark", bg: "#0d1117", fg: "#f0f6fc", muted: "#9198a1", border: "#3d444d", grid: "#3d444d", panel: "#151b23",
    main: "#db6d28", pr: "#4493f8", alt: "#ab7df8", ref: "#9198a1", good: "#3fb950", bad: "#f85149",
    rgb: { main: "219,109,40", pr: "68,147,248", alt: "171,125,248", good: "63,185,80", bad: "248,81,73" },
  },
  light: {
    name: "light", bg: "#ffffff", fg: "#1f2328", muted: "#59636e", border: "#d1d9e0", grid: "#d1d9e0", panel: "#f6f8fa",
    main: "#bc4c00", pr: "#0969da", alt: "#8250df", ref: "#59636e", good: "#1a7f37", bad: "#d1242f",
    rgb: { main: "188,76,0", pr: "9,105,218", alt: "130,80,223", good: "26,127,55", bad: "209,36,47" },
  },
};

// ---------------------------------------------------------------- formatting
export const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
export const pct = v => `${Math.round(v)}%`;
export const num = v => `${Math.round(v)}`;
export const fixed = (v, d = 1) => v.toFixed(d);
export const signed = (v, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;
export const mb = v => `${v.toFixed(1)} MB`;
export const kchars = n => (n === 0 ? "0" : `${Math.round(n / 1000)}k`);
export const thousands = n => Math.round(n).toLocaleString("en-US");

// ---------------------------------------------------------------- primitives
export function svg(w, h, t, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" font-family='${FONT}' font-size="12" fill="${t.fg}"><rect width="${w}" height="${h}" fill="${t.bg}"/>${body}</svg>`;
}
export function text(x, y, s, o = {}) {
  const a = [`x="${x}"`, `y="${y}"`];
  if (o.anchor) a.push(`text-anchor="${o.anchor}"`);
  if (o.size) a.push(`font-size="${o.size}"`);
  if (o.weight) a.push(`font-weight="${o.weight}"`);
  if (o.fill) a.push(`fill="${o.fill}"`);
  if (o.baseline) a.push(`dominant-baseline="${o.baseline}"`);
  if (o.italic) a.push(`font-style="italic"`);
  return `<text ${a.join(" ")}>${o.raw ? s : esc(s)}</text>`;
}
// Approximate advance width of `s` in the system font (SF / Segoe), erring wide, for wrapping: the 1.06
// covers plain lowercase text, which rendered up to 3% wider than the per-character table alone.
export function textWidth(s, size = 12, weight = 400) {
  let em = 0;
  for (const ch of String(s)) {
    em += /[ il.,:;'|!ijtf\u00b7()\[\]]/.test(ch) ? 0.3 : /[rI\-–]/.test(ch) ? 0.4 : /[mwMW%→]/.test(ch) ? 0.88
      : /[A-Z0-9#?−+=<>~]/.test(ch) ? 0.64 : 0.55;
  }
  return em * size * 1.06 * (weight >= 600 ? 1.06 : 1);
}
// Words of `s` packed into lines no wider than `w` px at `size`, as even in length as that line count allows.
export function wrap(s, w, size = 12, weight = 400) {
  const pack = width => {
    const out = [];
    for (const word of String(s).split(" ")) {
      const last = out.length ? `${out[out.length - 1]} ${word}` : word;
      if (out.length && textWidth(last, size, weight) <= width) out[out.length - 1] = last;
      else out.push(word);
    }
    return out;
  };
  const n = pack(w).length;
  let lo = 0, hi = w; // the narrowest width that still needs only n lines
  while (hi - lo > 1) { const mid = (lo + hi) / 2; if (pack(mid).length <= n) hi = mid; else lo = mid; }
  return pack(hi);
}
// Wrapped text from (x, y) down, `lead` px per line; returns { svg, y } with y the next free baseline.
export function para(x, y, s, w, o = {}) {
  const size = o.size ?? 12, lead = o.lead ?? Math.round(size * 1.35);
  const ls = wrap(s, w, size, o.weight);
  return { svg: ls.map((l, i) => text(x, y + i * lead, l, o)).join(""), y: y + ls.length * lead };
}
export const tspan = (s, o = {}) =>
  `<tspan${o.fill ? ` fill="${o.fill}"` : ""}${o.weight ? ` font-weight="${o.weight}"` : ""}${o.size ? ` font-size="${o.size}"` : ""}${o.dx ? ` dx="${o.dx}"` : ""}>${esc(s)}</tspan>`;
export const line = (x1, y1, x2, y2, stroke, w = 1, extra = "") =>
  `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${w}"${extra}/>`;
export const dashed = " stroke-dasharray=\"2 3\"";
export const rect = (x, y, w, h, fill, extra = "") => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}"${extra}/>`;
export const circle = (cx, cy, r, fill, extra = "") => `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}"${extra}/>`;
export const polyline = (pts, stroke, w = 2.25, extra = "") =>
  `<polyline points="${pts.map(p => p.join(",")).join(" ")}" fill="none" stroke="${stroke}" stroke-width="${w}" stroke-linejoin="round"${extra}/>`;
// A dot that stays visible on any background: filled in the series colour, ringed in the canvas colour.
export const dot = (cx, cy, r, fill, t) => circle(cx, cy, r, fill, ` stroke="${t.bg}" stroke-width="1.5"`);

// ---------------------------------------------------------------- scales
export const linear = (d0, d1, r0, r1) => v => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
export const log10 = (d0, d1, r0, r1) => v => r0 + ((Math.log10(v) - Math.log10(d0)) / (Math.log10(d1) - Math.log10(d0))) * (r1 - r0);

// Push label centres apart so stacked labels never overlap (keeps order, stays within [lo, hi]).
export function spread(items, gap, lo, hi) {
  const s = [...items].sort((a, b) => a.y - b.y);
  for (let i = 1; i < s.length; i++) if (s[i].y - s[i - 1].y < gap) s[i].y = s[i - 1].y + gap;
  const over = s.length ? s[s.length - 1].y - hi : 0;
  if (over > 0) for (const it of s) it.y -= over;
  for (let i = s.length - 2; i >= 0; i--) if (s[i + 1].y - s[i].y < gap) s[i].y = s[i + 1].y - gap;
  if (s.length && s[0].y < lo) { const d = lo - s[0].y; for (const it of s) it.y += d; }
  return items;
}

// Footer line (what was run, n, caveat) in the muted colour, bottom-left.
export const footer = (y, s, t) => text(0, y, s, { fill: t.muted, size: MIN_TEXT });
