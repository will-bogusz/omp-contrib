import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { COMMAND_MARKER } from "./checkout-guard";
import {
	flowNudge,
	type Next,
	ownWordsArg,
	PER_SESSION,
	PER_STEP,
	readNext,
	reviewerRefusal,
	runsStart,
	subjectOf,
} from "./flow-nudge";

let dir: string;
const saved = { cache: process.env.XDG_CACHE_HOME, config: process.env.OMP_CONTRIB_CONFIG };

beforeAll(async () => {
	dir = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "flow-nudge-")));
	process.env.XDG_CACHE_HOME = path.join(dir, "cache");
	process.env.OMP_CONTRIB_CONFIG = path.join(dir, "config.toml");
	await Bun.write(
		process.env.OMP_CONTRIB_CONFIG,
		`[github]\nfork_owner = "me"\nbranch_prefix = "me/"\n\n[paths]\ncheckout = "${path.join(dir, "clone")}"\n`,
	);
});

afterAll(async () => {
	for (const [key, value] of [
		["XDG_CACHE_HOME", saved.cache],
		["OMP_CONTRIB_CONFIG", saved.config],
	] as const) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
	await fs.rm(dir, { recursive: true, force: true });
});

type Result = { continue?: boolean; additionalContext?: string; block?: boolean; reason?: string } | undefined;
type Handler = (event: object, ctx: object) => Result;

const agentStep: Next = { step: "review", actor: "agent", why: "one reviewer", command: "task reviewer", id: "x" };

/** The extension wired to a fake ExtensionAPI and a fake `contrib next`. */
function session(next: () => Next | null) {
	const handlers: Record<string, Handler> = {};
	const api = {
		on: (name: string, h: Handler) => {
			handlers[name] = h;
		},
		logger: { info: () => {}, warn: () => {}, debug: () => {} },
	} as unknown as ExtensionAPI;
	flowNudge(api, () => next());
	return {
		prompt: (prompt: string) => handlers.before_agent_start({ type: "before_agent_start", prompt }, {}),
		bash: (command: string) => handlers.tool_call({ type: "tool_call", toolName: "bash", input: { command } }, {}),
		read: (p: string) => handlers.tool_call({ type: "tool_call", toolName: "read", input: { path: p } }, {}),
		stop: (kind: "main" | "sub" = "main") =>
			handlers.session_stop({ type: "session_stop", session_id: "s1" }, { cwd: dir, agent: { kind } }),
		task: (input: object) => handlers.tool_call({ type: "tool_call", toolName: "task", input }, {}),
	};
}

const contribute = (args: string) => `${COMMAND_MARKER}. The user's arguments:\n\n<arguments>\n${args}\n</arguments>\n`;

describe("helpers", () => {
	test("subjectOf: a /contribute subject, not setup or nothing", () => {
		expect(subjectOf(contribute("the edit tool drops tabs"))).toBe("the edit tool drops tabs");
		expect(subjectOf(contribute(""))).toBeNull();
		expect(subjectOf(contribute("setup"))).toBeNull();
	});

	test("runsStart: the script by any path, with global flags", () => {
		expect(runsStart('skill://omp-contrib/scripts/contrib start "x"')).toBe(true);
		expect(runsStart("/a/b/contrib --cwd /w start x")).toBe(true);
		expect(runsStart("contrib next --json")).toBe(false);
		expect(runsStart("echo contributor started")).toBe(false);
	});
});

describe("nudge", () => {
	test("nothing outside contribution mode", () => {
		const s = session(() => agentStep);
		s.prompt("fix my css");
		expect(s.stop()).toBeUndefined();
	});

	test("an agent step continues the session with its command; capped per step", () => {
		const s = session(() => agentStep);
		s.read("skill://omp-contrib");
		const first = s.stop();
		expect(first?.continue).toBe(true);
		expect(first?.additionalContext).toContain("Next step: review: one reviewer.");
		expect(first?.additionalContext).toContain("Command: task reviewer");
		expect(first?.additionalContext).toContain("stop <duplicate|not-a-bug|not-omp|user-declined|other>");
		for (let i = 1; i < PER_STEP; i++) expect(s.stop()?.continue).toBe(true);
		expect(s.stop()).toBeUndefined();
	});

	test("capped per session across steps", () => {
		let n = 0;
		const s = session(() => ({ ...agentStep, step: `s${n++}` }));
		s.read("skill://omp-contrib");
		const results = Array.from({ length: PER_SESSION + 2 }, () => s.stop());
		expect(results.filter((r) => r?.continue).length).toBe(PER_SESSION);
	});

	test("never for the user's, the bots' or a finished step, nor in subagents", () => {
		for (const actor of ["user", "wait", "done", "stopped", "none"] as const) {
			const s = session(() => ({ ...agentStep, actor }));
			s.read("skill://omp-contrib");
			expect(s.stop()).toBeUndefined();
		}
		const s = session(() => agentStep);
		s.read("skill://omp-contrib");
		expect(s.stop("sub")).toBeUndefined();
	});

	test("a /contribute fix with no contrib start is pushed to start it, then follows next", () => {
		const s = session(() => ({ step: "none", actor: "none", why: "nothing in progress" }));
		s.prompt(contribute("binary output turns the job widget into mojibake"));
		const r = s.stop();
		expect(r?.additionalContext).toContain("Next step: start:");
		expect(r?.additionalContext).toContain('start "binary output turns the job widget into mojibake"');
		s.bash('contrib start "binary output"');
		expect(s.stop()).toBeUndefined();
	});

	test("fails open when contrib next fails", () => {
		const s = session(() => {
			throw new Error("python missing");
		});
		s.read("skill://omp-contrib");
		expect(s.stop()).toBeUndefined();
	});

	test("the nudge offers pause; a user asking to stop is not nudged back", () => {
		const s = session(() => agentStep);
		s.prompt(contribute("the job widget shows mojibake"));
		expect(s.stop()?.additionalContext).toContain('pause "<their reason>"');
		s.prompt("stop for now, I'll look at it later");
		expect(s.stop()).toBeUndefined();
		s.prompt("ok, carry on with the review");
		expect(s.stop()?.continue).toBe(true);
	});
});

describe("contrib next", () => {
	test("the real script answers in the shape the extension reads", async () => {
		const repo = path.join(dir, "clone");
		await fs.mkdir(repo, { recursive: true });
		expect(Bun.spawnSync(["git", "init", "-q", repo]).exitCode).toBe(0);
		const next = readNext(repo);
		expect(next?.actor).toBe("none");
		expect(next?.step).toBe("none");
	});
});

describe("own words", () => {
	const said = "binary output turning into garbage in the job widget makes long-running pipes unreadable";

	test("ownWordsArg: the literal sentence a command records, else null", () => {
		expect(ownWordsArg(`skill://omp-contrib/scripts/contrib record own-words "${said}" && contrib next`)).toBe(said);
		expect(ownWordsArg(`python3 /x/contrib --id t record own-words 'it is "fine"'`)).toBe('it is "fine"');
		expect(ownWordsArg(`contrib record own-words "a \\"quoted\\" word"`)).toBe('a "quoted" word');
		expect(ownWordsArg(`contrib record own-words "$(cat s.txt)"`)).toBeNull();
		expect(ownWordsArg("contrib record dup-scan --verdict none")).toBeNull();
	});

	test("a sentence in none of the user's messages is refused; theirs passes, whitespace aside", () => {
		const s = session(() => null);
		s.prompt(contribute(`the job widget shows mojibake. In my words: ${said}.`));
		const mine = s.bash(`contrib record own-words "The job widget mangles binary output, so I fixed it."`);
		expect(mine?.block).toBe(true);
		expect(mine?.reason).toContain("never generate a substitute");
		const recapitalized = s.bash(`contrib record own-words "${said[0].toUpperCase()}${said.slice(1)}"`);
		expect(recapitalized?.block).toBe(true);
		expect(s.bash(`contrib record own-words "${said.replace("job widget", "job\n  widget")}"`)).toBeUndefined();
	});

	test("the /contribute command's own text is not the user's", () => {
		const s = session(() => null);
		const commandText = "turns something oh-my-pi (omp) did wrong into a reviewed, bot-clean PR";
		s.prompt(`${COMMAND_MARKER}: it ${commandText}.\n\n<arguments>\nthe job widget shows mojibake\n</arguments>\n`);
		expect(s.bash(`contrib record own-words "${commandText}"`)?.block).toBe(true);
	});

	test("the user's report of the problem is not an answer; a later message is", () => {
		const report = "omp keeps showing garbage characters in the background job widget";
		const answer = "Binary pipes should show a byte count, because garbage hides real progress.";
		const s = session(() => null);
		s.prompt(`${report}. can you fix it upstream?`);
		expect(s.bash(`contrib record own-words "${report}."`)?.block).toBe(true);
		s.prompt(answer);
		expect(s.bash(`contrib record own-words "${answer}"`)).toBeUndefined();
	});
});

describe("reviewer", () => {
	const brief = "Brief: /skill/references/review-brief.md, read it in full.";
	const pasted = "# Reviewer brief: the independent review\n\nWorkflow step 3 spawns omp's bundled `reviewer` agent with this file as its brief.";

	test("a task carrying the review brief runs as the reviewer agent", () => {
		expect(reviewerRefusal({ tasks: [{ task: brief }] })).toContain('agent: "reviewer"');
		expect(reviewerRefusal({ context: pasted, tasks: [{ task: "review the branch" }] })).toContain("reviewer agent");
		expect(reviewerRefusal({ context: brief, tasks: [{ agent: "reviewer", task: "review the branch" }] })).toBeNull();
	});

	test("a worker told to spawn its own reviewer is not the review", () => {
		const task = `Fix the bug in the worktree, then spawn one reviewer with ${brief}`;
		expect(reviewerRefusal({ tasks: [{ task }] })).toBeNull();
		expect(reviewerRefusal({ tasks: [{ task: "fix the widget" }] })).toBeNull();
	});

	test("the session's task call is refused with that reason", () => {
		const s = session(() => null);
		const r = s.task({ tasks: [{ task: brief }] });
		expect(r?.block).toBe(true);
	});
});
