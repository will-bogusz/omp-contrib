/**
 * reviewer-family: give the bundled `reviewer` agent a model from a different
 * family than the session's, so a PR is never reviewed only by the lineage that
 * wrote it.
 *
 * On `before_subagent_spawn` for `reviewer`, in order:
 *   1. `models.reviewer` from the omp-contrib config file, when set and it resolves.
 *   2. The spawn's own patterns (the reviewer's `@slow` role chain) — first one
 *      whose family differs from the session model's.
 *   3. The user's configured roles (`@slow`, `@plan`, `@advisor`, `@default`) —
 *      first one resolving to another family.
 *   4. The strongest other-family model in `ctx.models.list()` (see `strength`), served by a
 *      provider the user already runs a model on (the session's, or one a configured role
 *      resolves to) before any other: `list()` holds every model a login can name, including
 *      ones that login's plan cannot serve or an aggregator has retired.
 * When no other family is available the spawn keeps its models and carries a
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
// The plugin's one config reader (path rules: skills/omp-contrib/references/config.md).
import { cacheDir, get, loadConfig } from "../skills/omp-contrib/charts/lib/config.mjs";

const REVIEWER_AGENT = "reviewer";

/** Roles tried after the spawn's own patterns, strongest-intent first. */
const PREFERRED_ROLES = ["@slow", "@plan", "@advisor", "@default"] as const;

/**
 * Roles whose providers count as proven: a model the user configured there has served
 * requests on that login. A Sol session's reviewer once ranked to an OpenRouter Claude SKU
 * that OpenRouter had retired, with Cursor fallbacks a free plan refused; the Anthropic login
 * serving the session's `@smol` sat lower only because its price was lower.
 */
const PROVEN_ROLES = [...PREFERRED_ROLES, "@smol", "@task", "@commit", "@tiny"] as const;

/** Other-family models appended after the pick as the child's retry fallback chain. */
const FALLBACK_DEPTH = 2;

/** `models.reviewer` from the omp-contrib config; undefined when unset or empty. Throws on a malformed file. */
export function readConfiguredReviewer(
	env: Record<string, string | undefined> = process.env,
): string | undefined {
	const value: unknown = get(loadConfig(env), "models.reviewer", undefined);
	return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function selector(model: Model): string {
	return `${model.provider}/${model.id}`;
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
	event: Pick<BeforeSubagentSpawnEvent, "agent" | "patterns">,
	models: ExtensionModelQuery,
	configured: string | undefined,
): BeforeSubagentSpawnEventResult | undefined {
	if (event.agent !== REVIEWER_AGENT) return undefined;

	let configNote = "";
	if (configured) {
		const model = models.resolve(configured);
		if (model)
			return {
				model: configured,
				note: `reviewer: ${selector(model)} (models.reviewer)`,
			};
		configNote = ` (models.reviewer "${configured}" did not resolve to an available model)`;
	}

	const parent = models.current();
	if (!parent) return undefined;
	const parentFamily = models.family(parent);
	// A reviewer must be a chat model that can drive the agent's tools.
	const otherFamily = (model: Model | undefined): model is Model =>
		model !== undefined &&
		(model.kind ?? "chat") === "chat" &&
		model.supportsTools !== false &&
		models.family(model) !== parentFamily;

	// Ordered candidates: spawn patterns, then roles, then the ranked catalog.
	const picks: Array<{ spec: string; model: Model; source: string }> = [];
	const seen = new Set<string>();
	const add = (spec: string, model: Model, source: string): void => {
		const key = selector(model);
		if (seen.has(key)) return;
		seen.add(key);
		picks.push({ spec, model, source });
	};
	for (const pattern of event.patterns) {
		const model = models.resolve(pattern);
		if (otherFamily(model)) add(pattern, model, "agent model");
	}
	for (const role of PREFERRED_ROLES) {
		const model = models.resolve(role);
		if (otherFamily(model)) add(selector(model), model, role);
	}
	const proven = new Set<string>([parent.provider]);
	for (const role of PROVEN_ROLES) {
		const model = models.resolve(role);
		if (model) proven.add(model.provider);
	}
	const ranked = models
		.list()
		.filter(otherFamily)
		.sort(
			(a, b) =>
				Number(proven.has(b.provider)) - Number(proven.has(a.provider)) ||
				strength(a, b),
		);
	for (const model of ranked) add(selector(model), model, "strongest available");

	const [first, ...rest] = picks;
	if (!first) {
		const keep =
			event.patterns.length > 0 ? event.patterns : [selector(parent)];
		return {
			model: keep,
			note: `same-family review: no available model outside the session's family (${parentFamily})${configNote}; say so in the PR's Testing section`,
		};
	}
	return {
		model: [
			first.spec,
			...rest.slice(0, FALLBACK_DEPTH).map((pick) => pick.spec),
		],
		note: `cross-family reviewer: ${selector(first.model)} (${models.family(first.model)}, ${first.source}) vs session ${parentFamily}${configNote}`,
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
		let configured: string | undefined;
		try {
			configured = readConfiguredReviewer();
		} catch (error) {
			// A malformed config must not block the review; doctor reports the parse error.
			pi.logger.warn("reviewer-family: could not read omp-contrib config", {
				error: String(error),
			});
		}
		const result = chooseReviewer(event, ctx.models, configured);
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
