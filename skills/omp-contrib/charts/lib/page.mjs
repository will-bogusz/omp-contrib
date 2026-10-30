// Rendering plumbing for run.mjs: headless Chrome for Testing screenshots at 2x, PNG optimisation,
// GitHub's own markdown renderer, and github-markdown-css pages. Needs `gh`; pngquant and oxipng only
// make the PNGs smaller (a missing one is skipped with a warning).
import { $ } from "bun";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, extname, join, relative } from "node:path";
import puppeteer from "puppeteer-core";
import { W, FONT } from "./look.mjs";

const VENDOR = join(dirname(new URL(import.meta.url).pathname), "../vendor");

// Chrome for Testing's executable inside its version folder, per @puppeteer/browsers platform (the layout
// `computeExecutablePath` uses, which is how omp installs it: <cache>/chrome/<platform>-<buildId>/<this>).
const CFT_LAYOUT = {
  mac_arm: ["mac-arm64", "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"],
  mac: ["mac-x64", "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"],
  linux: ["linux64", "chrome"],
  linux_arm: ["linux64", "chrome"],
  win64: ["win64", "chrome.exe"],
  win32: ["win32", "chrome.exe"],
};
const cftPlatform = (platform, arch) =>
  platform === "darwin" ? (arch === "arm64" ? "mac_arm" : "mac")
    : platform === "linux" ? (arch === "arm64" ? "linux_arm" : "linux")
      : platform === "win32" ? (arch === "ia32" ? "win32" : "win64") : undefined;
// Chrome or Chromium installed system-wide, which omp's own browser prefers off macOS (and so may never
// download Chrome for Testing there).
const SYSTEM_CHROME = {
  linux: ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium"],
  win32: ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"],
};

// The browser run.mjs renders with, headless, never the user's own Chrome profile: --chrome PATH, else
// $CHROME_PATH or $PUPPETEER_EXECUTABLE_PATH, else omp's managed Chrome for Testing (the one `browser` tabs
// use; ~/.omp/puppeteer, or $XDG_CACHE_HOME/omp/puppeteer once omp moved to XDG on Linux), newest version
// first, else on Linux and Windows a system Chrome. The arguments exist for tests.
export function defaultChrome({ flag, env = process.env, platform = process.platform, arch = process.arch,
  home = env.HOME || homedir(), exists = existsSync, list = readdirSync } = {}) {
  if (flag) return flag;
  if (env.CHROME_PATH) return env.CHROME_PATH;
  if (env.PUPPETEER_EXECUTABLE_PATH) return env.PUPPETEER_EXECUTABLE_PATH;
  const cft = cftPlatform(platform, arch);
  const roots = [platform === "linux" && env.XDG_CACHE_HOME ? join(env.XDG_CACHE_HOME, "omp", "puppeteer") : null,
    join(home, ".omp", "puppeteer")].filter(Boolean).map(r => join(r, "chrome"));
  const version = d => d.slice(d.indexOf("-") + 1).split(".").map(Number);
  const newer = (a, b) => { const x = version(a), y = version(b); for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (y[i] ?? 0) - (x[i] ?? 0); return 0; };
  if (cft) {
    const [folder, exe] = CFT_LAYOUT[cft];
    for (const root of roots) {
      const dirs = exists(root) ? list(root).filter(d => d.startsWith(`${cft}-`)).sort(newer) : [];
      for (const d of dirs) {
        const path = join(root, d, `chrome-${folder}`, exe);
        if (exists(path)) return path;
      }
    }
  }
  for (const path of SYSTEM_CHROME[platform] ?? []) if (exists(path)) return path;
  throw new Error(`no Chrome found (looked in ${roots.join(", ")}${SYSTEM_CHROME[platform] ? " and the system Chrome paths" : ""}): `
    + "pass --chrome PATH or --ws URL, set CHROME_PATH, or let omp install its Chrome for Testing (open any `browser` tab once)");
}

export async function openBrowser({ ws, chrome } = {}) {
  const browser = ws
    ? await puppeteer.connect({ browserWSEndpoint: ws, defaultViewport: null })
    : await puppeteer.launch({ executablePath: defaultChrome({ flag: chrome }), headless: true, args: ["--allow-file-access-from-files"] });
  const page = await browser.newPage();
  const tmpDir = `/tmp/omp-charts-${process.pid}`;
  await $`mkdir -p ${tmpDir}`.quiet();
  let n = 0, intercepting = false, served = new Map();
  return {
    page,
    // Screenshot #root of an HTML string at `scale` device pixels per CSS pixel.
    async shot(html, file, { scheme = "dark", width = W + 40, scale = 2 } = {}) {
      await page.setViewport({ width, height: 800, deviceScaleFactor: scale });
      await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }]);
      const tmp = join(tmpDir, `${n++}.html`);
      writeFileSync(tmp, html);
      await page.goto("file://" + tmp, { waitUntil: "load" });
      await page.evaluate(() => document.fonts.ready);
      await (await page.$("#root")).screenshot({ path: file });
      await optimize(file);
    },
    // Full-page screenshot of an HTML file or URL at a window `width` px wide, 1x (what a reader sees);
    // with `selector`, only that element.
    async fullShot(url, file, { scheme = "dark", width = 1440, selector } = {}) {
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }]);
      await page.goto(url.startsWith("http") ? url : "file://" + url, { waitUntil: "networkidle2", timeout: 60000 });
      await page.evaluate(() => document.fonts.ready);
      if (selector) await (await page.$(selector)).screenshot({ path: file });
      else await page.screenshot({ path: file, fullPage: true });
      await optimize(file);
    },
    // The PR page on github.com, signed out, in a window `width` px wide; with `html`, the description's
    // rendered body swapped for it, placeholder attachment URLs answered from local files (`files`: url ->
    // path, served with the type of their extension). `motion` "reduce" emulates a reader who asked for
    // reduced motion. Shoots the description to `file` (1x) and returns each picture's geometry and the
    // source shown, and each video player's: its box, the footage inside it, the file name in its header.
    async prPage({ repo, pr, width, scheme, motion = "no-preference", html, files = new Map(), file }) {
      if (!intercepting) {
        intercepting = true;
        await page.setRequestInterception(true);
        page.on("request", req => (served.has(req.url())
          ? req.respond({ status: 200, contentType: contentType(served.get(req.url())), body: readFileSync(served.get(req.url())) })
          : req.continue()));
      }
      served = files;
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }, { name: "prefers-reduced-motion", value: motion }]);
      await page.goto(`https://github.com/${repo}/pull/${pr}`, { waitUntil: "networkidle2", timeout: 60000 });
      if (html != null) await page.evaluate(h => { document.querySelector(".comment-body").innerHTML = h; }, html);
      await page.evaluate(async () => {
        await document.fonts.ready;
        const body = document.querySelector(".comment-body");
        const imgs = [...body.querySelectorAll("img")], videos = [...body.querySelectorAll("video")];
        await Promise.all([
          ...imgs.map(i => (i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 15000); }))),
          ...videos.map(v => (v.readyState >= 1 ? 0 : new Promise(r => { v.onloadedmetadata = v.onerror = r; setTimeout(r, 15000); }))),
        ]);
      });
      await (await page.$(".comment-body")).screenshot({ path: file });
      await optimize(file);
      return page.evaluate(() => {
        const body = document.querySelector(".comment-body"), column = body.getBoundingClientRect();
        return {
          overflow: document.documentElement.scrollWidth > window.innerWidth,
          pictures: [...body.querySelectorAll("picture img")].map(i => {
            const r = i.getBoundingClientRect();
            return { loaded: i.complete && i.naturalWidth > 0, src: i.currentSrc, w: r.width, h: r.height, nw: i.naturalWidth, nh: i.naturalHeight };
          }),
          videos: [...body.querySelectorAll("video")].map(v => {
            const r = v.getBoundingClientRect(), fit = Math.min(r.width / v.videoWidth, r.height / v.videoHeight);
            return { loaded: v.readyState >= 1 && v.videoWidth > 0, w: r.width, h: r.height, nw: v.videoWidth, nh: v.videoHeight,
              footage: v.videoWidth ? [v.videoWidth * fit, v.videoHeight * fit] : [0, 0], inColumn: r.right <= column.right + 0.5,
              name: v.closest("details")?.querySelector("summary")?.textContent.trim() ?? "" };
          }),
        };
      });
    },
    async close() {
      await page.close();
      if (ws) browser.disconnect(); else await browser.close();
      await $`rm -rf ${tmpDir}`.quiet();
    },
  };
}

// pngquant (lossy palette) then oxipng (lossless); either one missing is skipped with one warning per run.
const missingTools = new Set();
export async function optimize(file) {
  for (const [tool, run] of [
    ["pngquant", () => $`pngquant --force --skip-if-larger --quality 75-95 --speed 1 --output ${file} ${file}`.quiet().nothrow()],
    ["oxipng", () => $`oxipng -q -o 4 --strip safe ${file}`.quiet()],
  ]) {
    if (!Bun.which(tool)) {
      if (!missingTools.has(tool)) console.warn(`warning: ${tool} not found, PNGs stay larger (install it to shrink them)`);
      missingTools.add(tool);
      continue;
    }
    await run();
  }
}
export const svgPage = (svg, bg) =>
  `<!doctype html><meta charset=utf-8><style>html,body{margin:0;background:${bg}}#root{display:inline-block;line-height:0}</style><div id=root>${svg}</div>`;

export async function ghMarkdown(md, repo) {
  return (await $`gh api markdown -f text=${md} -f mode=gfm -f context=${repo}`.quiet()).stdout.toString();
}

// GitHub renders an uploaded video's URL on a line of its own as its player, but a placeholder URL as a
// plain link. So a draft takes the player's markup from GitHub's rendering of a real upload (#15185's demo
// clip, in its body since 2026-10-10) on every run, and puts the placeholder and the file's name in it.
// If GitHub ever stops rendering that line as a player, the draft stops rather than use stale markup.
const VIDEO_PROBE = "https://github.com/user-attachments/assets/56755bfe-7127-49fc-a32d-b22f5fe7decc";
export async function videoPlayer() {
  const html = await ghMarkdown(VIDEO_PROBE, "can1357/oh-my-pi");
  const block = html.match(/<details\b[^>]*>[\s\S]*?<video\b[\s\S]*?<\/details>/)?.[0];
  const name = block?.match(/<span class="m-1">([^<]*)<\/span>/);
  const src = block?.match(/<video\b[^>]*\ssrc="([^"]+)"/);
  if (!block || !name || !src) throw new Error(`GitHub no longer renders a video URL line as its player (${VIDEO_PROBE}); see references/charts.md, Motion`);
  return (url, fileName) => block.split(src[1]).join(url).replace(name[0], `<span class="m-1">${fileName}</span>`);
}

const TYPES = { ".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm" };
const contentType = f => TYPES[extname(f).toLowerCase()] ?? "application/octet-stream";

// The source a browser picks from a <picture> (pr-images' markup) for a window `width` px wide in
// `scheme`, with `motion` "reduce" for a reader who asked for reduced motion: the first source whose
// media all match (a source with no media always matches), else the <img>.
export function expectedSource(pic, width, scheme, motion = "no-preference") {
  const q = c => {
    let m;
    if ((m = c.match(/^\(min-width: (\d+)px\)$/))) return width >= +m[1];
    if ((m = c.match(/^\(prefers-color-scheme: (\w+)\)$/))) return scheme === m[1];
    if ((m = c.match(/^\(prefers-reduced-motion: (\w+)\)$/))) return motion === m[1];
    throw new Error(`no rule for media ${c}`);
  };
  const sources = [...pic.matchAll(/<source\b([^>]*)>/g)].map(([, a]) => [a.match(/\smedia="([^"]+)"/)?.[1], a.match(/\ssrcset="([^"]+)"/)?.[1]]);
  const src = sources.find(([media]) => media === undefined || media.split(" and ").every(q));
  return src?.[1] ?? pic.match(/<img[^>]*\ssrc="([^"]+)"/)[1];
}

// Well-formed placeholder user-attachments URLs, mapped back to local files until the upload.
export function placeholders(root) {
  const urlFor = new Map();
  return {
    files: urlFor, // placeholder url -> local file, answered by prPage
    url(file) {
      const h = createHash("sha1").update(relative(root, file)).digest("hex");
      const u = `https://github.com/user-attachments/assets/${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-8${h.slice(17, 20)}-${h.slice(20, 32)}`;
      urlFor.set(u, file);
      return u;
    },
    localize: (html, fromDir) => html.replace(/https:\/\/github\.com\/user-attachments\/assets\/[0-9a-f-]{36}/g, u => (urlFor.has(u) ? relative(fromDir, urlFor.get(u)) : u)),
  };
}

// A PR comment box as github.com lays it out in a window `width` px wide (1440: 814 px box at 168 px;
// 390: 356 px box, a 324 px column), styled by github-markdown-css (vendored copies).
export function mdPage(htmlBody, scheme, header, width = 1440) {
  const dark = scheme === "dark", phone = width < 768;
  const bg = dark ? "#0d1117" : "#ffffff", border = dark ? "#3d444d" : "#d1d9e0", head = dark ? "#151b23" : "#f6f8fa", muted = dark ? "#9198a1" : "#59636e";
  const css = `${readFileSync(join(VENDOR, `github-markdown-${scheme}.css`), "utf8")}
  html,body{margin:0;background:${bg}}
  .markdown-body{font-size:14px;line-height:1.5;background:${bg}}
  .frame{width:${width}px;padding:24px 0 40px}
  .box{margin-left:${phone ? 16 : 168}px;width:${phone ? width - 34 : 814}px;border:1px solid ${border};border-radius:6px;overflow:hidden}
  .hdr{background:${head};border-bottom:1px solid ${border};padding:10px 16px;color:${muted};font:14px ${FONT}}
  .box .markdown-body{padding:16px}`;
  return `<!doctype html><html><head><meta charset=utf-8><style>${css}</style></head><body><div class=frame><div class=box><div class=hdr>${header}</div><div class="markdown-body">${htmlBody}</div></div></div></body></html>`;
}
