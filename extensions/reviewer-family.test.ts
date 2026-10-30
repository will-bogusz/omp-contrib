import { describe, expect, test } from "bun:test";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { Model } from "@oh-my-pi/pi-ai";
import type { ExtensionModelQuery } from "@oh-my-pi/pi-coding-agent";
import { chooseReviewer, readConfiguredReviewer, recordRoute } from "./reviewer-family";

function model(
	provider: string,
	id: string,
	cls: string,
	output: number,
	extra: Partial<Model> = {},
): Model {
	return {
		provider,
		id,
		identity: { class: cls },
		reasoning: true,
		cost: { input: output / 5, output, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 200_000,
		...extra,
	} as Model;
}

const opus = model("anthropic", "claude-opus-5", "claude", 25);
const haiku = model("anthropic", "claude-haiku-4-5", "claude", 5);
const gpt = model("openai-codex", "gpt-6", "gpt", 15);
const gptMini = model("openai-codex", "gpt-6-mini", "gpt", 2);
const gptPro = model("openai-codex", "gpt-6-pro", "gpt", 120, {
	reasoningMode: "pro",
});
const gemini = model("google", "gemini-3-pro", "gemini", 12);

function query(
	current: Model,
	list: Model[],
	roles: Record<string, Model> = {},
): ExtensionModelQuery {
	return {
		list: () => list,
		current: () => current,
		resolve: (spec) =>
			roles[spec] ??
			list.find((m) => spec === `${m.provider}/${m.id}` || spec === m.id),
		family: (m) => m.identity.class,
	};
}

describe("chooseReviewer", () => {
	test("ignores other agents", () => {
		expect(
			chooseReviewer(
				{ agent: "task", patterns: [] },
				query(opus, [opus, gpt]),
				undefined,
			),
		).toBeUndefined();
	});

	test("models.reviewer wins when it resolves", () => {
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: [] },
			query(opus, [opus, gpt, gemini]),
			"google/gemini-3-pro",
		);
		expect(result?.model).toBe("google/gemini-3-pro");
	});

	test("unresolvable models.reviewer falls through and says so", () => {
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: [] },
			query(opus, [opus, gpt]),
			"nope/missing",
		);
		expect(result?.model).toEqual(["openai-codex/gpt-6"]);
		expect(result?.note).toContain("did not resolve");
	});

	test("keeps an agent pattern that is already another family", () => {
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: ["google/gemini-3-pro"] },
			query(opus, [opus, gpt, gemini]),
			undefined,
		);
		expect(result?.model).toEqual([
			"google/gemini-3-pro",
			"openai-codex/gpt-6",
		]);
	});

	test("prefers a configured role of another family over the catalog ranking", () => {
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: ["anthropic/claude-opus-5"] },
			query(opus, [opus, gpt, gemini], { "@plan": gemini }),
			undefined,
		);
		expect(result?.model).toEqual([
			"google/gemini-3-pro",
			"openai-codex/gpt-6",
		]);
		expect(result?.note).toContain("@plan");
	});

	test("ranks the catalog: non-pro, reasoning, highest price", () => {
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: ["anthropic/claude-opus-5"] },
			query(opus, [opus, haiku, gptMini, gptPro, gpt]),
			undefined,
		);
		expect(result?.model).toEqual([
			"openai-codex/gpt-6",
			"openai-codex/gpt-6-mini",
			"openai-codex/gpt-6-pro",
		]);
		expect(result?.note).toContain("cross-family reviewer: openai-codex/gpt-6");
	});

	test("ranks providers the user already runs before pricier ones only listed", () => {
		// A Sol session whose @smol runs on Anthropic: the OpenRouter SKU costs more but was
		// retired, and the Cursor login's plan refused its fallbacks.
		const routed = model("openrouter", "anthropic/claude-opus-4.7-fast", "claude", 150);
		const cursor = model("cursor", "claude-opus-4-7-fast", "claude", 150);
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: ["openai-codex/gpt-6"] },
			query(gpt, [gpt, routed, cursor, opus, haiku], { "@smol": haiku }),
			undefined,
		);
		expect(result?.model).toEqual([
			"anthropic/claude-opus-5",
			"anthropic/claude-haiku-4-5",
			"openrouter/anthropic/claude-opus-4.7-fast",
		]);
	});

	test("skips non-chat and tool-less models", () => {
		const image = model("openai", "gpt-image-2", "gpt", 40, { kind: "image" });
		const noTools = model("openai", "gpt-6-notools", "gpt", 30, {
			supportsTools: false,
		});
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: [] },
			query(opus, [opus, image, noTools, gpt]),
			undefined,
		);
		expect(result?.model).toEqual(["openai-codex/gpt-6"]);
	});

	test("same family only: keeps the spawn's models with a note", () => {
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: ["anthropic/claude-opus-5"] },
			query(haiku, [opus, haiku]),
			undefined,
		);
		expect(result?.model).toEqual(["anthropic/claude-opus-5"]);
		expect(result?.note).toContain("same-family review");
		expect(result?.note).toContain("Testing section");
	});

	test("same family with empty patterns pins the session model", () => {
		const result = chooseReviewer(
			{ agent: "reviewer", patterns: [] },
			query(haiku, [haiku]),
			undefined,
		);
		expect(result?.model).toEqual(["anthropic/claude-haiku-4-5"]);
	});
});

describe("config", () => {
	test("reads models.reviewer from $OMP_CONTRIB_CONFIG; empty or missing is undefined", async () => {
		const dir = await fs.mkdtemp(path.join(os.tmpdir(), "reviewer-family-"));
		try {
			const env = { OMP_CONTRIB_CONFIG: path.join(dir, "config.toml") };
			expect(readConfiguredReviewer(env)).toBeUndefined();
			await Bun.write(env.OMP_CONTRIB_CONFIG, '[models]\nreviewer = ""\n');
			expect(readConfiguredReviewer(env)).toBeUndefined();
			await Bun.write(
				env.OMP_CONTRIB_CONFIG,
				'[models]\nreviewer = "openai-codex/gpt-6"\n',
			);
			expect(readConfiguredReviewer(env)).toBe("openai-codex/gpt-6");
			await Bun.write(env.OMP_CONTRIB_CONFIG, "[models\n");
			expect(() => readConfiguredReviewer(env)).toThrow();
		} finally {
			await fs.rm(dir, { recursive: true, force: true });
		}
	});
});

describe("recordRoute", () => {
	test("appends one JSON line per routing decision", async () => {
		const dir = await fs.mkdtemp(path.join(os.tmpdir(), "reviewer-family-"));
		try {
			const at = new Date("2026-10-30T22:00:00Z");
			recordRoute({ model: ["openai-codex/gpt-6"], note: "cross-family reviewer: openai-codex/gpt-6" },
				"anthropic/claude-sonnet-4-6", path.join(dir, "cache"), at);
			recordRoute({ model: ["anthropic/claude-haiku-4-5"], note: "same-family review" },
				"anthropic/claude-sonnet-4-6", path.join(dir, "cache"), at);
			const lines = (await Bun.file(path.join(dir, "cache", "reviewer-routes.jsonl")).text())
				.trim().split("\n").map((line) => JSON.parse(line));
			expect(lines).toEqual([
				{ at: at.toISOString(), session: "anthropic/claude-sonnet-4-6", model: ["openai-codex/gpt-6"],
					note: "cross-family reviewer: openai-codex/gpt-6" },
				{ at: at.toISOString(), session: "anthropic/claude-sonnet-4-6", model: ["anthropic/claude-haiku-4-5"],
					note: "same-family review" },
			]);
		} finally {
			await fs.rm(dir, { recursive: true, force: true });
		}
	});
});
