## What

I moved snapcompact's hand-set request limits into the catalog's KDL policy and set the official Anthropic and Codex values from probes, so a long Opus session's archive is no longer held to 17 frames by a 3 MB constant the API never needed.

| Per request | `main` | This PR |
|---|---|---|
| Archive frame payload | 3 MB everywhere (`FRAME_DATA_BYTES_BUDGET`) | half the deployment's `inline-image-byte-budget`: 12 MB on the official Anthropic API and the Codex backend, 3 MB elsewhere |
| Images | TS table `PROVIDER_IMAGE_BUDGETS` (Anthropic 90, Codex 200, unknown 5) | KDL `image-count-budget` with the same values, raised on the official endpoint only: Anthropic 600 (100 on 200k-window Claude lines), Codex 2,000 |

**The one maintainer decision:** these raised defaults on the two official endpoints. Proxies, other hosts, the 80-frame cap, frame pricing and the 60% sizing are unchanged.

## Why

**The 3 MB cap is what makes long sessions forget.** omp budgets an Opus frame at 170 KB, so 3 MB holds 17 frames even when a 600k trigger leaves room for about 43, and each compaction cuts the oldest history past the cap for good. Replaying one real 1,300-turn session through omp's compaction with only the frame cap varied (recall of early-session facts; 0 = no history, 100 = full history):

| Frame cap | Opus 5.5 after 1 / 3 / 5 compactions | gpt-6-astra after 1 / 3 / 5 |
|---|---|---|
| 17 (Opus on `main` today) | 90% / 66% / 18% | 90% / 27% / 21% |
| 40 | 90% / 97% / 97% (6.4 MB at 5) | 94% / 79% / 29% |
| 80 | same as 40 (never needed more than 37) | 94% / 96% / 83% (7.3 MB at 5) |

**Where 3 MB came from.** #3792's sessions failed mid-stream carrying 11.6 MB of frames at 857k tokens of a 1M window, so size and a near-full context were never separated. 70 real Opus frames (12.1 MB), alone and with filler to 865k tokens, produced no 5xx or mid-stream error (n = 1 to 3).

**The new values are measured, not copied from docs.** Each Anthropic limit is a typed rejection at an exact boundary, repeated with no flips, and the docs were wrong twice (the 413 comes from Anthropic, not Cloudflare; the many-image cap is 3000 px, not 2000). Codex showed no typed limit up to 128 MB or 16,000 images; rejected requests billed nothing.

Over 30 days of one heavy user's sessions, 3,476 Anthropic requests carried over 3 MB of images (max 11.3 MB) and 309 Codex requests did (max 17.4 MB), with zero provider failures. 12 MB is a margin under the measured limits, not the limit.

Related, not ours: #15091 (these budgets as settings), #10286, #9064, #7549. **Overlaps #14249, #15130, #15133, #15143, #15144** in `agent-session.ts` and `snapcompact-inline.ts`; merge those first.

Non-goals: the Files API and the 2000 px many-image clamp in `anthropic.ts` (follow-up).

<details><summary>How the limits were probed</summary>

Each probe went through omp's own provider path (Opus 5.5, Haiku 5.5 and Haiku 4.5 on the official Anthropic API; gpt-6-luna and gpt-6-astra on the ChatGPT Codex backend), one attempt per request, caching off, a fresh nonce each time. Size probes used grey PNGs padded with a private ancillary chunk, so the body size is exact to the byte while each image costs a few tokens; Codex billed the same tokens for an image with and without 2 MB of padding, so padded images are still decoded.

| Limit | Probe | Result |
|---|---|---|
| Anthropic request body | ladder to 40 MB, then 25-point bisection to one byte, boundary repeated | 33,554,432 bytes accepted 4/4, one byte more rejected 4/4 with 413 `request_too_large` ("32 MB" is MiB) |
| Anthropic one image | bisection on base64 length | 10,485,760 characters accepted, the next valid length rejected (400) |
| Anthropic image count | 600/601 on Haiku 5.5 and Opus 5.5, 100/101 on Haiku 4.5, 601 split across two turns | 600 and 100 accepted, one more rejected on each; the count spans the whole request |
| Anthropic many-image dimensions | 20 vs 21 images at 1932, 2000, 2001, 3000, 3001 px | with 21+ images each side must be at most 3000 px; one oversized image rejects the request |
| Codex request body | 48, 64, 96, 128 MB, compressed and uncompressed | all accepted (128 MB: 3/3); no size limit found |
| Codex image count | 500 to 16,000 tiny images | 4,000 accepted 3/3; no typed error at any count; from 6,000, 1 of 2 requests failed mid-stream |

In real traffic, an Opus frame bills 0.98 to 1.00 of omp's estimate (68 post-compaction requests), and Codex frames bill exactly the KDL price (31 real requests replayed with and without their frames), so the frame counts below are what the providers charge.

</details>

<details><summary>Decisions and reading order</summary>

- Frames get half of `inline-image-byte-budget` instead of a new axis. That axis already bounds every inline image in the request and the send-time clamp evicts the oldest first, which are the frames; the other half keeps a live screenshot from evicting archive frames and busting the cache.
- The Codex backend at its default URL, or a path under it such as `/codex/responses`, now counts as `compat.officialEndpoint`, derived in the compat resolver from the catalog's `CODEX_BASE_URL`. No Codex wire field reads that flag: request bodies are identical with it on and off.
- Codex 2,000 images is a policy value: half the highest count that passed 3/3, below where mid-stream failures start; it also counts screenshots, and the 12 MB byte budget binds first.
- After a model switch, including retry and role fallbacks, each request drops the oldest archive frames past the new model's budget: official API to OpenRouter or Bedrock sends 3 MB of frames, not 12. Frame pricing is unchanged.
- The raised counts sit on an `official-image-count-budget` axis that applies only while the request reaches the official endpoint, so an Anthropic or Codex proxy keeps 90 / 200. The gate follows the effective request URL, not just the configured `baseUrl`: pi-ai's `reachesOfficialEndpoint` also checks the `ANTHROPIC_BASE_URL` and Foundry `FOUNDRY_BASE_URL` reroutes the Anthropic provider applies at request time, and the image count, frame byte and inline byte budgets all read it. The Codex provider has no request-time URL override, so its configured `baseUrl` decides. The 100-image rule is keyed on Claude revision, including collapsed ids like `claude-opus-45`; tests pin it at the 4.5/4.6 and collapsed-revision boundaries.

Reading order: `packages/catalog/src/compat/request-size.ts` and its gate `reachesOfficialEndpoint` in `packages/ai/src/providers/anthropic-state.ts` → `rules/providers/anthropic.kdl`, `openai-codex.kdl` → `snapcompact.ts` `frameDataBytesBudget` → `session-maintenance.ts` `#computeSnapcompactMaxFrames` → rebuilds in `session-context.ts`, `session-provider-boundary.ts`, `agent-session.ts` (`switchSession`, `navigateTree`), `sdk.ts` → the send-time cap `capArchiveFrameBytes` in `provider-image-budget.ts`.

</details>

## Testing

Offline replay of two real sessions through the automatic-maintenance path (real render, network disabled), `compaction.modelThresholds` `anthropic/*: 600000`, `openai-codex/*: 400000`:

| Session | `main`: planned / rendered | This PR: planned / rendered | Binds on this PR |
|---|---|---|---|
| Opus 5.5, 1M window, 730k tokens | 17 / 15 frames (9 in the denser 241-column grid), 2.44 MB | 43 / 18 frames (all 175-column), 3.06 MB | room under the trigger |
| Codex gpt-6.1-sol, 500k window, 403k tokens | 26 / 20 frames, 1.62 MB | 30 / 20 frames, 1.62 MB | room under the trigger |

A first compaction still fits: `main`'s cap already pushes 9 Opus frames into the denser, less legible grid; here all 18 stay legible. The recall gain starts once history outgrows 17 frames. Two runs byte-identical.

A 4.8 MB three-frame archive keeps 3 frames on the official endpoint and 1 through a proxy after compaction, resume, `switchSession`, tree navigation and a model switch. Negative controls, each failing with its fix reverted: 3 MB budget (9 tests), endpoint gate (13), env reroutes (4), session rebuilds (3), send-time cap (2). 199 pass; `bun run check:ts` passes.

```
bun test packages/catalog/test/request-size.test.ts packages/snapcompact/test/snapcompact.test.ts packages/coding-agent/test/session/provider-image-budget.test.ts packages/coding-agent/test/agent-session-model-persistence.test.ts packages/coding-agent/test/agent-session-snapcompact-budget.test.ts packages/coding-agent/test/agent-session-snapcompact-trigger-room.test.ts
```

Not run: Bedrock, Vertex, OpenRouter and other hosts (not measured; values kept). Recall replays are one session per model, n = 1 to 3 per cell, repeat spread up to about 13 points.

---

- [x] `bun check` passes
- [x] Tested locally
- [x] CHANGELOG updated with the required attribution (if user-facing; internal issue fixes use issue links, external contributions add the PR link and contributor credit after creation)


