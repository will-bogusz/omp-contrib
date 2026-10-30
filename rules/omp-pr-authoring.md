---
description: Pull request description conventions — read before writing or editing any PR body
---
# Pull request descriptions

A description exists to transfer what the diff cannot carry: intent, the claim, the evidence, and the risk. Litmus test for every sentence: could the reader have gotten this from the diff in the same time? If yes, cut it. Never restate the diff; mechanical inventories go stale within the PR's own review cycle and start to lie.

Answer four questions, in this order, at length proportional to the stakes:

1. Why does this exist? The problem, its impact, why this shape and not the alternatives. If the effect is measurable, the headline number goes in the first sentence.
2. What is the shape of the change? A conceptual map for navigating the diff, not an inventory: the heart first, then consequences, then wiring. Name invariants deliberately preserved and explicit non-goals. Group by concept, never file-by-file.
3. How do we know it works? Retrospective evidence ("replayed over 400 PRs, zero mismatches"), never prospective test plans. State how you know, not where evidence lives: no local file paths or artifact dumps. Link at most a couple of runs or PRs.
4. Where is the risk? What to review first, semantic deltas, open questions, rollback.

Render questions 1-2 as `## Why` and `## What` (repo convention). Questions 3-4 become short optional sections (`Verification`, `Open questions`, `Rollback`) only when they have real content; empty-ritual sections train readers to skip descriptions. A one-line fix needs one sentence under each of Why and What.

Length budget, enforced not vibes:

- Whole body: aim under 2,000 characters; 3,000 is the hard ceiling for even the largest change (tables, diagrams, and `<details>` content excluded from the count). Past that, cut claims, not words: each claim gets one sentence and one number, and everything else moves to `<details>` or dies.
- Paragraphs: 3 sentences max. A paragraph arguing a proof, a provenance story, and a failure mode is three paragraphs, and probably one of them is a `<details>`.
- One number per claim, best form only. A p50 does not need its raw pair; a "was 146s" does not need the sub-step breakdown in the body.
- Never grow a body by patching sentences into it across revisions; accretion is how dense walls form. Re-derive the body from the four questions each time it changes materially.

Density tools, used deliberately:

- A small `| | before | after |` table when there is a measurable claim.
- Mermaid (flowchart, pie) when structure or composition is the point; a table when a comparison is the point; never both for the same fact.
- A feature PR with several user-visible capabilities leads its What with a compact `| Capability | Behavior |` table, one short line per row, only claims true of the pushed code; this is the scannable map maintainers use, so do not flatten it into paragraphs.
- Exhaustive reviewer-grade tables (per-file decisions, full inventories) go in `<details>` blocks, not the body.

Plain conversational prose, senior engineer orienting a capable colleague unfamiliar with the code; no emojis, no em-dashes. Do not invent motivation, tests, or impact the PR context does not support.

Register scales with the surface, because each has a different reader:

| Surface | Reader | Register |
|---|---|---|
| Title + first sentence | someone skimming a list of 30 | what the user or caller observed wrong; no symbols, no mechanism |
| Body | a maintainer triaging | consequence first, then the shape; mechanism only where it changes the review |
| `<details>` | the reviewer going deep | mechanism, per-file decisions, measurement tables |
| Review reply | the reviewer who wrote a numbered list | their numbering; per item, the resolved state in one sentence plus sha and evidence; never re-argue the diagnosis; one "ready for another look" per round |
| Issue | someone deciding whether it is real | repro, expected, observed, verbatim output; no proposal |

Test for the first sentence: would a maintainer who has never read our transcripts know what broke for whom? `map_action ended in _ => "AXPress"` fails; `an unknown action name pressed the element and reported a press` passes. On an external repo, its PR template's headings win over `## Why` / `## What`; the four questions still fill them in that order.

Two rules that outlive the review:

- Anchor code references by path + symbol, never line number — line numbers die in one commit; symbols survive refactors and are greppable.
- Make verification executable: give the command or query that re-proves the claim, not just the observation, so a later reader can re-run it instead of trusting it.

Write for two readers: the reviewer today, and the agent doing archaeology on this PR months later with only the body and the diff.
