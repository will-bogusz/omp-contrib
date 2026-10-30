import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import checkoutGuard, { COMMAND_MARKER, findCheckout, inCheckout, targetPaths, touchesSkill } from "./checkout-guard";

let dir: string;
let checkout: string;
let worktree: string;

function git(cwd: string, ...args: string[]): void {
	const r = Bun.spawnSync(["git", "-C", cwd, ...args], { stderr: "pipe" });
	if (r.exitCode !== 0) throw new Error(r.stderr.toString());
}

beforeAll(async () => {
	dir = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "checkout-guard-")));
	checkout = path.join(dir, "oh-my-pi");
	await fs.mkdir(path.join(checkout, "packages", "coding-agent", "src"), { recursive: true });
	await Bun.write(path.join(checkout, "packages", "coding-agent", "src", "a.ts"), "export {};\n");
	git(dir, "init", "-q", "-b", "main", checkout);
	git(checkout, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init");
	worktree = path.join(dir, "oh-my-pi-wt", "fix");
	git(checkout, "worktree", "add", "-q", worktree, "-b", "me/fix");
});

afterAll(async () => {
	await fs.rm(dir, { recursive: true, force: true });
});

type Verdict = { block?: boolean; reason?: string } | undefined;
type Handler = (event: object, ctx: { cwd: string }) => Verdict;

/** The guard wired to a fake ExtensionAPI; config from $OMP_CONTRIB_CONFIG (`config`). */
function session(config: string) {
	const handlers: Record<string, Handler> = {};
	const warnings: string[] = [];
	// The guard uses only `on` and `logger`; the rest of ExtensionAPI is never reached in these tests.
	const api = {
		on: (name: string, h: Handler) => {
			handlers[name] = h;
		},
		logger: { debug: () => {}, warn: (m: string) => warnings.push(m) },
	} as unknown as ExtensionAPI;
	checkoutGuard(api);
	const env = process.env.OMP_CONTRIB_CONFIG;
	const run = (name: string, event: object, cwd = checkout): Verdict => {
		process.env.OMP_CONTRIB_CONFIG = config;
		try {
			return handlers[name]({ type: name, ...event }, { cwd });
		} finally {
			if (env === undefined) delete process.env.OMP_CONTRIB_CONFIG;
			else process.env.OMP_CONTRIB_CONFIG = env;
		}
	};
	return {
		warnings,
		prompt: (prompt: string) => run("before_agent_start", { reason: "prompt", prompt, systemPrompt: [] }),
		call: (toolName: string, input: Record<string, unknown>, cwd?: string) =>
			run("tool_call", { toolName, toolCallId: "t", input }, cwd),
	};
}

async function config(body: string): Promise<string> {
	const file = path.join(dir, `config-${Math.random().toString(36).slice(2)}.toml`);
	await Bun.write(file, body);
	return file;
}

describe("helpers", () => {
	test("touchesSkill: the skill URL, its directory, its scripts", () => {
		expect(touchesSkill("skill://omp-contrib")).toBe(true);
		expect(touchesSkill("skill://omp-contrib/scripts/doctor --json")).toBe(true);
		expect(touchesSkill("cd /x/node_modules/omp-contrib/skills/omp-contrib/ && ./scripts/doctor")).toBe(true);
		expect(touchesSkill("packages/coding-agent/src/skills/loader.ts")).toBe(false);
	});

	test("targetPaths: edit path(s), write path, ast_edit glob prefixes, internal URLs skipped", () => {
		expect(targetPaths("edit", { path: "a.ts", paths: ["a.ts", "b.ts"] })).toEqual(["a.ts", "b.ts"]);
		expect(targetPaths("write", { path: "local://notes.md" })).toEqual([]);
		expect(targetPaths("ast_edit", { paths: ["src/**/*.ts", "*.md"] })).toEqual(["src/", "."]);
	});

	test("inCheckout: the checkout and new files in it, not a linked worktree or outside", () => {
		expect(inCheckout(path.join(checkout, "packages/coding-agent/src/a.ts"), checkout)).toBe(true);
		expect(inCheckout(path.join(checkout, "packages/coding-agent/src/new/b.ts"), checkout)).toBe(true);
		expect(inCheckout(path.join(worktree, "packages/coding-agent/src/a.ts"), checkout)).toBe(false);
		expect(inCheckout(path.join(dir, "elsewhere.ts"), checkout)).toBe(false);
		const nested = path.join(checkout, "wt", "x");
		git(checkout, "worktree", "add", "-q", nested, "-b", "me/nested");
		expect(inCheckout(path.join(nested, "a.ts"), checkout)).toBe(false);
	});

	test("findCheckout: paths.checkout, else the main clone around cwd (from a worktree too)", () => {
		expect(findCheckout({ paths: { checkout: "/some/omp" } }, dir, {})).toBe("/some/omp");
		expect(findCheckout({}, worktree, {})).toBe(checkout);
		expect(findCheckout({}, dir, {})).toBeNull();
	});
});

describe("guard", () => {
	const edit = (file: string) => ({ input: `[${file}#ABCD]\nPUT 1:\n+x`, path: file, paths: [file] });

	test("outside contribution mode nothing is blocked", async () => {
		const s = session(await config(""));
		expect(s.call("edit", edit("packages/coding-agent/src/a.ts"))).toBeUndefined();
		expect(s.call("write", { path: path.join(checkout, "x.ts"), content: "" })).toBeUndefined();
	});

	test("after reading the skill, edits in the checkout are blocked with the next steps", async () => {
		const s = session(await config(`[paths]\nworktrees = "${dir}/wts"\n[github]\nbranch_prefix = "me/"\n`));
		expect(s.call("read", { path: "skill://omp-contrib" })).toBeUndefined();
		const result = s.call("edit", edit("packages/coding-agent/src/a.ts"));
		expect(result?.block).toBe(true);
		expect(result?.reason).toContain(`git -C ${checkout} worktree add ${dir}/wts/<topic> -b me/<topic> origin/main`);
		expect(result?.reason).toContain("scripts/doctor");
		expect(result?.reason).toContain("duplicates.md");
		expect(s.call("ast_edit", { paths: ["packages/**/*.ts"], ops: [] })?.block).toBe(true);
		// Worktree edits, reads, bash and paths outside the checkout go through.
		expect(s.call("edit", edit(path.join(worktree, "packages/coding-agent/src/a.ts")))).toBeUndefined();
		expect(s.call("write", { path: "a.ts", content: "" }, worktree)).toBeUndefined();
		expect(s.call("read", { path: "packages/coding-agent/src/a.ts" })).toBeUndefined();
		expect(s.call("bash", { command: "echo hi > packages/x" })).toBeUndefined();
		expect(s.call("write", { path: path.join(dir, "scratch.md"), content: "" })).toBeUndefined();
	});

	test("the expanded /contribute prompt or a skill script turns contribution mode on", async () => {
		const file = await config("");
		const a = session(file);
		a.prompt(`${COMMAND_MARKER}: it turns something …`);
		expect(a.call("write", { path: "packages/coding-agent/src/a.ts", content: "" })?.block).toBe(true);
		const b = session(file);
		b.call("bash", { command: "skill://omp-contrib/scripts/doctor --json" });
		expect(b.call("write", { path: "packages/coding-agent/src/a.ts", content: "" })?.block).toBe(true);
	});

	test("a malformed config fails open with a warning", async () => {
		const s = session(await config("[paths\n"));
		s.call("read", { path: "skill://omp-contrib" });
		expect(s.call("edit", edit("packages/coding-agent/src/a.ts"))).toBeUndefined();
		expect(s.warnings.join()).toContain("allowing the call");
	});
});
