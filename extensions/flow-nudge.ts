/**
 * flow-nudge: in a contribution session, when the main agent is about to stop, ask `contrib next` for
 * the contribution's next step; when that step is the agent's own, continue the session with it instead
 * of ending (a `session_stop` continuation, which runs in print mode and the TUI alike).
 *
 * Why: Haiku 5.5 fixed a bug correctly in its worktree, then ended without the review, precheck or
 * queueing, once asking "should I run pr-queue add?" (cross-model check, 2026-10-30). The skill's
 * chain was in its context; a stop hook that names the step and its command is not.
 *
 * Contribution mode is the checkout guard's: the expanded `/contribute` prompt, or reading the skill or
 * running its scripts. Nothing happens in subagents or when the step belongs to the user (the own-words
 * sentence, a supervised open, a P2 decision), the bots, or no one. At most PER_STEP nudges for one step
 * and PER_SESSION per session, so a step the agent cannot do ends the session instead of looping; every
 * failure (python, git, parse) fails open with a log line.
 *
 * It also holds `contrib record own-words` to the user's own text: upstream wants one sentence the
 * contributor wrote, never a generated one, and Haiku 5.5 recorded the user's sentence merged with its
 * own restatement of the bug, recapitalized (2026-11-01). A sentence that is not the user's answer
 * (`ownWordsRefusal`) is refused; one the command does not spell out literally (a `$(…)`, a heredoc)
 * is let through. And a `task` that carries the review brief runs as the `reviewer`
 * agent (`reviewerRefusal`).
 */
import { appendFileSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { cacheDir } from "../skills/omp-contrib/charts/lib/config.mjs";
import { COMMAND_MARKER, touchesSkill } from "./checkout-guard";

export const CONTRIB = resolve(import.meta.dir, "..", "skills", "omp-contrib", "scripts", "contrib");
export const PER_STEP = 2;
export const PER_SESSION = 6;
/** A user message asking to stop or pause the work for now ("stop", "pause, I'll look later", "hold off"). */
export const STOP_ASK = /\b(stop|pause|hold (on|off)|leave it|later|not now|that's enough)\b/i;

/** `contrib next --json`. */
export interface Next {
	step: string;
	actor: "agent" | "user" | "wait" | "done" | "stopped" | "none";
	why: string;
	command?: string;
	id?: string;
	branch?: string;
	started?: string;
	pending_user?: string[];
}

export interface State {
	/** The /contribute subject, when the command named one (a fix was asked for). */
	subject: string | null;
	/** Epoch ms of the session's first prompt. */
	since: number;
	/** Whether the agent ran `contrib start` in this session. */
	started: boolean;
	perStep: Map<string, number>;
	total: number;
}

/** The arguments of an expanded `/contribute` prompt when they name something to fix (not empty, not `setup`). */
export function subjectOf(prompt: string): string | null {
	const m = /<arguments>\n?([\s\S]*?)\n?<\/arguments>/.exec(prompt);
	const args = m?.[1]?.trim() ?? "";
	if (!args || /^setup\b/i.test(args)) return null;
	return args;
}

/** Whether a bash command runs `contrib start`. */
export function runsStart(command: string): boolean {
	return /(^|[\s/])contrib(\s+--\S+(\s+(?!start\b)\S+)?)*\s+start\b/.test(command);
}

/** The text a bash command records with `contrib record own-words`, or null: none, or not a literal word. */
export function ownWordsArg(command: string): string | null {
	const m = /(^|[\s/])contrib(\s+--\S+(\s+[^\s-]\S*)?)*\s+record\s+own-words\s+/.exec(command);
	if (!m) return null;
	const rest = command.slice(m.index + m[0].length);
	let word = "";
	let quote: string | null = null;
	for (let i = 0; i < rest.length; i++) {
		const c = rest[i];
		if (quote === "'") {
			if (c === "'") quote = null;
			else word += c;
		} else if (quote === '"') {
			if (c === '"') quote = null;
			else if (c === "\\" && i + 1 < rest.length && '"\\$`'.includes(rest[i + 1])) word += rest[++i];
			else if (c === "$" || c === "`") return null;
			else word += c;
		} else if (c === "'" || c === '"') {
			quote = c;
		} else if (/[\s;&|<>]/.test(c)) {
			break;
		} else if (c === "$" || c === "`") {
			return null;
		} else {
			word += c === "\\" && i + 1 < rest.length ? rest[++i] : c;
		}
	}
	return quote || !word.trim() ? null : word;
}

/**
 * Why recording `sentence` as the user's own words is refused, or null when it is theirs. Their first message
 * reports the problem; a sentence from it counts only after "in my words" or "own words" there, since the
 * report is not an answer to the question (GPT-6.1 Sol recorded a plain bug report, 2026-11-01). Any later
 * message counts whole: it is where the answer to the question arrives.
 */
export function ownWordsRefusal(sentence: string, userTexts: string[]): string | null {
	const want = sentence.replace(/\s+/g, " ").trim();
	if (!want || userTexts.length === 0) return null;
	const holds = userTexts.some((raw, i) => {
		const text = raw.replace(/\s+/g, " ");
		const at = text.indexOf(want);
		if (at < 0) return false;
		return i > 0 || /\b(in my (own )?words|own[- ]words)\b/i.test(text.slice(0, at + 1));
	});
	if (holds) return null;
	return [
		"omp-contrib: the own-words sentence is the user's answer to the own-words question, exactly as they wrote it",
		"(upstream CONTRIBUTING.md; AGENTS.md: never generate a substitute). This text is not that: it is in none of",
		"their messages, or only in their report of the problem. Ask them once: \"In a sentence, in your words: what",
		"should change, and why does it matter to you? It goes first in the PR, verbatim.\" and stop for their answer;",
		"keep working on the steps that do not need it.",
	].join(" ");
}

const REVIEW_BRIEF = /review-brief|Reviewer brief: the independent/;

/**
 * Why a `task` call carrying the review brief is refused, or null: the one independent review runs as omp's
 * bundled `reviewer` agent, which the reviewer-family extension moves to another lab. Haiku 5.5 sent the
 * brief to a plain `task` worker, which ran on Haiku itself (2026-11-01). A task that hands a worker the
 * fix and tells it to spawn the reviewer itself (workflow.md step 3) is not the review: one that says
 * "spawn" passes.
 */
export function reviewerRefusal(input: Record<string, unknown>): string | null {
	const tasks = Array.isArray(input.tasks) ? (input.tasks as Record<string, unknown>[]) : [];
	const context = typeof input.context === "string" ? input.context : "";
	const wrong = tasks.filter((t) => {
		// The brief's own opening ("Workflow step 3 spawns omp's bundled `reviewer` agent with this file as its
		// brief") is no instruction to spawn anything.
		const text = `${context}\n${typeof t.task === "string" ? t.task : ""}`.replace(/spawns omp's bundled[\s\S]*?as its/g, "");
		return t.agent !== "reviewer" && REVIEW_BRIEF.test(text) && !/\bspawn/i.test(text);
	});
	if (wrong.length === 0) return null;
	return (
		'omp-contrib: the independent review runs as omp\'s bundled reviewer agent: set `agent: "reviewer"` on the task ' +
		"that carries review-brief.md (the plugin moves it to a model from another lab), one reviewer, one round."
	);
}

/**
 * The step to push the agent to, or null. A /contribute fix with no `contrib start` this session gets a
 * synthesized start step when `next` has nothing newer than the session.
 */
export function stepFor(state: State, next: Next | null): Next | null {
	const fresh = next?.started ? Date.parse(next.started) >= state.since - 60_000 : false;
	if (state.subject && !state.started && !fresh && (!next || next.actor !== "agent")) {
		return {
			step: "start",
			actor: "agent",
			why: "you were asked to fix this upstream, and no contribution is recorded for it",
			command: `${CONTRIB} start ${JSON.stringify(state.subject.slice(0, 200))}`,
		};
	}
	return next && next.actor === "agent" ? next : null;
}

export function nudgeText(next: Next): string {
	const lines = [
		`omp-contrib: this contribution${next.id ? ` (${next.id})` : ""} is not finished.`,
		`Next step: ${next.step}: ${next.why}.`,
	];
	if (next.command) lines.push(`Command: ${next.command}`);
	const pending = next.pending_user ?? [];
	for (const p of pending) lines.push(`Still needed from the user: ${p}`);
	if (pending.length > 0) {
		lines.push(
			"That answer is needed only when the PR body is written, so it does not block this step: ask it once in your " +
				"final message and keep working until `contrib next` names the user as the one to act. Waiting for it is " +
				"never a reason to stop or pause the contribution.",
		);
	}
	lines.push(
		"Continue with that step now, then run `contrib next` again. If the step does not apply because of what you " +
			`found (a duplicate, not a bug, not omp's code), end the contribution with \`${CONTRIB} stop ` +
			'<duplicate|not-a-bug|not-omp|user-declined|other> --evidence "<what shows it>"`' +
			(next.step === "start" ? " (after `contrib start`, which records what was asked)" : "") +
			`; if the user asked to stop or pause, \`${CONTRIB} pause "<their reason>"\`, which keeps it for later and ` +
			"ends this nudging.",
	);
	return lines.join("\n");
}

/** Counts a nudge for `next` against the caps; null when a cap is reached. */
export function take(state: State, next: Next): string | null {
	const key = `${next.id ?? "-"}:${next.step}`;
	const n = state.perStep.get(key) ?? 0;
	if (n >= PER_STEP || state.total >= PER_SESSION) return null;
	state.perStep.set(key, n + 1);
	state.total++;
	return key;
}

export function readNext(cwd: string): Next | null {
	const out = Bun.spawnSync([CONTRIB, "--cwd", cwd, "next", "--json"], { stderr: "pipe", timeout: 20_000 });
	if (out.exitCode !== 0) throw new Error(`contrib next exited ${out.exitCode}: ${out.stderr.toString().slice(0, 400)}`);
	return JSON.parse(out.stdout.toString()) as Next;
}

function logNudge(session: string | undefined, next: Next, key: string, state: State): void {
	const dir = cacheDir();
	mkdirSync(dir, { recursive: true });
	const line = { at: new Date().toISOString(), session, id: next.id, step: next.step, key, total: state.total };
	appendFileSync(join(dir, "nudges.jsonl"), `${JSON.stringify(line)}\n`);
}

/** The extension with its `contrib next` reader injected (tests pass a fake). */
export function flowNudge(pi: ExtensionAPI, read: (cwd: string) => Next | null): void {
	let contribution = false;
	const state: State = { subject: null, since: 0, started: false, perStep: new Map(), total: 0 };
	// What the user wrote this session: a /contribute prompt's arguments (the rest is the command's own
	// text, the own-words question included), any other prompt whole.
	const userTexts: string[] = [];

	pi.on("before_agent_start", (event) => {
		if (!state.since) state.since = Date.now();
		if (event.prompt.includes(COMMAND_MARKER)) {
			contribution = true;
			state.subject = subjectOf(event.prompt) ?? state.subject;
			userTexts.push(/<arguments>([\s\S]*?)<\/arguments>/.exec(event.prompt)?.[1] ?? "");
		} else {
			userTexts.push(event.prompt);
		}
		return undefined;
	});

	pi.on("tool_call", (event) => {
		const input = (event.input ?? {}) as Record<string, unknown>;
		if (event.toolName === "bash" && typeof input.command === "string") {
			if (runsStart(input.command)) state.started = true;
			const sentence = ownWordsArg(input.command);
			const refusal = sentence === null ? null : ownWordsRefusal(sentence, userTexts);
			if (refusal) {
				pi.logger.info("flow-nudge: refused an own-words sentence not in the user's messages");
				return { block: true, reason: refusal };
			}
		}
		if (event.toolName === "task") {
			const refusal = reviewerRefusal(input);
			if (refusal) {
				pi.logger.info("flow-nudge: refused a review-brief task not spawned as the reviewer agent");
				return { block: true, reason: refusal };
			}
		}
		if (!contribution) {
			const probe = event.toolName === "read" ? [input.path] : event.toolName === "bash" ? [input.command, input.cwd] : [];
			if (probe.some((p) => typeof p === "string" && touchesSkill(p))) contribution = true;
		}
		return undefined;
	});

	pi.on("session_stop", (event, ctx) => {
		if (!contribution || ctx.agent?.kind === "sub") return undefined;
		// The user's latest message (not the one that started the work) asks to stop or pause: their call,
		// never nudged back into work. The nudge text offers `contrib pause` for the next stop.
		const last = userTexts.length > 1 ? userTexts[userTexts.length - 1] : "";
		if (last.length < 400 && STOP_ASK.test(last)) return undefined;
		try {
			const next = stepFor(state, read(ctx.cwd));
			if (!next) return undefined;
			const key = take(state, next);
			if (!key) {
				pi.logger.info("flow-nudge: cap reached, letting the session end", { step: next.step, total: state.total });
				return undefined;
			}
			try {
				logNudge(event.session_id, next, key, state);
			} catch (error) {
				pi.logger.warn("flow-nudge: could not log the nudge", { error: String(error) });
			}
			return { continue: true, additionalContext: nudgeText(next) };
		} catch (error) {
			pi.logger.warn("flow-nudge: contrib next failed, letting the session end", { error: String(error) });
			return undefined;
		}
	});
}

export default function (pi: ExtensionAPI): void {
	flowNudge(pi, readNext);
}
