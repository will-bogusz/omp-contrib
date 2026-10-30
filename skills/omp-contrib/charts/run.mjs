#!/usr/bin/env bun
// Charts and drawn figures for an OMP PR body. Rules and workflow: ../references/charts.md.
//
//   bun run.mjs --help        the modes and their flags; writes nothing
//
// DIR holds chart.mjs and, for a chart of measurements, data.json (from your derive script; every value
// carries its source). A diagram's source is the code it draws, named in DIR/source/README.md.
//   export const meta = { pr: 15434, repo?: "can1357/oh-my-pi" }
//   export const charts = { <id>: { fn(data, theme) -> svg (W wide), narrow(data, theme) -> svg (NARROW wide,
//     the phone layout), alt(data) -> string, takeaway: string } }
//   export function place(body, data, h) -> the whole new body. `body` is the live body (gh pr view),
//     or --body FILE for a PR not opened yet, or closed and queued (its stored body, `pr-queue show`; the draft
//     and upload refuse the live body of such a PR). Helpers:
//     h.picture(id)                   the image block for chart <id> (a <picture> following the theme and,
//                                     below a 1244 px window, showing the phone layout; pr-images' markup)
//     h.loop(path, alt)               a motion loop from ./loop.py: `path` is its --out PREFIX (relative to
//                                     DIR), the four files placed as pr-images --loop prints them
//     h.still(path, alt)              a recording's end frame from `loop.py --make still`, both layouts
//                                     (pr-images --still), e.g. a whole task's result in view
//     h.video(path)                   a video's placeholder URL, to put on a line of its own with blank lines
//                                     around it, where GitHub renders it as its player (in view only when
//                                     the user picks it: references/charts.md, Motion); `--upload` uploads it
//     h.details(summary, md)          a collapsed block, e.g. for the exact table
//     h.swapTable(body, first, md)    body with the table whose header line starts with `first` replaced by md
//     h.table(body, first)            that table's Markdown, to move into h.details
//     h.replace(body, old, new)       one exact, unique replacement (a wording correction)
// Chart modules import "omp-charts/look.mjs" (canvas, palette, text) and "omp-charts/draw.mjs" (boxes,
// arrows, titles for diagrams); this script links lib/ into DIR/node_modules/omp-charts.
// Or DIR holds figures.json and no chart.mjs: timelines and decision flows drawn from a spec, each placed at
// a marker line or in a table's place (format: lib/shapes.mjs). Its `pr` may wait for the PR: draft with
// --body FILE, and --upload then says to queue out/body-final.md.
import { $ } from "bun";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { THEMES, W, NARROW, MIN_TEXT, SCALE, NARROW_SCALE } from "./lib/look.mjs";
import { openBrowser, svgPage, ghMarkdown, placeholders, mdPage, expectedSource, videoPlayer } from "./lib/page.mjs";
import { details, table, swapTable, replace } from "./lib/body.mjs";
import { fromFigures } from "./lib/shapes.mjs";
import { loadConfig, get, ompCheckout, cacheDir } from "./lib/config.mjs";

const HERE = dirname(new URL(import.meta.url).pathname);
const SCRIPTS = resolve(HERE, "../scripts");
const CONFIG = loadConfig();
// The oh-my-pi checkout precheck runs in: $OMP_REPO, else paths.checkout, else the enclosing clone; null skips precheck.
const OMP_REPO = ompCheckout(CONFIG);
// images.upload: "relay" (GitHub attachments) or "fork-links" (files committed to the fork; scripts/pr-images).
const UPLOAD_MODE = get(CONFIG, "images.upload", "relay");
const argv = process.argv.slice(2);
const arg = k => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : undefined; };
const flag = k => argv.includes(k);
// --help, and a flag where DIR belongs, exit before anything is written: no out/, node_modules or browser.
const USAGE = `usage: bun run.mjs DIR [--body FILE] [--chrome PATH | --ws URL]   draft: images, out/body.md, page check
       bun run.mjs DIR --upload                                    upload the placed images, out/body-final.md
       bun run.mjs DIR --verify                                    after scripts/pr-body: read back, check the live page
       bun run.mjs --help                                          this text`;
if (flag("--help") || flag("-h")) { console.log(USAGE); process.exit(0); }
if (argv[0]?.startsWith("-")) { console.error(`${USAGE}\nDIR is a flag, not a directory: nothing was written`); process.exit(2); }
const dir = resolve(argv[0] ?? ".");
const OUT = join(dir, "out");
mkdirSync(join(OUT, "svg"), { recursive: true });

const link = join(dir, "node_modules", "omp-charts");
if (!existsSync(link)) {
  // A dangling link (its charts checkout moved or was removed) is replaced, not kept.
  if (process.env.OMP_CHARTS_RELINKED) throw new Error(`${link} still does not resolve after relinking`);
  mkdirSync(dirname(link), { recursive: true });
  rmSync(link, { force: true });
  symlinkSync(join(HERE, "lib"), link);
  // Bun has already cached DIR's module lookups without the link: start again so the import resolves.
  process.exit(Bun.spawnSync([process.execPath, ...process.argv.slice(1)], {
    stdio: ["inherit", "inherit", "inherit"],
    env: { ...process.env, OMP_CHARTS_RELINKED: "1" },
  }).exitCode);
}
const { meta, charts, place } = !existsSync(join(dir, "chart.mjs")) && existsSync(join(dir, "figures.json"))
  ? fromFigures(JSON.parse(readFileSync(join(dir, "figures.json"), "utf8")))
  : await import(join(dir, "chart.mjs"));
const repo = meta.repo ?? get(CONFIG, "github.upstream_repo", "can1357/oh-my-pi");
// images.upload = "fork-links": the folder on the fork's asset branch these files go to (pr-images --folder).
const FOLDER = meta.pr ? `pr-${meta.pr}` : basename(dir);
const data = existsSync(join(dir, "data.json")) ? JSON.parse(readFileSync(join(dir, "data.json"), "utf8")) : {};
const read = f => readFileSync(f, "utf8");
const liveBody = async () => (await $`gh pr view ${meta.pr} --repo ${repo} --json body -q .body`.quiet()).stdout.toString().replace(/\n$/, "");
const PICTURE = /<picture>[\s\S]*?<\/picture>/g;
// Each chart's four PNGs, in the order pr-images prints their sources: wide dark, wide light, phone dark,
// phone light. The phone layout renders at 3x: pr-images shows it up to 440 px wide (look.mjs).
const LAYOUTS = [["", W, SCALE], ["-narrow", NARROW, NARROW_SCALE]];
const pngs = id => LAYOUTS.flatMap(([l]) => ["dark", "light"].map(th => join(OUT, `${id}${l}-${th}.png`)));
// A loop's or still's files in the order pr-images prints their sources: stills (wide, phone), then GIFs.
const footageFiles = (shape, prefix) => [`${prefix}-still.png`, `${prefix}-narrow-still.png`,
  ...(shape === "--loop" ? [`${prefix}.gif`, `${prefix}-narrow.gif`] : [])];
const svgWidth = s => Number(s.match(/<svg[^>]*\swidth="([\d.]+)"/)?.[1]);

// A closed PR whose change waits in the queue reopens with its stored body (`pr-queue open` posts it), so an
// edit to GitHub's body is lost (references/queue.md). {entry, message}: set for such a PR.
function bodyHome() {
  const r = Bun.spawnSync([join(SCRIPTS, "pr-queue"), ...(OMP_REPO ? ["--repo", OMP_REPO] : []), "body-home", String(meta.pr)], { stderr: "inherit" });
  if (r.exitCode !== 0) throw new Error(`pr-queue body-home ${meta.pr} failed (exit ${r.exitCode})`);
  return JSON.parse(r.stdout.toString());
}
function refuse(message) {
  console.error(`${message}: draft from it with --body FILE`);
  process.exit(1);
}

// The <picture> for one chart (or, with shape --loop / --still, one recording), written by pr-images;
// files with a known URL are not uploaded again.
function pictureMarkup(alt, files, urls, shape = "--themed") {
  const known = files.filter(f => urls[f]).flatMap(f => ["--uploaded", `${f}=${urls[f]}`]);
  const r = Bun.spawnSync([join(SCRIPTS, "pr-images"), "upload", "--repo", repo, "--folder", FOLDER, shape, "--scale", "2", "--alt", alt, ...known, ...files], { stderr: "inherit" });
  const md = r.stdout.toString().trim();
  if (r.exitCode !== 0 || !md.startsWith("<picture>")) throw new Error(`pr-images failed (exit ${r.exitCode}) for ${basename(files[0])}`);
  const got = [...md.matchAll(/srcset="([^"]+)"/g)].map(m => m[1]);
  if (got.length !== files.length) throw new Error(`pr-images printed ${got.length} sources for ${files.length} files`);
  return { md, urls: Object.fromEntries(files.map((f, i) => [f, got[i]])) };
}

// precheck's body checks (length outside tables/<details>/images/checklist, own-words line, mentions, merge-order text).
async function precheck(file) {
  if (!OMP_REPO || !existsSync(OMP_REPO)) return `precheck skipped: no oh-my-pi checkout${OMP_REPO ? ` at ${OMP_REPO}` : ""} (set OMP_REPO or paths.checkout)`;
  const r = await $`${SCRIPTS}/precheck --body ${file} --no-siblings`.cwd(OMP_REPO).quiet().nothrow();
  return r.stdout.toString().split("\n").filter(l => /^(FIX|WARN)\s+(body|mention|order)\b/.test(l)).join("\n") || "precheck body checks: clean";
}
async function diff(a, b, out) {
  const r = await $`diff -u ${a} ${b}`.quiet().nothrow();
  writeFileSync(out, r.stdout.toString());
  return r.stdout.toString().split("\n").filter(l => /^[-+][^-+]/.test(l)).length;
}

// The description on the real PR page, signed out, at each window width in dark and light: every picture
// loads the source its media picks, keeps its shape, shows its smallest text at 11 px or more and at least
// 2 image pixels per CSS pixel (sharp on a 2x screen), and the page never scrolls sideways. A recording
// (a loop or still: no colour-scheme source) skips the text check, since footage text isn't drawn to our
// sizes, and needs 1 image pixel per CSS pixel; with a reduced-motion source, every width and scheme is
// checked again for a reader who asked for reduced motion. Every video player GitHub renders loads its
// metadata and stays in the column; its line reports the footage's size inside the player (a wide clip is
// letterboxed into the player's 200 px minimum height on a phone) and the file name in its header.
// `html` null = the live body. Shots: out/<prefix>-<width>-<scheme>[-reduce].png. Returns whether every
// check held.
const CHECK_WIDTHS = [1280, 1100, 430, 390]; // full desktop, half-width desktop, two phones
async function pageCheck(R, md, prefix, html, files) {
  const pics = md.match(PICTURE) ?? [];
  const players = ((html ?? await ghMarkdown(md, repo)).match(/<video\b/g) ?? []).length;
  const motions = pics.some(p => p.includes("prefers-reduced-motion")) ? ["no-preference", "reduce"] : ["no-preference"];
  let ok = true;
  for (const motion of motions) {
    for (const width of CHECK_WIDTHS) {
      for (const scheme of ["dark", "light"]) {
        const reduce = motion === "reduce";
        const file = join(OUT, `${prefix}-${width}-${scheme}${reduce ? "-reduce" : ""}.png`);
        const got = await R.prPage({ repo, pr: meta.pr, width, scheme, motion, html, files, file });
        const rows = got.pictures.map((im, i) => {
          const pic = pics[i] ?? "";
          const footage = pic !== "" && !pic.includes("prefers-color-scheme");
          const want = pic ? expectedSource(pic, width, scheme, motion) : "";
          const phone = [...pic.matchAll(/<source\b[^>]*\swidth="\d+"[^>]*\ssrcset="([^"]+)"/g)].some(m => m[1] === want);
          const text = (MIN_TEXT * im.w) / (phone ? NARROW : W), density = im.nw / im.w;
          const problems = [
            !im.loaded && "not loaded",
            pic && !im.src.startsWith(want) && `shows ${im.src}`,
            Math.abs(im.h / im.w - im.nh / im.nw) > 0.01 && `stretched to ${Math.round(im.w)}x${Math.round(im.h)}`,
            !footage && text < 11 && `smallest text ${text.toFixed(1)} px`,
            density < (footage ? 1 : 2) && `blurry: ${density.toFixed(2)} image px per CSS px`,
          ].filter(Boolean);
          const kind = `${footage ? (pic.includes("prefers-reduced-motion") ? "loop " : "still ") : ""}${phone ? "phone" : "wide"}`;
          return { good: !problems.length, line: `${kind} ${Math.round(im.w)}x${Math.round(im.h)} px, ${footage ? "" : `text ${text.toFixed(1)} px, `}${density.toFixed(2)}x${problems.length ? ", PROBLEM: " + problems.join("; ") : ""}` };
        });
        const vids = got.videos.map(v => {
          const collapsed = v.w === 0;
          const problems = [!v.loaded && "not loaded", !v.inColumn && "wider than the column"].filter(Boolean);
          const size = collapsed ? "collapsed" : `${Math.round(v.w)}x${Math.round(v.h)} px, footage ${Math.round(v.footage[0])}x${Math.round(v.footage[1])}`;
          return { good: !problems.length, line: `video "${v.name}" ${size}${problems.length ? ", PROBLEM: " + problems.join("; ") : ""}` };
        });
        const good = rows.length === pics.length && rows.every(r => r.good) && vids.length === players && vids.every(v => v.good) && !got.overflow;
        ok &&= good;
        const counts = `${rows.length} of ${pics.length} picture(s)${players || vids.length ? `, ${vids.length} of ${players} video(s)` : ""}`;
        console.log(`${width} px ${scheme}${reduce ? " reduced motion" : ""}: ${counts}${got.overflow ? ", PAGE SCROLLS SIDEWAYS" : ""}: ${[...rows, ...vids].map(r => r.line).join(" | ")} (out/${basename(file)})`);
      }
    }
  }
  return ok;
}

if (flag("--upload")) await upload();
else if (flag("--verify")) await verify();
else await draft();

// Runs fn with a browser and closes it on every path, a throw included: BHW-5 found Chrome for Testing left by a throw
// between launch and close. openBrowser launches first, so it stays outside the try.
async function withBrowser(fn) {
  const R = await openBrowser({ ws: arg("--ws"), chrome: arg("--chrome") });
  try {
    return await fn(R);
  } finally {
    await R.close();
  }
}

async function draft() {
  // Body files hold the exact body (no added final newline), so `scripts/pr-body` posts it byte for byte.
  if (!arg("--body")) {
    if (!meta.pr) { console.error("no PR number yet, so no live body: draft with --body FILE"); process.exit(1); }
    const { message } = bodyHome();
    if (message) refuse(message);
  }
  const live = arg("--body") ? read(arg("--body")) : await liveBody();
  writeFileSync(join(OUT, "live.md"), live);
  await withBrowser(R => draftWith(R, live));
}

// The draft's pictures and body, with the browser open for the duration of withBrowser.
async function draftWith(R, live) {
  for (const [id, c] of Object.entries(charts)) {
    if (!c.takeaway) throw new Error(`charts.${id}.takeaway is missing: one sentence the chart must convey (cold-read grades against it)`);
    if (!c.narrow) throw new Error(`charts.${id}.narrow is missing: the phone layout, ${NARROW} px wide (references/charts.md)`);
    for (const [l, width, scale] of LAYOUTS) {
      for (const th of ["dark", "light"]) {
        const s = (l ? c.narrow : c.fn)(data, THEMES[th]);
        if (svgWidth(s) !== width) throw new Error(`${id}${l}: the SVG is ${svgWidth(s)} px wide, not ${width}`);
        writeFileSync(join(OUT, "svg", `${id}${l}-${th}.svg`), s);
        await R.shot(svgPage(s, THEMES[th].bg), join(OUT, `${id}${l}-${th}.png`), { scheme: th, scale });
      }
    }
  }
  const ph = placeholders(OUT);
  const placed = [], drafts = {}; // drafts: chart or recording id -> its <picture> with placeholder URLs, as placed in body.md
  const footage = {}; // "loop:<path>" / "still:<path>" -> { shape, prefix, alt }
  const videos = {}; // "video:<path>" -> { file, draft: its placeholder URL, alone on its line in body.md }
  const recording = (shape, path, alt) => {
    const prefix = resolve(dir, path), id = `${shape.slice(2)}:${path}`;
    const files = footageFiles(shape, prefix);
    const missing = files.filter(f => !existsSync(f));
    if (missing.length) throw new Error(`${id}: no ${missing.map(f => basename(f)).join(", ")} (charts/loop.py --out ${path}${shape === "--still" ? " --make still" : ""})`);
    if (!alt) throw new Error(`${id}: alt text is missing: the takeaway, as for a chart`);
    placed.push(id);
    footage[id] = { shape, prefix, alt };
    return (drafts[id] = pictureMarkup(alt, files, Object.fromEntries(files.map(f => [f, ph.url(f)])), shape).md);
  };
  const h = {
    picture(id) {
      placed.push(id);
      const files = pngs(id);
      return (drafts[id] = pictureMarkup(charts[id].alt(data), files, Object.fromEntries(files.map(f => [f, ph.url(f)]))).md);
    },
    loop: (path, alt) => recording("--loop", path, alt),
    still: (path, alt) => recording("--still", path, alt),
    video(path) {
      const file = resolve(dir, path), id = `video:${path}`;
      if (!/\.(mp4|mov|webm)$/i.test(file) || !existsSync(file)) throw new Error(`${id}: no such MP4, MOV or WebM (charts/loop.py --make mp4)`);
      return (videos[id] = { file, draft: ph.url(file) }).draft;
    },
    details, table, swapTable, replace,
  };
  const body = place(live, data, h); // as returned: a trailing blank line in the live body survives
  writeFileSync(join(OUT, "body.md"), body);
  const changed = await diff(join(OUT, "live.md"), join(OUT, "body.md"), join(OUT, "body.diff"));
  let html = await ghMarkdown(body, repo);
  if (Object.keys(videos).length) {
    // GitHub renders a placeholder URL as a link: put its player in that link's place (lib/page.mjs).
    const player = await videoPlayer();
    for (const [id, v] of Object.entries(videos)) {
      const line = new RegExp(`<p dir="auto"><a href="${v.draft}"[^>]*>${v.draft}</a></p>`, "g");
      const n = (html.match(line) ?? []).length;
      if (n !== 1) throw new Error(`${id}: its URL renders as a line of its own ${n} times, need exactly 1 (blank lines around h.video's URL)`);
      html = html.replace(line, () => player(v.draft, basename(v.file)));
    }
  }
  let pages;
  if (arg("--body")) {
    // No PR page yet: the body in a github-markdown-css box at a desktop and a phone window.
    const local = ph.localize(html, OUT);
    for (const [view, width] of [["", 1440], ["-phone", 390]]) {
      for (const scheme of ["dark", "light"]) {
        const f = join(OUT, `context${view}-${scheme}.html`);
        writeFileSync(f, mdPage(local, scheme, `${meta.pr ? `PR #${meta.pr} draft body` : "Draft body"}, rendered by GitHub's markdown API`, width));
        await R.fullShot(f, join(OUT, `context${view}-${scheme}.png`), { scheme, width });
      }
    }
    pages = "previews: out/context{,-phone}-{dark,light}.png";
  } else {
    pages = (await pageCheck(R, body, "page", html, ph.files)) ? "page check: clean" : "page check: PROBLEMS above";
  }
  const manifest = {
    pr: meta.pr, repo, placed, drafts, footage, videos, bodyFile: arg("--body") ? resolve(arg("--body")) : null,
    charts: Object.fromEntries(Object.entries(charts).map(([id, c]) => {
      const [dark, light, ndark, nlight] = pngs(id).map(f => basename(f));
      return [id, { dark, light, narrow: { dark: ndark, light: nlight }, alt: c.alt(data), takeaway: c.takeaway }];
    })),
  };
  writeFileSync(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 1));
  console.log(`charts: ${Object.keys(charts).map(id => `out/${id}{,-narrow}-{dark,light}.png`).join(", ")}; placed: ${placed.join(", ") || "none"}`);
  console.log(`body: out/body.md (${changed} changed lines vs live, out/body.diff); ${pages}`);
  console.log(await precheck(join(OUT, "body.md")));
}

async function upload() {
  const m = JSON.parse(read(join(OUT, "manifest.json")));
  // No PR yet: the body was drafted from a file and waits to be queued with it.
  const home = meta.pr ? bodyHome() : {};
  if (!meta.pr && !m.bodyFile) { console.error("no PR number yet, so no live body: draft with --body FILE first"); process.exit(1); }
  if (home.message && !m.bodyFile) refuse(home.message);
  let body = read(join(OUT, "body.md"));
  const alts = md => [...md.matchAll(/<img[^>]*\salt="([^"]*)"/g)].map(a => a[1]).join("\n");
  if ((body.match(PICTURE) ?? []).length !== m.placed.length) throw new Error(`body.md's <picture> blocks don't match the manifest's placed charts and recordings: rerun the draft`);
  // One upload per file version: out/uploads.json maps "<repo> <sha1 of the file>" to its URL, and so does a cache
  // shared by every body folder (<cache>/omp-contrib/uploads.json), so a loop placed in several PR bodies and a post
  // is uploaded once: GitHub answers the upload policy with HTTP 429 after about a hundred uploads in a few minutes.
  // A fork-links URL is keyed apart from an attachment, so switching images.upload never reuses the other kind.
  const cacheFile = join(OUT, "uploads.json"), sharedFile = join(cacheDir(), "uploads.json");
  const readCache = f => (existsSync(f) ? JSON.parse(read(f)) : {});
  const cache = { ...readCache(sharedFile), ...readCache(cacheFile) };
  const remember = () => {
    writeFileSync(cacheFile, JSON.stringify(cache, null, 1));
    mkdirSync(dirname(sharedFile), { recursive: true });
    writeFileSync(sharedFile, JSON.stringify({ ...readCache(sharedFile), ...cache }, null, 1));
  };
  const key = f => `${UPLOAD_MODE === "fork-links" ? "fork-links " : ""}${m.repo} ${createHash("sha1").update(readFileSync(f)).digest("hex")}`;
  // Each draft <picture> (placeholder URLs) is swapped for its uploaded one by identity, not by position:
  // place() may call h.picture in any order (#15291 and #15402 were published swapped).
  for (const id of m.placed) {
    const rec = m.footage?.[id];
    const files = rec ? footageFiles(rec.shape, rec.prefix) : pngs(id);
    const { md, urls } = pictureMarkup(rec ? rec.alt : m.charts[id].alt, files, Object.fromEntries(files.map(f => [f, cache[key(f)]])), rec?.shape);
    for (const f of files) cache[key(f)] = urls[f];
    remember();
    const n = body.split(m.drafts[id]).length - 1;
    if (n !== 1) throw new Error(`body.md holds ${id}'s draft <picture> ${n} times, need exactly 1: rerun the draft`);
    body = body.replace(m.drafts[id], () => md);
  }
  // A video is a bare URL: pr-images prints it, swapped for the placeholder by identity like a picture.
  for (const [id, v] of Object.entries(m.videos ?? {})) {
    let url = cache[key(v.file)];
    if (!url) {
      const r = Bun.spawnSync([join(SCRIPTS, "pr-images"), "upload", "--repo", m.repo, "--folder", FOLDER, v.file], { stderr: "inherit" });
      url = r.stdout.toString().trim();
      if (r.exitCode !== 0 || !/^https:\/\/\S+$/.test(url)) throw new Error(`pr-images failed (exit ${r.exitCode}) for ${basename(v.file)}`);
      cache[key(v.file)] = url;
      remember();
    }
    const n = body.split(v.draft).length - 1;
    if (n !== 1) throw new Error(`body.md holds ${id}'s draft URL ${n} times, need exactly 1: rerun the draft`);
    body = body.replace(v.draft, () => url);
  }
  if (alts(body) !== alts(read(join(OUT, "body.md")))) throw new Error("the uploaded pictures' order differs from body.md's");
  writeFileSync(join(OUT, "body-final.md"), body);
  const changed = await diff(join(OUT, "live.md"), join(OUT, "body-final.md"), join(OUT, "body-final.diff"));
  console.log(`out/body-final.md: ${changed} changed lines vs the body fetched at draft time (out/body-final.diff)`);
  console.log(await precheck(join(OUT, "body-final.md")));
  console.log(nextStep(home, m, join(OUT, "body-final.md")));
}

// What to do with body-final.md: update a queued entry's stored body, queue a body that has no PR yet, or
// post it to the open PR.
function nextStep(home, m, file) {
  if (home.entry) return `next: pr-queue set ${home.entry} --body ${file}`;
  if (!meta.pr) return `next, no PR yet: queue it with this body:\n  pr-queue add <branch> --title … --body ${file}\n  (an entry already queued: pr-queue set <id> --body ${file})`;
  return `next, if the live body still equals out/live.md:\n  ${join(SCRIPTS, "pr-body")} ${m.pr} ${file} --repo ${m.repo}\n  bun ${join(HERE, "run.mjs")} ${dir} --verify`;
}

async function verify() {
  if (!meta.pr) { console.error("no PR number yet: --verify reads a PR's live body; add it to figures.json once the PR is open"); process.exit(1); }
  const live = await liveBody(), want = read(join(OUT, "body-final.md"));
  const same = live.replace(/\n+$/, "") === want.replace(/\n+$/, ""); // trailing newlines do not count (pr-body's rule)
  console.log(same ? "read-back: identical to out/body-final.md" : "read-back: DIFFERS from out/body-final.md");
  const pageOk = await withBrowser(R => pageCheck(R, live, "live", null));
  process.exit(pageOk && same ? 0 : 1);
}
