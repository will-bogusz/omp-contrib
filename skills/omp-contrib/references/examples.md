# Curated examples (can1357/oh-my-pi)

Examples of what worked and what did not. Read them for the move each one makes, not as templates.
Outcomes are as of 2026-09-28.

## One contributor's PRs, made with this flow

| PR | Outcome | Lesson |
|---|---|---|
| [#7865](https://github.com/can1357/oh-my-pi/pull/7865) fix(catalog): Devin reasoning family routing | merged in 11 h, P0 | Narrow root-cause fix in two revertible commits; nit fixed with a one-line reply in 3 min. |
| [#8337](https://github.com/can1357/oh-my-pi/pull/8337) fix(usage): authoritative OpenCode Go quotas | merged in 15 h, P1 | The best body of the set: the first sentence says what users saw wrong, a before/after screenshot table follows, and every blocking finding was answered within 8 min with sha, mechanism and test name. |
| [#7195](https://github.com/can1357/oh-my-pi/pull/7195) omit unsupported Anthropic search temperature | merged in 24 h, P0 | Tiny scope, rank P0. |
| [#8590](https://github.com/can1357/oh-my-pi/pull/8590) adopt Devin's native CLI surface | merged in 15 d | Capability before -> now table and screenshots. Merged only after the default flip roboomp called a "maintainer call" was reverted. The base for the framing distillation. |
| [#11613](https://github.com/can1357/oh-my-pi/pull/11613) Cursor account catalog, prices, native requests | merged 09-30 by H4vC, P2, 1 d after going ready | The visuals that worked: five labeled before/after composites (model browser, `omp models`, Auto pricing, live tool turn, `/usage`), one per provable table row. Also the scope lesson in numbers: roboomp capped it at P2 for bundling a default-model change and transport fixes with discovery; the four fixes split out as #13723-#13726 were ranked P0, P0, P0, P1 within minutes of going ready. Before merging, the maintainer cut more scope in their own commits: removed the runtime pricing-page scrape (KDL rate card only), dropped a change that duplicated an open split PR, fixed an HTTP/1 settle bug. Expect runtime scraping of a vendor site to be cut. |
| [#10233](https://github.com/can1357/oh-my-pi/pull/10233) normalize Gemini tool schemas | merged in 16 d | Deterministic repro, a live before/after 51/51 matrix, explicit non-goals. The delay was Can's merge gap, not the body. |
| [#13527](https://github.com/can1357/oh-my-pi/pull/13527) drop Devin Fusion, default SWE-2, CLI identity | open, P2; slice cherry-picked by Can | Good framing (see framing.md). Bundling a default-model change cost the PR: Can took the identity bump alone in `30f532944f`. |
| [#10234](https://github.com/can1357/oh-my-pi/pull/10234) align Devin completion settings | open since 08-30, P2 | Changes a default for every Devin turn and waits on a maintainer decision. |
| [#8577](https://github.com/can1357/oh-my-pi/pull/8577), [#11650](https://github.com/can1357/oh-my-pi/pull/11650) | drafts, never reviewed | Drafts get no bot review and maintainers rarely act on them. Large features were never discussed first. (#11613 sat in draft the same way until 09-29.) |
| [#11956](https://github.com/can1357/oh-my-pi/pull/11956) -> [#11959](https://github.com/can1357/oh-my-pi/issues/11959), [#11960](https://github.com/can1357/oh-my-pi/issues/11960) | closed, then proposals idle 15 d | Proposal issues get no roboomp PR and no maintainer action unless someone decides. |

## Others' PRs worth studying

| PR | Move to borrow |
|---|---|
| [#13063](https://github.com/can1357/oh-my-pi/pull/13063) collab-web responsiveness | Opens with a real-session symptom, names three measured causes, and gives a `main` vs this-PR table (p50 delay 9.4 s -> 7 ms) with the measurement rig. roboomp P1; merged in 9 h. |
| [#11740](https://github.com/can1357/oh-my-pi/pull/11740) `free` searchable | First-person scenario, a four-row count table, an explicit non-goal, a before/after query table. P0; merged in under 1 h. |
| [#11386](https://github.com/can1357/oh-my-pi/pull/11386) whichFresh | Explains why CI is green but developer machines fail. Testing gives RED/GREEN counts (116/3 -> 119/0) and one honest AI-assistance line. P0; merged in 1 h. |
| [#9995](https://github.com/can1357/oh-my-pi/pull/9995) stats colors | Short What bullets, a plainly human Why ("I was recurrently running in this issue"), `### Before` / `### After` screenshots. P0; merged in 6 h. |
| [#10603](https://github.com/can1357/oh-my-pi/pull/10603) Anthropic head caching | Separates the case that is already fine from the one that regresses; live A/B benchmark. P1; merged in 13 h. |
| [#10262](https://github.com/can1357/oh-my-pi/pull/10262) | Beat roboomp's competing #10261 with visibly stronger verification ("21/21 green"). |

## Issues

| Issue | Lesson |
|---|---|
| [#13229](https://github.com/can1357/oh-my-pi/issues/13229) | What happens, cause, a minimal repro with no network or omp code, then a suggested fix. roboomp repro in 3 min, PR #13230 in 14 min, merged 73 min after filing. |
| [#12869](https://github.com/can1357/oh-my-pi/issues/12869) | Observed session evidence plus steps; roboomp PR in 19 min, merged in about 11 h. |
| [#13270](https://github.com/can1357/oh-my-pi/issues/13270) | roboomp ran the issue's repro script unchanged and implemented "suggestion A". A suggestion after the failure is fine. |
| [#11048](https://github.com/can1357/oh-my-pi/issues/11048) | "Proposed fix: #11047" -> roboomp's competing #11051 merged; the contributor's P0 PR was closed. Never file an issue for a fix you already have. |
| [#10626](https://github.com/can1357/oh-my-pi/issues/10626), [#10635](https://github.com/can1357/oh-my-pi/issues/10635), [#10647](https://github.com/can1357/oh-my-pi/issues/10647) | Filed the day before an 11-day merge gap; roboomp PRs still open and conflicting weeks later. Timing, not shape. |
