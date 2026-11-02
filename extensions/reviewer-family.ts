/**
 * reviewer-family: give the bundled `reviewer` agent a model from a different
 * family than the session's, so a PR is never reviewed only by the lineage that
 * wrote it.
 *
 * The reviewer's models live in omp's own config: `task.agentModelOverrides.reviewer`
 * (comma-separated selectors and `@role` aliases, e.g. "openai-codex/gpt-6.1-sol:high,
 * anthropic/claude-opus-5-5:high"), else the agent's `@slow`. omp expands either into the
 * event's `patterns`, thinking suffixes kept; on its own it would take the first available.
 *
 * On `before_subagent_spawn` for `reviewer`, in order:
 *   1. The first spawn pattern of another family than the session's, as written (its
 *      thinking suffix kept). With the override above, a Claude session gets the OpenAI
 *      entry and a GPT session the Anthropic one.
 *   2. When no pattern is of another family (no override, and `@slow` is the session's
 *      own family): the candidates below, Anthropic/OpenAI cross first (`labRank`): a
 *      Claude session gets an OpenAI model, a GPT session an Anthropic one, any other
 *      session either; other labs only after them. Within a rank, in source order:
 *      a. the user's configured roles (`@slow`, `@plan`, `@advisor`, `@default`);
 *      b. every model in `ctx.models.list()`, served by a provider the user already
 *         runs a model on (the session's, or one a configured role resolves to) before
 *         any other: `list()` holds every model a login can name, including ones that
 *         login's plan cannot serve or an aggregator has retired; then the lab's own
 *         provider before a reseller, `pro` serving variants last, the strongest tier
 *         (`TIERS`), then `strength`.
 * When no other family is available the spawn keeps its patterns and carries a
 * same-family note; the PR's Testing section must say so. The hook never blocks.
 */
import type { Model } from "@oh-my-pi/pi-ai";
import type {
	BeforeSubagentSpawnEvent,
	BeforeSubagentSpawnEventResult,
	ExtensionAPI,
	ExtensionModelQuery,
} from "@oh-my-pi/pi-coding-agent";
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
// The plugin's cache location (path rules: skills/omp-contrib/references/config.md).
import { cacheDir } from "../skills/omp-contrib/charts/lib/config.mjs";

const REVIEWER_AGENT = "reviewer";

/** Roles tried after the spawn's own patterns, strongest-intent first. */
const PREFERRED_ROLES = ["@slow", "@plan", "@advisor", "@default"] as const;

/**
 * Roles whose providers count as proven: a model the user configured there has served
 * requests on that login. A provider the user isn't actually using can list models it can't
 * serve, so a model only listed there must not outrank one a working login already serves.
 */
const PROVEN_ROLES = [...PREFERRED_ROLES, "@smol", "@task", "@commit", "@tiny"] as const;

/** Other-family models appended after the pick as the child's retry fallback chain. */
const FALLBACK_DEPTH = 2;

/**
 * The labs paired first: their frontier models are the strongest code reviewers on consumer
 * subscriptions, and the flow was measured end to end on Opus and Sol. Other labs are the fallback.
 */
const PRIORITY_LABS = ["anthropic", "openai"] as const;

/** Each priority lab's own providers; anything else serving its models is a reseller. */
const OWN_PROVIDERS: Record<string, readonly string[]> = {
	anthropic: ["anthropic"],
	openai: ["openai", "openai-codex"],
};

/**
 * Tier tokens in a model id, strongest first, for the labs whose tiers rank by name rather
 * than price (a lab's unreleased or premium-priced lines must not outrank the reviewed
 * flagship). Ids with none of them rank between the two groups. Same table as doctor's `TIERS`.
 */
const TIERS: Record<string, readonly [readonly string[], readonly string[]]> = {
	anthropic: [["opus", "sonnet"], ["haiku"]],
	openai: [["sol", "terra"], ["luna", "mini", "nano"]],
};

function selector(model: Model): string {
	return `${model.provider}/${model.id}`;
}

/**
 * The model's lab. `identity.class` is the catalog's vendor lineage, classified centrally from
 * provider and id, so a reseller's copy (`openrouter/anthropic/claude-opus-4.7`,
 * `cursor/claude-opus-4-7-fast`) carries the lab's class while `provider` names only the
 * reseller. `ctx.models.family()` stays the same-family test: docs/extensions.md defines it
 * as an opaque token to compare, never to read.
 */
function lab(model: Model): string {
	return model.identity?.class ?? "unknown";
}

/** 0: the Anthropic/OpenAI cross for this session's lab; 1: any other lab. */
function labRank(model: Model, sessionLab: string): number {
	const l = lab(model);
	return (PRIORITY_LABS as readonly string[]).includes(l) && l !== sessionLab ? 0 : 1;
}

/** Rank of the id's tier token within its lab (`TIERS`); 0 for labs without a table. */
function tier(model: Model): number {
	const table = TIERS[lab(model)];
	if (!table) return 0;
	const [strong, cheap] = table;
	const tokens = new Set(model.id.split("/").pop()!.toLowerCase().split(/[-._]/));
	const s = strong.findIndex((t) => tokens.has(t));
	if (s >= 0) return s;
	const c = cheap.findIndex((t) => tokens.has(t));
	return c >= 0 ? strong.length + 1 + c : strong.length;
}

/** Numeric `major.minor.patch` comparison; missing parts count as 0. */
function compareRevision(a: string | undefined, b: string | undefined): number {
	const pa = (a ?? "").split(".").map(Number);
	const pb = (b ?? "").split(".").map(Number);
	for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
		const diff = (pa[i] || 0) - (pb[i] || 0);
		if (diff !== 0) return diff;
	}
	return 0;
}

/**
 * Descending "strongest first" order from what the catalog exposes: reasoning
 * models first; `pro` serving variants last (slow and priced for a different
 * job); then output price as the capability proxy (vendors price their
 * flagships highest); then newer revision; then larger context window.
 */
export function strength(a: Model, b: Model): number {
	const pro =
		Number(a.reasoningMode === "pro") - Number(b.reasoningMode === "pro");
	if (pro !== 0) return pro;
	const reasoning = Number(b.reasoning) - Number(a.reasoning);
	if (reasoning !== 0) return reasoning;
	const price = (b.cost?.output ?? 0) - (a.cost?.output ?? 0);
	if (price !== 0) return price;
	const revision = compareRevision(b.identity?.revision, a.identity?.revision);
	if (revision !== 0) return revision;
	return (b.contextWindow ?? 0) - (a.contextWindow ?? 0);
}

/** Pure routing decision; exported for tests. */
export function chooseReviewer(
	event: Pick<BeforeSubagentSpawnEvent, "agent" | "patterns" | "modelRole">,
	models: ExtensionModelQuery,
): BeforeSubagentSpawnEventResult | undefined {
	if (event.agent !== REVIEWER_AGENT) return undefined;

	const parent = models.current();
	if (!parent) return undefined;
	const parentFamily = models.family(parent);
	const parentLab = lab(parent);
	// A reviewer must be a chat model that can drive the agent's tools.
	const otherFamily = (model: Model | undefined): model is Model =>
		model !== undefined &&
		(model.kind ?? "chat") === "chat" &&
		model.supportsTools !== false &&
		models.family(model) !== parentFamily;

	// Ordered candidates: the spawn's patterns as written, then the ranked fallback picks.
	const picks: Array<{ spec: string; model: Model; source: string }> = [];
	const seen = new Set<string>();
	const add = (spec: string, model: Model, source: string): void => {
		const key = selector(model);
		if (seen.has(key)) return;
		seen.add(key);
		picks.push({ spec, model, source });
	};

	// The override's (or `@slow`'s) order is the user's: no lab re-ranking here, and the
	// pattern string is passed back untouched so its thinking suffix survives.
	const patternSource = event.modelRole ? `@${event.modelRole}` : "task.agentModelOverrides.reviewer";
	for (const pattern of event.patterns) {
		const model = models.resolve(pattern);
		if (otherFamily(model)) add(pattern, model, patternSource);
	}

	const auto: Array<{ spec: string; model: Model; source: string }> = [];
	for (const role of PREFERRED_ROLES) {
		const model = models.resolve(role);
		if (otherFamily(model)) auto.push({ spec: selector(model), model, source: role });
	}
	const proven = new Set<string>([parent.provider]);
	for (const role of PROVEN_ROLES) {
		const model = models.resolve(role);
		if (model) proven.add(model.provider);
	}
	const own = (model: Model): boolean =>
		(OWN_PROVIDERS[lab(model)] ?? []).includes(model.provider);
	const ranked = models
		.list()
		.filter(otherFamily)
		.sort(
			(a, b) =>
				Number(proven.has(b.provider)) - Number(proven.has(a.provider)) ||
				Number(own(b)) - Number(own(a)) ||
				Number(a.reasoningMode === "pro") - Number(b.reasoningMode === "pro") ||
				tier(a) - tier(b) ||
				strength(a, b),
		);
	for (const model of ranked)
		auto.push({ spec: selector(model), model, source: "strongest available" });
	// Stable: the Anthropic/OpenAI cross first, source order kept within each rank.
	auto.sort((a, b) => labRank(a.model, parentLab) - labRank(b.model, parentLab));
	for (const pick of auto) add(pick.spec, pick.model, pick.source);

	const [first, ...rest] = picks;
	if (!first) {
		return {
			model: event.patterns.length > 0 ? event.patterns : [selector(parent)],
			note: `same-family review: no available model outside the session's family (${parentFamily}); say so in the PR's Testing section`,
		};
	}
	return {
		model: [
			first.spec,
			...rest.slice(0, FALLBACK_DEPTH).map((pick) => pick.spec),
		],
		note: `cross-family reviewer: ${first.spec} (${models.family(first.model)}, ${first.source}) vs session ${parentFamily}`,
	};
}

/**
 * Append one routing decision to `<cacheDir>/reviewer-routes.jsonl`. The note shows in the task UI
 * only: a background reviewer's result reaches the session without it or the resolved model, so
 * the session reads this file to tell whether the review was cross-family (workflow.md).
 */
export function recordRoute(
	result: BeforeSubagentSpawnEventResult,
	session: string | undefined,
	dir: string = cacheDir(),
	now: Date = new Date(),
): void {
	mkdirSync(dir, { recursive: true });
	const line = { at: now.toISOString(), session, model: result.model, note: result.note };
	appendFileSync(join(dir, "reviewer-routes.jsonl"), `${JSON.stringify(line)}\n`);
}

export default function reviewerFamily(pi: ExtensionAPI): void {
	pi.on("before_subagent_spawn", (event, ctx) => {
		if (event.agent !== REVIEWER_AGENT) return undefined;
		const result = chooseReviewer(event, ctx.models);
		// The note shows in the task UI only; the routes file is what the session can read back.
		if (result) {
			const current = ctx.models.current();
			try {
				recordRoute(result, current ? selector(current) : undefined);
			} catch (error) {
				pi.logger.warn("reviewer-family: could not record the route", {
					error: String(error),
				});
			}
		}
		return result;
	});
}
