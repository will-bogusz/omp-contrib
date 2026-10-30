// omp-contrib's config file for the charts and the extension (contract: ../../references/config.md).
// $OMP_CONTRIB_CONFIG, else ${XDG_CONFIG_HOME:-~/.config}/omp-contrib/config.toml (%APPDATA% on Windows).
// A missing file is valid: every key has a default. Read with Bun.TOML; no writer here (the wizard writes it).
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export function configPath(env = process.env, platform = process.platform) {
  if (env.OMP_CONTRIB_CONFIG) return env.OMP_CONTRIB_CONFIG;
  if (platform === "win32" && env.APPDATA) return join(env.APPDATA, "omp-contrib", "config.toml");
  return join(env.XDG_CONFIG_HOME || join(env.HOME || homedir(), ".config"), "omp-contrib", "config.toml");
}

// ${XDG_CACHE_HOME:-~/.cache}/omp-contrib (%LOCALAPPDATA% on Windows), as scripts/omp_config.py's cache_dir; not created.
export function cacheDir(env = process.env, platform = process.platform) {
  if (platform === "win32" && env.LOCALAPPDATA) return join(env.LOCALAPPDATA, "omp-contrib");
  return join(env.XDG_CACHE_HOME || join(env.HOME || homedir(), ".cache"), "omp-contrib");
}

// The parsed file, {} when there is none; a file that does not parse throws with its path.
export function loadConfig(env = process.env) {
  const file = configPath(env);
  if (!existsSync(file)) return {};
  try {
    return Bun.TOML.parse(readFileSync(file, "utf8"));
  } catch (err) {
    throw new Error(`${file}: ${err.message}`);
  }
}

// get(cfg, "models.cold_read", fallback): the value at a dotted key, the fallback when unset or "".
export function get(cfg, key, fallback) {
  const v = key.split(".").reduce((o, k) => (o == null ? undefined : o[k]), cfg);
  return v === undefined || v === null || v === "" ? fallback : v;
}

// The oh-my-pi checkout: $OMP_REPO, else paths.checkout, else the enclosing git toplevel of `cwd` when it
// is an oh-my-pi clone; null when none of those holds.
export function ompCheckout(cfg = loadConfig(), env = process.env, cwd = process.cwd()) {
  const set = env.OMP_REPO || get(cfg, "paths.checkout", "");
  if (set) return set.replace(/^~(?=\/|$)/, env.HOME || homedir());
  const top = Bun.spawnSync(["git", "-C", cwd, "rev-parse", "--show-toplevel"], { stderr: "ignore" });
  const dir = top.exitCode === 0 ? top.stdout.toString().trim() : "";
  return dir && existsSync(join(dir, "packages", "coding-agent")) ? dir : null;
}
