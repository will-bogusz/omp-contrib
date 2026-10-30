/**
 * checkout-guard: in a contribution session, refuse file edits in the user's oh-my-pi checkout, so a fix
 * goes through a worktree on `<branch_prefix><topic>` as the skill's chain requires.
 *
 * Why a guard and not more wording: asked in plain words to "fix it upstream", Haiku 5.5 read the skill
 * and still patched the checkout directly, skipping the duplicate scan, branch, review and queue
 * (cross-model check, 2026-10-30, case c).
 *
 * A session enters contribution mode when its prompt is the expanded `/contribute` command, or when it
 * reads `skill://omp-contrib` (or any file under this plugin's skill directory) or runs one of its
 * scripts. From then on a `tool_call` of `edit`, `write` or `ast_edit` whose target resolves inside the
 * checkout (`paths.checkout`, else the oh-my-pi clone around the session's cwd), and not inside a linked
 * worktree, is blocked with the next steps. Outside contribution mode nothing is blocked; reads and bash
 * are never blocked. Every failure (config, git) fails open with a log line: a throwing `tool_call`
 * handler would block every tool.
 */
import { existsSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { get, loadConfig } from "../skills/omp-contrib/charts/lib/config.mjs";

/** The first line of the expanded `/contribute` command (commands/contribute.md). */
export const COMMAND_MARKER = "You are running `/contribute` from the omp-contrib plugin";

const SKILL_DIR = resolve(import.meta.dir, "..", "skills", "omp-contrib");
const WRITE_TOOLS: Record<string, true> = { edit: true, write: true, ast_edit: true };

/** Whether a read path or bash command touches the skill (its URL, its directory, its scripts). */
export function touchesSkill(text: string, skillDir: string = SKILL_DIR): boolean {
	return text.includes("skill://omp-contrib") || text.includes(skillDir) || text.includes("skills/omp-contrib/");
}

/** The paths a write tool targets, from its normalized event input; ast_edit globs cut to their static prefix. */
export function targetPaths(toolName: string, input: Record<string, unknown>): string[] {
	const raw: unknown[] = [];
	if (typeof input.path === "string") raw.push(input.path);
	if (Array.isArray(input.paths)) raw.push(...input.paths);
	const paths = raw.filter((p): p is string => typeof p === "string" && p.length > 0 && !p.includes("://"));
	if (toolName !== "ast_edit") return [...new Set(paths)];
	return [...new Set(paths.map((p) => p.split(/[*?[{]/, 1)[0] || "."))];
}

function absolute(path: string, cwd: string): string {
	const expanded = path.replace(/^~(?=\/|$)/, homedir());
	return isAbsolute(expanded) ? expanded : resolve(cwd, expanded);
}

/** realpath of the nearest existing ancestor, with the missing tail re-appended (new files). */
function realish(path: string): string {
	let head = path;
	const tail: string[] = [];
	while (!existsSync(head)) {
		const up = dirname(head);
		if (up === head) return path;
		tail.unshift(head.slice(up.length + 1));
		head = up;
	}
	return join(realpathSync(head), ...tail);
}

/**
 * Whether `target` edits the checkout itself: inside `checkout` with no linked worktree (a directory
 * whose `.git` is a file) between them, the checkout's own root included.
 */
export function inCheckout(target: string, checkout: string): boolean {
	const root = realish(checkout);
	const file = realish(target);
	if (file !== root && !file.startsWith(root + sep)) return false;
	for (let dir = file; ; dir = dirname(dir)) {
		const git = join(dir, ".git");
		if (existsSync(git) && statSync(git).isFile()) return false;
		if (dir === root || dirname(dir) === dir) return true;
	}
}

/** The configured checkout, else the main clone of `cwd` when it is an oh-my-pi clone; null when neither. */
export function findCheckout(cfg: unknown, cwd: string, env: Record<string, string | undefined> = process.env): string | null {
	const set = env.OMP_REPO || get(cfg, "paths.checkout", "");
	if (set) return absolute(set, cwd);
	const out = Bun.spawnSync(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"], {
		stderr: "ignore",
	});
	if (out.exitCode !== 0) return null;
	const main = dirname(out.stdout.toString().trim());
	return existsSync(join(main, "packages", "coding-agent")) ? main : null;
}

export function blockReason(checkout: string, cfg: unknown): string {
	const worktrees = get(cfg, "paths.worktrees", `${checkout}-wt`);
	const prefix = get(cfg, "github.branch_prefix", "<your-login>/");
	return [
		`omp-contrib: this edit targets your oh-my-pi checkout (${checkout}); a fix for upstream is made in a worktree, never in the checkout.`,
		"Next: run skill://omp-contrib/scripts/doctor --json, then the duplicate scan (skill://omp-contrib/references/duplicates.md), then",
		`  git -C ${checkout} worktree add ${worktrees}/<topic> -b ${prefix}<topic> origin/main`,
		"and make the edit there, with absolute paths into the worktree (workflow.md step 2).",
	].join("\n");
}

export default function checkoutGuard(pi: ExtensionAPI): void {
	let contribution = false;

	pi.on("before_agent_start", (event) => {
		if (!contribution && event.prompt.includes(COMMAND_MARKER)) contribution = true;
		return undefined;
	});

	pi.on("tool_call", (event, ctx) => {
		try {
			const input = (event.input ?? {}) as Record<string, unknown>;
			if (!contribution) {
				const probe =
					event.toolName === "read"
						? [input.path]
						: event.toolName === "bash"
							? [input.command, input.cwd]
							: [];
				if (probe.some((p) => typeof p === "string" && touchesSkill(p))) contribution = true;
				return undefined;
			}
			if (!WRITE_TOOLS[event.toolName]) return undefined;
			const paths = targetPaths(event.toolName, input);
			if (paths.length === 0) return undefined;
			const cfg = loadConfig();
			const checkout = findCheckout(cfg, ctx.cwd);
			if (!checkout) return undefined;
			const hit = paths.find((p) => inCheckout(absolute(p, ctx.cwd), checkout));
			if (!hit) return undefined;
			pi.logger.debug("checkout-guard: blocked an edit in the checkout", { tool: event.toolName, path: hit });
			return { block: true, reason: blockReason(checkout, cfg) };
		} catch (error) {
			pi.logger.warn("checkout-guard: check failed, allowing the call", { error: String(error) });
			return undefined;
		}
	});
}
