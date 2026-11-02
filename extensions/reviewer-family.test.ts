import { describe, expect, test } from "bun:test";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { Model } from "@oh-my-pi/pi-ai";
import type { ExtensionModelQuery } from "@oh-my-pi/pi-coding-agent";
import { chooseReviewer, recordRoute } from "./reviewer-family";

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

const opus = model("anthropic", "claude-opus-5-5", "anthropic", 20);
const mythos = model("anthropic", "claude-mythos-5", "anthropic", 50);
const haiku = model("anthropic", "claude-haiku-5-5", "anthropic", 0.5);
const gpt = model("openai-codex", "gpt-6.1-sol", "openai", 10);
const astra = model("openai-codex", "gpt-6-astra", "openai", 50);
const gptLuna = model("openai-codex", "gpt-6-luna", "openai", 0.5);
const gptPro = model("openai-codex", "gpt-6-pro", "openai", 120, {
	reasoningMode: "pro",
});
const gemini = model("google", "gemini-3-pro", "gemini", 60);
const kimi = model("moonshot", "kimi-k3", "kimi", 15);

function query(
	current: Model,
	list: Model[],
	roles: Record<string, Model> = {},
): ExtensionModelQuery {
	return {
		list: () => list,
		current: () => current,
		resolve: (spec) => {
			const base = spec.replace(/:(off|minimal|low|medium|high|xhigh|max)$/, "");
			return roles[base] ?? list.find((m) => base === `${m.provider}/${m.id}` || base === m.id);
		},
		family: (m) => m.identity.class,
	};
}

const reviewer = (patterns: string[] = [], modelRole?: string) => ({ agent: "reviewer", patterns, modelRole });

describe("chooseReviewer", () => {
	test("ignores other agents", () => {
		expect(
			chooseReviewer({ agent: "task", patterns: [] }, query(opus, [opus, gpt])),
		).toBeUndefined();
	});

	test("Claude session: the strongest OpenAI model, ahead of a pricier other lab", () => {
		const result = chooseReviewer(
			reviewer(["anthropic/claude-opus-5-5"]),
			query(opus, [opus, haiku, gemini, gptLuna, astra, gptPro, gpt]),
		);
		expect(result?.model).toEqual([
			"openai-codex/gpt-6.1-sol",
			"openai-codex/gpt-6-astra",
			"openai-codex/gpt-6-luna",
		]);
		expect(result?.note).toContain("cross-family reviewer: openai-codex/gpt-6.1-sol");
	});

	test("GPT session: Opus over a pricier untiered Anthropic line and over other labs", () => {
		const result = chooseReviewer(
			reviewer(["openai-codex/gpt-6.1-sol"]),
			query(gpt, [gpt, gemini, kimi, haiku, mythos, opus]),
		);
		expect(result?.model).toEqual([
			"anthropic/claude-opus-5-5",
			"anthropic/claude-mythos-5",
			"anthropic/claude-haiku-5-5",
		]);
	});

	test("another lab's session: Anthropic or OpenAI before the rest", () => {
		const result = chooseReviewer(reviewer(), query(kimi, [kimi, gemini, gpt, opus]));
		expect(result?.model).toEqual([
			"anthropic/claude-opus-5-5",
			"openai-codex/gpt-6.1-sol",
			"google/gemini-3-pro",
		]);
	});

	test("Anthropic only plus another lab: that lab reviews a Claude session", () => {
		const result = chooseReviewer(
			reviewer(["anthropic/claude-opus-5-5"]),
			query(opus, [opus, haiku, gemini]),
		);
		expect(result?.model).toEqual(["google/gemini-3-pro"]);
	});

	test("a configured role of the preferred lab beats the catalog ranking; another lab's does not", () => {
		const result = chooseReviewer(
			reviewer(["anthropic/claude-opus-5-5"]),
			query(opus, [opus, gpt, gptLuna, gemini], { "@plan": gemini, "@advisor": gptLuna }),
		);
		expect(result?.model).toEqual([
			"openai-codex/gpt-6-luna",
			"openai-codex/gpt-6.1-sol",
			"google/gemini-3-pro",
		]);
		expect(result?.note).toContain("@advisor");
	});

	test("override pair: the first entry of another family, thinking suffix kept", () => {
		const list = [opus, haiku, gpt, gemini];
		const pair = ["openai-codex/gpt-6.1-sol:high", "anthropic/claude-opus-5-5:high"];
		const claude = chooseReviewer(reviewer(pair), query(haiku, list));
		expect(claude?.model?.[0]).toBe("openai-codex/gpt-6.1-sol:high");
		expect(claude?.note).toContain("(openai, task.agentModelOverrides.reviewer)");
		const gptSession = chooseReviewer(reviewer(pair), query(gpt, list));
		expect(gptSession?.model?.[0]).toBe("anthropic/claude-opus-5-5:high");
	});

	test("patterns keep their written order over the lab preference", () => {
		const result = chooseReviewer(
			reviewer(["google/gemini-3-pro", "openai-codex/gpt-6.1-sol"]),
			query(opus, [opus, gpt, gemini]),
		);
		expect(result?.model).toEqual(["google/gemini-3-pro", "openai-codex/gpt-6.1-sol"]);
	});

	test("@slow of another family is kept; unavailable patterns are skipped", () => {
		const result = chooseReviewer(
			reviewer(["nope/missing", "openai-codex/gpt-6.1-sol:medium"], "slow"),
			query(opus, [opus, gpt]),
		);
		expect(result?.model).toEqual(["openai-codex/gpt-6.1-sol:medium"]);
		expect(result?.note).toContain("@slow");
	});

	test("ranks providers the user already runs before pricier ones only listed", () => {
		// A session whose @smol runs on a working login: a provider the user isn't actually
		// using can list models it can't serve, so those rank after the proven login.
		const routed = model("openrouter", "anthropic/claude-opus-4.7-fast", "anthropic", 150);
		const cursor = model("cursor", "claude-opus-4-7-fast", "anthropic", 150);
		const result = chooseReviewer(
			reviewer(["openai-codex/gpt-6.1-sol"]),
			query(gpt, [gpt, routed, cursor, opus, haiku], { "@smol": haiku }),
		);
		expect(result?.model).toEqual([
			"anthropic/claude-opus-5-5",
			"anthropic/claude-haiku-5-5",
			"openrouter/anthropic/claude-opus-4.7-fast",
		]);
	});

	test("skips non-chat and tool-less models", () => {
		const image = model("openai", "gpt-image-2", "openai", 40, { kind: "image" });
		const noTools = model("openai", "gpt-6-notools", "openai", 30, {
			supportsTools: false,
		});
		const result = chooseReviewer(reviewer(), query(opus, [opus, image, noTools, gpt]));
		expect(result?.model).toEqual(["openai-codex/gpt-6.1-sol"]);
	});

	test("same family only: keeps the spawn's models with a note", () => {
		const result = chooseReviewer(
			reviewer(["anthropic/claude-opus-5-5"]),
			query(haiku, [opus, haiku]),
		);
		expect(result?.model).toEqual(["anthropic/claude-opus-5-5"]);
		expect(result?.note).toContain("same-family review");
		expect(result?.note).toContain("Testing section");
	});

	test("same family with empty patterns pins the session model", () => {
		const result = chooseReviewer(reviewer(), query(haiku, [haiku]));
		expect(result?.model).toEqual(["anthropic/claude-haiku-5-5"]);
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
