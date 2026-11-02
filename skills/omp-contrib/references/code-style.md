# Code style: what the maintainers write, change and reject

Part of the `omp-contrib` skill; phase names in *italics* are listed in `../SKILL.md`.

## Write the code the way the maintainers do

Maintainers push fixup commits onto the PRs they merge, so their taste shows up as edits (the
before -> after record below); since 2026-10-08 the maintainer (H4vC) also sends PRs back with written change
requests (*Maintainer change request* in `workflow.md`). Read
their written taste at `origin/main` before writing: `.omp/commands/cleanup.md` §3–4, roboomp's
`python/robomp/src/prompts/kickoff_pr_review.md` § Conventions, and `AGENTS.md`. Those win over
this list, which holds only where our code has differed from theirs.

- **Build only what the title needs.** No new settings, flags, single-caller options objects or
  abstractions, re-validation of repo-owned data, warn-once caches, or legacy branches unless an
  existing user's stored state would break. Name the rest as non-goals. cleanup.md forbids them;
  roboomp ranks sprawl down. Tests count too: a test of behaviour the PR doesn't change is another
  PR (CONTRIBUTING.md, "one logical change"); the maintainer deleted #15414's screen-state notice test from a
  display-awake fix (`3fe61bb3da`). precheck NOTEs each commit scoped outside the title.
- **Pass state explicitly, and keep only what its readers use.** Thread values through parameters
  and types; a failure reason rides on the error or return value. No module-level `WeakMap`,
  `WeakSet` or `AsyncLocalStorage` carrying state between modules: roboomp treats a global
  mutated across sessions as a blocker. A module-private brand on objects the module itself
  creates, read through an exported predicate, is fine; the maintainer wrote one (`isDateCwdReminderControl`,
  `9bbd15fe63`). The same holds inside a struct: a fact rides with the thing it qualifies, not in
  a side map another method reads later, and is stored in the smallest form its readers compare.
  #15574 kept each ref's identity as field strings, matched by a wildcard for fields the app
  always fails, plus a per-target map of the last walk that `register` read; the maintainer kept a 64-bit
  hash and the walk that proved it per ref, passed in as `Uniqueness::Proven(&walk)` (`6e211f8cd8`,
  -134 lines), a shape with no room for the identity-size, string-type, window-root and
  walk-limit findings Codex had raised across its 15 rounds.
- **A tool result says when the tool degraded.** If it recovered, retried, reset state or
  returned less than asked, the result names it; an agent that isn't told repeats the action or
  trusts state that is gone. roboomp asked for this on #14410 (recycled tab), #14343 (input with
  no report) and #13660 (a DST-gap time silently shifted). An error's stated cause or responsible
  party is a claim like a comment's: name only what the failing signal establishes, and re-check
  text restored from `main` against what the PR measured. #15157 restored `main`'s tap-failure
  error naming Input Monitoring after its own matrix showed Input Monitoring never stops the tap,
  and called the app macOS holds responsible "the app that launched omp", which is omp itself
  under launchd (`4823076e83`); #15920 blamed a frame that a closed tab also explains
  (`be217bbd39`). An input the message was not written for gets its own arm that says where it
  failed: #15175's empty `selectText` text fell into the general message counting occurrences of
  `""`, and the maintainer's arm says no position in the value is after the prefix (`8345761da0`). Once
  input has gone out, a later cancel or timeout must not report it unsent: #15184 waited for a
  background shortcut's reply with the cancellable `control::wait`, so an Escape after the keys
  were posted came back `Cancelled`, and the maintainer made that wait a plain sleep (`78bf1669cc`).
- **Fix a type where the value is produced, not with a cast at each call site.** The maintainer replaced
  #11613's commented `as Uint8Array<ArrayBuffer>` casts with an encoder returning that type
  (`689ba7a33e`). Absence with several causes is a named union or enum, not `undefined` or a
  boolean (`a4d463370b`, `c72b7663ef`; #15574's `unique: Option<bool>` became `Uniqueness`,
  `6e211f8cd8`).
  A decision over an enum names every variant instead of ending in `_ =>`, so a variant added
  later has to choose: the maintainer replaced #15176's `_ => return false` in `Request::takes_over` with the
  22 background-only requests listed by name (`ff6025abdb`).
- **Reuse before writing.** Search central helpers and our own open PRs; extract on the second
  copy, which roboomp flags. A private method in a neighbouring file counts (`939de631c7`).
- **Find everything that can break what the fix promises, and test the hardest.** Most of the maintainer's
  code fixups in the 2026-10-05/06 rounds were one miss: the fix held on the path we ran and
  broke on a neighbour. Before calling it done, list with `xd://lsp` references or grep whatever
  writes, reads, ages or reacts to what you changed: other writers of persisted state
  (`3c408d0106`), readers of a changed payload (`31f15cd077`), consumers of a re-derived constant
  (`cbcc326488`), pipeline transforms (`9bbd15fe63`), eviction or expiry code whose premise the
  change alters (`b2347fa6df`), events a new teardown step fires into live listeners
  (`4b17decb11`), and the window where a cheap signal (`isStreaming`, `signal.aborted`, a
  role/label match, an open dialog) is true but wrong (`e27123ddb8`, `1b8ce877a2`, `42537a9dc2`; a
  dialog bounded by `ask.timeout` goes on without the user, `7a4229b0d7`). A field added to
  a persisted entry or record reaches every reader of its siblings: serializers, replicas, and the
  session anonymizer, which keeps only fields it has a rule for (#15680's `runtime`, `71da31fb7d`);
  precheck NOTEs files that name a third of a type file's fields but not the new one. A comment or
  body claim ("keeps the message count", "unchanged", "stays conservative") needs that list
  behind it, and the docs, tool prompt and CHANGELOG that state a contract change with it
  (`b9d0609e4d`).
- **When we filter or shorten what a tool returns to the model, say what was dropped and how to
  get it back**. Dropping is right when the measured common case is noise, but
  a silent drop turns the rare task whose subject is the dropped data into a false negative: an
  SEO audit or a mobile-QA check that reads a page without `og:image` or `viewport` concludes the
  page has none. Name the dropped items (keys, not values) next to the result, plus the selector or
  call that returns them in full (`:raw`, a range, an artifact), and measure both sides: tokens
  saved, and how often the dropped data was used (#17393: 0 of 60 sampled `og:image` URLs shown by
  `read` reached a later call; omp's truncation notices follow the same shape).
- **Restructure freely; keep what users and resources see outside the title's promise.** The maintainer
  kept every structural cutover in these rounds (navigation moved out of worker init, payload
  fields deleted, eager handles made lazy, maintainer code rewritten once our change broke its
  premise) and restored every outcome we had changed past the title: a failed or cancelled open
  leaving a tab behind (`825806e402`, even though our body named it as a decision), a cancel
  killing the page's own fetches (`1b8ce877a2`), a held ref failing sooner than on `main`
  (`42537a9dc2`), elements without an id becoming unusable (`a80a00d68e`), library validation
  and exits our replacement dropped (`ab366bbd1c`). So before replacing code, list what it
  guarded, preserved, rolled back or tolerated, and make every call the diff removes a deliberate
  drop: #15604's refactor lost `enable_web_accessibility(pid, &app)` in `window_records` and the maintainer
  put it back (`e84a0a6f5c`); precheck NOTEs each removed call statement whose callee no added
  line calls. Outcomes inside the title's promise are ours
  to change; one outside it is a behaviour change that belongs in its own PR. On a path the fix
  adds, a fallback that returns the bug's value still ships the bug (`939de631c7`), a wait in a
  deadline-bound operation ends with that deadline (`7acc7ae9d4`), and under uncertainty the
  fix fails toward the harmless outcome ("a needless new ref is harmless, a ref renewed onto
  another element is not", `1a3bd04df5`). A probe whose answer is kept for the connection keeps
  only a deciding answer and runs under its own deadline, not the wait it precedes: on #15489 only
  a token read or `Not allowed` fixes the upload route, and a timeout, navigation or busy page
  sends contents once and checks again (`830a9b82eb`).
- **New behaviour stays inside its feature.** With an opt-in setting off, the session behaves
  exactly as on `main`, down to which hooks are registered; a workaround for one backend's
  behaviour runs only on that backend; a teardown or close path never starts or replaces a
  resource. Each such gate gets a test of its off side asserting `main`'s outcome: our tests had
  run only the on side each time. #16803 registered its cost-cap model-call hook with no cap set,
  so a user abort before the next request ended cleanly and `/retry` found nothing to retry
  (`f5f47678bc`, registered only while capped); #17768 waited for a relay detach report in
  launched and headless browsers too (`1c45a9113c`, gated on `#userDriven`); #17751's
  close-after-keep path called `acquireBrowser`, which can start a relay (`a47a579ff1`,
  `startRelay: false`).
- **A side effect we call accepted is a finding against the PR.** A comment, body line or test
  that names a new side effect as acceptable ("Chrome fires the click on the document root
  instead"), or pins a bug of `main` as expected ("subagents … rediscover additional roots"), marks
  a defect to remove, unless the subsystem's stated policy allows it (cite it). A test asserting
  that something did not happen listens everywhere it could happen (a `window` capture listener,
  not one on the target). #17778 released a cancelled press at `(-1,-1)` and its test listened only
  on `#target`, so the root click H4vC removed was invisible to it (`89833d37f4`); #16768's test
  asserted AGENTS.md leaking into subagents, and H4vC inverted it (`dcafcef642`); #17745's fix kept
  an extension's summary by dropping the template's guide, trading one loss for another
  (`921f5562ca`).
- **Platform code we can't run** (Windows UIA, Linux AT-SPI from the Mac): read the wrapper
  crate's source for who owns returned resources (`39ed781676`: `get_runtime_id` leaked a
  SAFEARRAY), reuse the access path the file already uses, and model the platform's documented
  failure modes (id reused after death, id missing) in the test mock so they run here.
- **Comments state the invariant or the causal chain, in present tense, sized like their
  neighbours.** A field whose siblings carry one-line docs gets one line. Measurements, vendor
  captures, CLI versions, issue or reviewer numbers, "used to" history and pointers to other
  files go in the commit body or PR, where they cannot go stale. A comment defending a cast
  means the type should change. Our open PRs carried about twice the maintainers' doc-block rate.
- **Count tests by code path, not by scenario.** Before adding a test, name the branch it reaches
  that no other test in the PR reaches. Another trigger (idle, pre-prompt, `/compact`), another
  input of the same class (a fractional cap beside an integer one) or another environment that
  reaches the same branch is the same test: keep the case most likely to break, or extend the
  existing test, rather than add one; a loop of starting points inside one test counts as several.
  A bot finding's fix gets a test of its own only when a user would notice the failure at normal
  input; hardening for input nobody sends (a clock step, a non-multiple interval, a BigInt or
  cyclic value, a name containing a separator) is fixed in code without one. Never test debug-log
  wording, prompt or tool-description wording (a test that a branch the PR adds puts a section in
  or leaves it out is fine; a whole session built to find a prompt line in its request is not:
  H4vC kept #16918's renderer test and deleted its SDK one, `4b13432524`), catalog, KDL or
  registry rows read back through their builder, a cache-key version, or a mechanism the PR did
  not change. Why: between 10-29 and 11-02 H4vC pared the tests of 7 of our PRs to their distinct
  branches and kept every fix (`642fce6b03` kept 3 of #17490's 7 cases, `3587ec7f14` cut 347
  lines from #17510, `0fa4a8a570` "pare merged PR tests to behavior that can regress" on five),
  and cut about 210 more lines in post-merge cleanups (#16297, #16579, #16918, #17351, #17391,
  #17393). AGENTS.md Testing Guidance already bans these ("duplicate rows", "static echo", prompt
  boilerplate); our test lines ran 1.0–3.6× source lines on those PRs, against H4vC's 1.0.
  precheck NOTEs logger and prompt-text assertions and test volume past its thresholds (`tests`,
  `log-test`, `prompt-test`).
- **One regression test that fails without the fix, through the real path, asserting the exact
  outcome.** Put it in the nearest existing test file and reuse its fixtures. No wall-clock time,
  no internals exported for tests, no generators the bug doesn't need. Maintainers delete tests
  that pass anyway (`42c7369016`). A test that asserts on the text of a script or source file
  proves nothing ran: #15599's cmux test checked that the page script contained `"body"`, and
  the maintainer's run of the script in Chromium found the empty-`innerText` bug (`132e741411`); precheck
  NOTEs such assertions. Check what the code claims against what happened, not
  against the predicate the code uses: a log saying "falling back to V1" is tested by whether
  V1 ran (`809d8658d7`). Use inputs the change could actually break (whitespace inside JSON, a
  first-row empty cell), assert only values the test controls (not OS window geometry), and
  delete a mock-echo test once a real-path test covers the contract. Forwarding is the same echo
  (AGENTS.md Testing Guidance, "passthrough option forwarding"): a test that a facade method hands
  its arguments to the native call, or that the addon's required-methods list holds a new name,
  fails only when someone deletes the line it restates. The maintainer dropped both from #15175
  (`c5c7b72937`) and kept its read-only refusal test; keep the decision, boundary or error the
  facade adds (an empty menu path refused before native runs), not the hand-off. Test both sides
  of each boundary the docs state (missing from one snapshot vs two, `b2347fa6df`), and when a fix
  moves a boundary, the cases the move pushes out on the other side: closing #15919's drop-read count
  to keep deferred `dragover` reads out also dropped an async `drop` handler's reads
  (`1e9a85daf8`); when the fix
  touches a failure path, assert what happens to the resource (tab gone, refcount 0), not only
  the error. Live checks drive the state changes the feature claims to handle (a relabelled
  button, a row that briefly disappears), not only the unchanged case. Read a rejection that
  settles from I/O with `rejectionOf` (`test/helpers/rejection.ts`), not `expect().rejects`,
  which hangs Bun on Windows (`0674f2c81b`). Assert the parts of a message a user relies on, not
  the whole string (`52e8770000`); one scenario per test, not two with a `process.exitCode`
  reset between; clear env keys the code under test falls back to (`CURSOR_ACCESS_TOKEN` masked
  a stored row, `f5b78e8db0`); a fixture matches the scenario's kind (an automatic pin, not an
  explicit one, on #14749); sort before comparing when order is not the contract (`253c27dd20`).
- **Never a test whose result depends on wall-clock time**. A sleep, a clock
  read, an elapsed-time bound (`toBeLessThan(700)` on a duration, #14236), a short per-test limit or
  a race against a timer passes on an idle Mac and fails on a loaded CI runner, so it breaks omp's
  CI for everyone. Make time an input instead: fake timers (`jest.useFakeTimers`,
  `advanceTimersByTime`), a clock or deadline the code takes as a parameter, or a channel or promise
  the test awaits for the event itself. A hang is the runner's default limit to catch, never a
  tighter deadline of ours. A behaviour that is only about timing (a release grace, a debounce) is
  tested by advancing the injected clock to each side of the bound. precheck FIXes added test lines
  that sleep, read a clock or race a timer (TS and Rust).
- **No incidental churn.** Touch only the lines the change needs: no reformatting, comment
  reflow, reordering or renames elsewhere. Maintainers revert it (`8a9660df00`, `9311adf9b7`).
- **Learn from each merge.** Maintainer feedback on a merged PR lands in three places: commits
  on our branch before the merge, edits inside the merge commit, and commits on `main` after it
  ("chore: post-merge cleanup for #N", "fixup! Merge PR #N", "fixup(#N): …", or unlabelled
  follow-ups that rewrite our lines). In the 10-24..11-02 rounds 8 of the 13 instructive commits
  were in the third place, which reading `<merge>^1..<merge>^2` misses. `pr-trace --learn [N …]`
  lists all three per merged PR; read each diff and record what is new here (a table row, a rule
  once it repeats). Repo-wide sweeps it marks as such teach nothing about our code unless they
  recur.

## Evidence behind the rules above

 Built 2026-10-04 from
full-diff reads of ~28 can1357 commits, ~24 H4vC commits, ~50 maintainer fixup commits and reviews on
external PRs (all of ours included) and all 34 of our open PRs at the time. Re-read the upstream
taste sources at `origin/main` before relying on the quotes below; they win.

## Where the taste is written down

- `.omp/commands/cleanup.md` (can1357's autonomous cleanup loop), §3 and §4. The most explicit
  statement of what he wants code to look like:
  - "NEVER add dependencies, config/options, feature flags, wrapper layers, one-implementation
    abstractions, or 'future-proofing'."
  - "Narrow once at IO boundary … Delete downstream `?.` on non-nullable values, `?? fallback` on
    non-optional values, … and `as` casts papering over flow." "Genuinely sometimes-absent value →
    fix TYPE upstream; NEVER add downstream guards."
  - "Swallow-and-limp `try/catch` → delete or propagate error. Precise catches only."
  - "2+ copies → one function in nearest common domain module." "NEVER boolean positionals."
  - "NEVER add caching layers." "NEVER reformat/restyle outside touched cluster."
  - "NEVER drive-by comment/doc sweep; comment only new non-obvious code."
  - "Deletion favored: net-negative LOC expected."
- `python/robomp/src/prompts/kickoff_pr_review.md` § Conventions: "Adherence first-class ranking
  signal; breach is finding, not waived nit." Default-behavior change caps the rank at P2; sprawl
  ranks down; "Global singleton mutated across sessions" is a hard blocker.
- `.omp/commands/review-prs.md`: how H4vC lands external PRs (one conventional fixup commit per
  problem on top of the contributor's branch, then merge).
- `AGENTS.md` § Code Quality, Central Utilities, Testing Guidance, Changelog.

## How maintainers give feedback

Inline review is roboomp's and Codex's (about 3,700 inline comments since 08-29 against 14 by
maintainers). Maintainers act by pushing fixup commits onto the contributor's branch before
merging: 154 such commits on 103 of 883 external merges since 08-15, 144 of them by H4vC. 36 of
the 154 fix CHANGELOG entries. Until 2026-10-07 no maintainer had
written a review comment on any of our 58 PRs; on 2026-10-08 H4vC wrote seven change requests on
PRs he did not merge that round, each a concrete regression with a suggested fix. Since 10-24 most
of his feedback on ours lands on `main` after the merge, as post-merge cleanups, fixups and
follow-ups (*Learn from each merge*). So the feedback is his commits, before and after the merge,
plus those requests.

## Fixups on our PRs (before → after)

| Commit | PR | Before (ours) | After | Lesson |
|---|---|---|---|---|
| `a6179d1a4f` H4vC | #11613 | ~190 lines fetching and parsing cursor.com's pricing markdown, threaded through 6 functions | KDL rate card only; +71/−325 | Policy and prices live in KDL; delete a fragile subsystem rather than harden it |
| `689ba7a33e` H4vC | #11613 | `body as Uint8Array<ArrayBuffer>` plus a comment explaining why the cast is safe, in two files | encoder returns `Uint8Array<ArrayBuffer>`; type guard in `Writer.finish()` | A comment justifying a cast means the type is wrong upstream |
| `fb0a01afae` H4vC | #11613 | cached-token change also carried by our #13723 | removed: "#13723 carries that fix" | One change lives in one PR, including against our own PRs |
| `0693c80629` H4vC | #11613 | HTTP/1 turn hung on an end-stream error; test drained the stream with no assertion | `endListener()` on close; test asserts `terminalEvents` equals `["done"]`, bounded by `SETTLE_TIMEOUT_MS` | Assert the exact terminal outcome; we leave a hang to the runner's limit, never a deadline of ours |
| `2b6c159408` H4vC | #8577 | 1,020-line per-model TS table read by id | `rules/providers/factory-droid.kdl` | No per-model TS tables |
| `58006868fb` H4vC | #8577 | `stripThinkingHistory: false, fastMode: false` plus a test exemption hiding the mismatch | unset, exemption deleted | Unset means unset; never paper over a parity test |
| `c72b7663ef` H4vC | #8577 | `Object.assign` clobbering parent schema; dedupe filter copied twice | `mergeFactoryDroidSchemas(…, requiredMerge: "union" \| "intersection")`, `dedupe()` | Named discriminant over boolean; extract on the second copy |
| `a4d463370b` | #13659 | `Option<…>` return; generic "not found" error | `enum AttachedSearch { Found, Missing { truncated } }`; error says the search hit its limit | Absence with causes is a sum type; errors say why |
| `8583df691f` | #13726 | filter dropped buckets that still recorded usage; test could not tell the filter from dropping everything | keep `used > 0`; fixture exercises that branch | A test must distinguish the fix from plausible wrong code |
| `9b1a2f244c` H4vC | #13822 | changelog "on macOS" | every platform affected | Changelog states the full blast radius |
| `30f532944f` can1357 | #13527 | version bump + Fusion removal + default-model change | only the version bump, cherry-picked | Bundled default changes cost the rest of the PR |
| `929c8ed515` H4vC | #14226 | `select()` no-match reset the dropdown, fired change, returned `[]` (roboomp asked; we declined as a non-goal) | throws `No <select> option matches …` before touching it, all three backends | Invalid model input fails before mutating, with the sibling backend's error |
| `0e96b11365` H4vC | #14227 | verbatim `textContent` fallback replaced by whitespace-collapsing `blockText()`; fixture `{"a":1}` collapsing can't change | raw-text roots verbatim, `pre` context kept, nbsp kept, first-row corner tab kept | We dropped what the pass-through preserved without noticing; fixtures the change could break would have shown it |
| `a0038403bb` H4vC | #14236 | new early `return "extension-gone"` above `staleRelay ? "outdated-relay" : …` | early return honours `staleRelay` | A new return obeys the function's existing outcome precedence |
| `809d8658d7` H4vC | #14245 | log text checked against the predicate table the code uses; fetch threw, so V1 never ran | stub answers V1, records URLs; asserts `claimedV1 === ranV1` | Test a claim against the observed effect |
| `31f15cd077` H4vC | #14247 | kept user turns by `role === "user"`; newly kept images counted as base64 text by the token counter | `isUserAuthored` from the host's `isUserTurnInitiator`; image-aware count | Follow every reader of a payload you change; take host concepts from host helpers |
| `9bbd15fe63` H4vC | #14251 | comment "every transform keeps the message count" (false: reminder controls); rebuilt summary copy; real-session test without reminder change or second compaction | counts past controls, reuses the live object, tests each roboomp-named input | Enumerate pipeline stages before asserting an invariant; identity-keyed caches need the live object |
| `e27123ddb8` H4vC | #14261 | `isStreaming && last assistant` treated as in flight | stop at a user message; test with a stale unpaired call | Test where the cheap signal is true but wrong |
| `3bd6038e09` H4vC | #14286 | TS `FALLBACK_IMAGE_TOKENIZATION` and a constant repeating KDL numbers; two of our PRs pricing frames two ways | fallbacks as `on-api … priority=-1` in KDL; one `frameBilling` path; compiled-payload test | Fallbacks are policy; related PRs ship integrated; removed runtime validation becomes a test |
| `26615adc6e` H4vC | #14286 | cheap tier default, high-res only for `>=4.7 <10`; open `>=5.6` on OpenAI | high-res default with cheaper carve-outs; `<10` guard on OpenAI too | Must-not-undercount estimates default expensive; guard a parser quirk on every open range |
| `cbcc326488` H4vC | #14291 | tokenizer charged per-shape price; both archive caps still divided by 5,024 under a "mirrors … by construction" doc | caps use `max(5,024, shape price)`; forced `5x8` test | Change one half of a paired estimate, update every consumer |
| `18e065003b` H4vC | #14277 | over-budget render rejected (roboomp: "throws instead of retrying"; we fixed only calibration) | re-render once at the measured fit | Answer every clause of a finding; degrade instead of reject |
| `3c408d0106` H4vC | #14338 | contract persisted only at model calls; test asserted `toBe(lastRequest)` | also persisted on the batch-end clear; asserts the finished batch is gone | Hook every writer of persisted state; assert the correct state, not the last one sent |
| `939de631c7` H4vC | #14409 | new viewport probe beside `recording.ts`'s; fallbacks returned `DEFAULT_VIEWPORT` (the bug's 1365x768); asserted OS-dependent width | shared `readPageViewport()`, last measured viewport as fallback, asserts DPR only | Fallbacks never return the bug's value; assert only what the test controls |
| `474f7e66af` H4vC | #14410 | recycle notice listed roboomp's examples | lists everything the recycle payload resets | Loss lists come from the code that loses; a reviewer's list is a lower bound |
| `7acc7ae9d4` H4vC | #14417 | `await arming` before the op watchdog | `untilAborted(opSignal, …)` | Every await in a deadline-bound op runs under its signal |
| `ab366bbd1c` H4vC | #14421 | own main-frame wait for all non-networkidle values; value import of puppeteer-core; no detach exit | allowlist load/domcontentloaded, rest to Puppeteer; type-only import; rejects on detach/close | Read what the replaced library routine guarded before replacing it; area import conventions |
| `455037f6cf`, `1dffd3c136` H4vC | #14415 | iframe read bounded by one deadline, but a dead frame cost every later observe the full wait; scoped selector used `Node.contains`, which stops at shadow roots | frames that missed the deadline skipped until they navigate (module `WeakMap<Frame, loaderId>`); `composedContains` crosses shadow roots | A bounded wait that repeats on every call still needs memory of the failure; DOM containment checks cross shadow roots |
| `825806e402` H4vC | #14420 | took roboomp's "wrap the message for any Error": every failed or cancelled open kept its new tab (named as a decision in the body) | only a timeout keeps a created tab; hard failure or cancel rolls it back as on `main`; typed `NavigationTimeoutError`; existing attach-failure test asserts the tab is gone and refcount 0 | Structural cutover kept, outcome past the title restored; assert the resource's fate on failure paths |
| `1b8ce877a2`, `4b17decb11` H4vC | #14425 | took roboomp's `if (ac.signal.aborted) await this.#stopLoading()` before cleanup | stop only while a main-frame navigation is pending; detach run listeners before stopping | A bot's patch is a pointer, not the fix: gate broad side effects on the exact condition; a teardown step fires into live listeners |
| `0674f2c81b` H4vC | #14425 | `expect(run).rejects` on CDP-settled runs | `run.catch(e => e)` (the `rejectionOf` pattern) | `.rejects` hangs Bun on Windows; precheck NOTEs it |
| `2ae62a813e`, `bd67876dc3` H4vC | #14431 | lazy node ids keyed by backend id; roboomp's `ownerDocument === document` guard added untested | ids carry the document's `loaderId`; bfcache restore clears them; the Document root resolves | When eager becomes lazy, carry the old binding in the key; a guard added for a bot gets its own neighbour tests |
| `42537a9dc2`, `b2347fa6df` H4vC | #14485 | role/label change expired the held ref at once; maintainer's evict-before-walk kept after refs began to persist | old ref ages out normally; eviction moved after the walk (`end_snapshot`) | Never fail a held handle sooner than `main`; re-read lifecycle code whose premise you changed |
| `1a3bd04df5`, `a80a00d68e`, `39ed781676` H4vC | #14485 | reused RuntimeId accepted "as on main"; id-less UIA elements refused; `get_runtime_id()` | liveness check (roboomp's proposal), `Option` id with fresh refs, property read that doesn't leak the SAFEARRAY | Implement the bot's mechanism; absence is `Option`, not a sentinel that refuses; read the FFI wrapper for ownership |
| `b9d0609e4d` H4vC | #14485 | follow-up commit changed the ref contract in one doc of five | docs, tool prompt and both CHANGELOGs | Every surface stating a contract moves with it, the tool prompt included |
| `90da647b69` H4vC | #14748 | replaying API-dropped thinking verbatim made the API report the same drops on every later request, each logged as a warning | warn once per dropped block (replay key), repeats at debug | Follow a fix's consequences to its observable side effects: logs, events, metrics |
| `f5b78e8db0` H4vC | #14753 | stored the renewed access token as the refresh token ("the session token is its own refresh credential") | keeps the stored refresh token unless the response rotates one; test clears `CURSOR_ACCESS_TOKEN` | A vendor-token claim needs a probe of the success path; roboomp had said the live check covered only `shouldLogout` |
| `51a7d6086c` (merge) H4vC | #14758 | `--history` threw a stack dump on an unreachable or old broker (roboomp's "behavior note") | one-line `auth broker request failed` error, exit 1 | A roboomp review-body note is a finding |
| `d8b21928ec` H4vC | #14760 | row key without the tier merged Antigravity's per-tier `Usage` rows; Copilot's window id `billing-period` | tier joins the key only for meters one report repeats; Copilot id `monthly`; width over all titles | A shared key change touches every provider's producer: test each one that repeats a label |
| `ce04d87bf0` H4vC | #14761 | `notifyUsageStale(signal?)` became `(provider?, signal?)` with no Breaking Changes line | Breaking Changes entry; test that scoped invalidation re-fetches | A signature change that breaks existing callers is a Breaking Change; precheck NOTEs changed parameter lists |
| `6e8bc4c9c2` H4vC | #14762 | broker imported `resolvePeer` from `auth-gateway/http`; the crash log still printed the raw path | helper in `utils/resolve-peer.ts`; crash log uses `loggablePath`; trusted-proxy test | A shared helper lives in a neutral module; fix every site of the same leak; test both sides of a flag |
| `52e8770000` H4vC | #14763 | full stderr strings; two scenarios in one test with an exit-code reset | asserts the parts that matter; one scenario per test | Assert meaning, not bytes |
| `2bb17955c3` H4vC | #14764 | policy line checked only the used fraction | a provider-flagged `exhausted` status wins, as the rows and routing already do | Reuse the rule your neighbours apply to the same data |
| `253c27dd20` H4vC | #14767 | a synthetic `UsageReport` stored on every history account; new account-id qualifiers without a redaction test | report built only for Codex; redaction test for the ids; order-free assertion | New identity text in output needs a `--redact` test |
| `18fc177b04` H4vC | #14657 | regression test placed far from its siblings | moved next to the other `only_on_exit` tests | Put the test with the tests of the same mechanism |
| `1111b1fc03` H4vC | #14751 | `CACHE_LOOKBACK_POSITIONS = 20` in `pruning.ts`, applied to every model; positions counted by hand per entry kind | a `prompt-cache-lookback` KDL axis on the anthropic class (undefined elsewhere: no bound); positions counted over the session's own `convertToLlm` output | Policy true for one model family is a KDL axis; precheck NOTEs (`kdl`) such constants. Our third reviewer had asked to scope it to Claude and the parent dropped that finding |
| `6a5629ed5a` H4vC | #14754 | a `system-prompt-digest` entry stayed on the old branch when a checkpoint rewind moved the reply; every model call reverse-scanned the whole branch for it | rewind re-records the digest; an incremental scan memoized on the branch view | A new saved entry must follow its reply through rewind and branching; no per-call scan of history (review-brief criteria 3 and 4) |
| `7a4229b0d7` H4vC | #15762 | every dialog counted as waiting for the user, so the display hold ended; dialog wrappers cached by property name (Codex flagged the cache; we disproved only its `undefined` getter case) | a dialog with an `ask.timeout` deadline (and the timed `cfg://` approval) keeps the hold; the cache re-wraps when the member is replaced; docs updated | A cheap signal (a dialog opened) is wrong where a setting lets the turn go on alone; a disproof covers the mechanism a finding names (a stale cached wrapper), not only its example |
| `7c9d457d70` H4vC; `6741331889` H4vC | #15941; #16230 | `Fixed` line for sleep prevention broken by #14591, which no release had shipped; #16230's screenshot-deadline fix went out with no line, though a release had shipped the bug by its merge (precheck FIXes its head `7d7afab898` today) | line dropped; line added | A fix of an unreleased regression gets no CHANGELOG line (changelog.md); precheck names the unreleased lines it rewrites. Judged at merge: once a release ships the bug, `pr-trace` says `changelog: regression shipped in vX` and the entry is due in the next push |
| `1e9a85daf8` H4vC | #15919 | our Codex fix closed the drop-read count right after `drop` dispatched, so a handler reading files after `await` failed the upload | a task-boundary settle (`MessageChannel`) after each drag event, count closed after `drop` settles; async drop zone in the fixture | A script's `dispatchEvent` runs no microtasks between listeners as a user's event does; moving a boundary needs a test on its other side |
| `be217bbd39` H4vC | #15920 | a relay tab that could not be reattached after `target_closed` was blamed on another extension's frame, though Chrome reports the same reason for a closed tab (Codex said so; we left it "for review") | the message names both causes | An error names a cause only when the signal tells it apart; the hand-off rule (workflow step 7) now makes such a deferred finding ours |
| `4823076e83` H4vC | #15157 | restoring `main`'s refusal (`24f13dc1eb`) brought back its error asking for Input Monitoring, which our VM matrix showed never stops the tap; `denied` called the responsible app "the app that launched omp"; a Screen Recording grant revoked mid-capture kept `main`'s message without pane or app, though the body said Screen Recording errors name the app | "macOS refused its event tap, so no input was sent; check Accessibility …"; "which macOS holds responsible for omp"; the revoked path goes through `permission::denied` | An error's cause is a claim: name what the signal shows and re-check restored text against the PR's own findings; a helper adopted for one class of error reaches every site of that class (as `6e8bc4c9c2`) |
| `6e211f8cd8` H4vC | #15574 | ref identity stored as field strings with an `UNKNOWN_FIELD` wildcard for fields AppKit fails on every read; the proving walk in a per-target `roots` map that `note_window` set and `register` read; `unique: Option<bool>`; a `u32` partial count read only as nonzero | a 64-bit hash (an always-failing field hashes as that failure), `Proof { identity, walk }` per ref, `Uniqueness::{Proven(&WholeWalk), Shared, Unknown}`, a `bool`; +211/−345 | Store a fact with what it qualifies and in the smallest form its readers compare; a failure the platform repeats on every read is a value, not a wildcard |
| `c5c7b72937` H4vC | #15175 | a worker test that `selectText` handed its text and options to the fake native session and returned the fake's selection unchanged; a desktop-adapter test listing 16 required methods to show an addon without `axSelectText` is refused by name | both deleted (−55 lines); the read-only refusal test kept | A facade's hand-off to native and a copy of the required-methods list restate the code (AGENTS.md: no passthrough forwarding); test what the facade decides. Same kind removed from our drafts: #15185's menu-path forwarding tests (JS and Rust), #15563's `type()` rows |
| `8345761da0` H4vC | #15175 | an empty `selectText` text with a prefix that matched nowhere fell into the message counting occurrences of `""` | its own arm: "no position in the element's value is after prefix …"; test asserts it | An input the message was not written for gets an arm naming where it failed |
| `78bf1669cc` H4vC | #15184 | the reply wait after a background shortcut was posted went through `control::wait`, so a cancel during it reported a sent shortcut as `Cancelled`; a doc comment named "no Screen Recording permission" as the reason the window list is missing; 16 CHANGELOG lines for one PR, each naming mechanism (`openAndSavePanelService`, AX window lists) | `std::thread::sleep` with "the shortcut is out: a cancel now must not report it unsent"; "when the window list cannot be read"; 7 lines grouped by what the user sees, in second person ("your app") | A result after input went out never says nothing was sent; a comment names only the cause the signal shows; CHANGELOG lines per user-visible outcome, not per fix |
| `ff6025abdb` H4vC | #15176 | `Request::takes_over` ended in `_ => return false`; CHANGELOG said "the tool prompt now says Escape stops only takeover input" | every remaining variant listed by name with "a new request variant must decide whether it arms the stop"; "Pressing Escape in your own app no longer stops … background window input unless task control is held" | A safety decision over an enum has no wildcard arm; a CHANGELOG line says what the user sees, not what the prompt or docs now say |
| `99f03d81f8`, `1bf6594bbe` H4vC; `bf9fd4bd6a` H4vC | #15564; #16202 | macOS-only text-locator helpers in the shared `text_range.rs` were dead code on Linux and Windows builds; supervisor tests built `ComputerSupervisor` with the default Escape-stop counter, which reads the native addon; #16202's last bot-round push (`8bb3284667`) named the Wayland key hold's closure parameter `held`, shadowing the press counter, so the Linux build failed (E0618), and its test fake's `if let Some(s) = lock().take()` held the guard across `cancel()` | module-level `cfg_attr(not(target_os = "macos"), allow(dead_code, reason = …))`; tests pass a `NO_ESCAPE_STOPS` stub (`read: () => 0`); parameter `hold`, `let cancel = …take();` before the `if let` | Code gated on one OS compiles only there, and CI compiles no Rust before the merge: this row's text ("check the other targets") didn't stop #16202, so precheck now FIXes a Rust diff until `rust-check` passes on each platform it builds on (each on the host its `build.<platform>` key names; `ci` and `none` as in `config.md`), every push that changes a Rust line included; it reproduces both #16202 errors on `8bb3284667` and passes `bf9fd4bd6a`. A test that doesn't exercise native state injects a stub instead of reading the addon (a stale addon made 7 of #15564's tests fail on one Mac) |
| `89892decd0` H4vC; `5b4666a490`, `f10a9c6008` H4vC | #15195; #16445 | #15195's rewritten focus guard counted any click within its switch window as the user's, so after #15184 merged (with click placement on the target, `a78b2a81e1`) a click in the user's own app let a self-activated target stay in front again; `main` turned `wait` with nothing to wait for from an error into an idle result while #16445 still threw | merged main twice and kept main's placement inside #15195's guard himself, then merged; resolved #16445's `wait.ts` conflict to main's idle result and moved its tests to it | When a sibling's merge changes a function your open PR rewrote, carry its fix into your version before the next push; H4vC will otherwise do it himself. The watcher reported #16445's conflict at 17:05Z, 11 min before his merge of `main` resolved it: a `conflict` line in `pr-trace` is next-step work the day it appears (*Cadence*) |
| `ead4d0ddca`, `5c996a3818`, `ef7c45bd4b` H4vC | #15563, #16140 | Windows background `el.type` focused the element; after H4vC rebased #16140 onto main, the CHANGELOG still carried its parents' lines and the key reroute failed clippy (`register` could be `const fn`; unchecked `Duration` subtraction in a test) and rustfmt | `el.type` sent to the element's own control window without focusing it; only #16140's entry kept; clippy fixes; the file reformatted in his later `83cc2a3472`/`13d09929b7` | Background paths on every platform keep focus where it is; a rebased child keeps only its own CHANGELOG lines; clippy runs with `--all-targets` on the OS the code is for (H4vC's build lints tests; CI's skips them): `rust-check` on the platform's build host (`build.macos`, `build.windows`), which precheck asks for (row `bf9fd4bd6a`), finds both lints and the rustfmt diff on `5c996a3818` |
| `83cc2a3472` H4vC | #15562 | after #16140 and #15563 merged, #15562's input watch didn't count #15563's element input or menu reads as input into the app (its `app_access` match ended in a catch-all), and #16140's key-reroute taps stayed open when the process exited | element input and menu reads listed as app input; the reroute taps closed on exit | When a sibling merges first, re-walk every match and lifecycle your PR adds against what the sibling added (new request kinds, new taps), and fix it in your next push, before H4vC has to |
| `914654c252` H4vC | #16390 | the relay guidance block rendered `browser.cdpUrl` verbatim (`cdpUrl: fallback.cdpUrl` into `prompt.render`), so a URL's userinfo or token query went to the model provider in the system prompt | `redactUrlForLog(fallback.cdpUrl)`; the test's URL carries `user:pw@` and `?token=` and expects them redacted | Text rendered into a prompt leaves the machine: a settings or env value that can carry a credential is redacted at the render site (as `6e8bc4c9c2` did for logs); precheck NOTEs (`secret`) such a value passed to `prompt.render` or a template placeholder, review-brief criterion 9 |
| `9b481c53bd` H4vC | #16433 | a test of two concurrent `rm -f` runs on one tree ran everywhere; on Windows a file another process is deleting (delete pending) reads as access denied, not gone, so the race still fails there | `#[cfg(unix)]` with a comment saying why | A test of filesystem or process semantics runs only where those semantics hold: no CI job runs Windows or macOS tests and H4vC does, so gate it to its platforms (checklist, CI item) |
| `1f6d9ee075` H4vC | #16252 | role-name matching that five Codex rounds kept extending case by case (each round a new way a name is computed) | hidden `aria-labelledby` targets read whole, ARIA range values, nested `aria-labelledby`, from the accessible-name rules themselves | A third Codex round in one function means the model is wrong (workflow step 7): implement the spec's algorithm (here accname) or ask the browser for the computed value, not the case the finding names |
| `642fce6b03`, `3587ec7f14`, `0fa4a8a570` H4vC | #17490, #17510, #16309, #16552, #16595, #17766, #17772 | seven snapcompact cases that each start another way (context notes, `/compact`, idle, pre-prompt) and end in the same frame-count check; eight text-reader session tests re-proving "marker text, no images" from other starts; a 3×4 `/proc` × install-start matrix; KDL credit rows read back through the registry; a cache-key version bump tested | three cases; two tests; `if (procfs !== "cannot be listed") continue` ("every unusable /proc routes to the same guarded installer"); the echoes deleted; every fix kept | Count tests by code path: a test exists for a branch no other test reaches |
| `3000d4e84d` H4vC | #17391 | `try { JSON.stringify(wait) } catch` for unserializable waits; a selector type test re-run on every poll; one test per Codex finding (a non-whole interval, a wall-clock jump, BigInt and cyclic rows) | `typeof wait === "number" ? String(wait) : describeArgument(wait)`; the id computed once before the loop; the fixes kept, their 4 tests deleted | Rare input is handled by the construct that covers it by construction; hardening nobody hits at normal input needs no test |
| `93adeecffb` H4vC | #17393 | a 7-line doc on a private helper; quoting of meta names containing `,;"`; a second `stripDataUriImages` pass; a test of `:raw` behaviour the PR did not change | 3 lines; no quoting; one pass ("`renderHtmlToText` already stripped data-URI images"); the test deleted | Defend against input the pipeline can deliver, once per transform |
| `f5f47678bc` H4vC | #16803 | the cost-cap gate registered on every session (`addBeforeModelCall`), so an abort before the next request stopped cleanly and `/retry` found no interrupted turn | `syncCostCapGate()` registers it only while a cap is set | With the feature off, nothing of it runs: test the off side |
| `1c45a9113c` H4vC | #17768, #17778 | the relay detach wait ran in launched and headless browsers too; our own RPC timeout recognised by a regex on its message, with a comment defending the coupling | `this.#userDriven &&`; `class RpcTimeoutError` and `instanceof` | A backend's workaround runs only on that backend; our own error is a type, not a message match |
| `89833d37f4` H4vC | #17778 | a cancelled press released at `(-1,-1)`; doc and body accepting that Chrome then clicks the document root; the test listened on `#target` only | released at `CANCELLED_RELEASE_POINT`, the root `click`/`auxclick` swallowed by a document-start capture guard; the test logs clicks on `window` | A side effect we call accepted is a finding; a "did not happen" test listens everywhere |
| `e6eba3dc43` H4vC | #17492 | four Codex findings on the request-size estimate left `Not fixed yet` under the round budget | those four fixes on our branch, merged 5 h after the PR opened | Deferred fixes go out in one final push once the rounds settle (workflow step 7) |
| `7f1d03d333`, `8a0bc691f8` H4vC | #16925, #17349 | a new instruction spliced into a maintainer's prompt bullet as a parenthetical; a `//!` paragraph left ragged by an insertion | his bullet restored word for word plus a bullet of ours; the paragraph rewrapped | A new instruction gets its own sentence or bullet; rewrapping a paragraph we inserted into is part of the change, not churn |

**2026-10-24..11-02 rounds.** H4vC merged 75 of our PRs with no comment or review on any; #16910 he
squash-landed verbatim as his own commit in an 88-PR batch. His feedback moved after the merge: 10
targeted cleanups or fixups on `main` and about 9 behaviour follow-ups, against one commit on a
branch (#17492), most of them paring our tests. Can's 10-29 sweep (`6469ddbe4d`, `20a20268d6`)
rewrote, then deleted, about 710 of our test lines on 8 PRs, mostly real-time browser, LSP and
OAuth tests. What changed: *Count tests by code path*, *New behaviour stays inside its feature*,
*A side effect we call accepted…*, the final push of deferred Codex fixes (workflow step 7),
`pr-trace --learn`, and precheck's test NOTEs.

**2026-10-18..20 rounds.** H4vC merged 78 of our PRs (median 15.8 h after opening, p90 36 h). No
human comment or review came on any of them: his feedback is his commits. Fork CI never ran before
a merge (every run `action_required`), so his build was the first: commits beyond merges on 7 PRs (rows
`bf9fd4bd6a`, `ef7c45bd4b`, `914654c252`, `9b481c53bd`, `f10a9c6008`, `1f6d9ee075`, `6741331889`),
27 CHANGELOG commits on 20 PRs ("move entry to Unreleased", "fold Unreleased sections after merging
main") as releases cut while ours waited, and a merge of `main` into nearly every PR (81 commits).
Codex was out of usage during review and reviewed the heads he pushed instead, after the merges:
he fixed those findings on `main` (`13d09929b7`, `1a97f79d28`, `d25d0ed5a9`, `8f5a0aa4ea`,
`864c1b370a`, `8567bdcab1`, `3166e4d221`) and 7 more were open on 2026-10-20. What
changed: `rust-check` and precheck's `rust` FIX, the `secret` NOTE, the checklist's CI item,
one CHANGELOG-only push per release once bot rounds settle (*Cadence*), and the post-merge sweep
(workflow step 10) backed by the watcher's record.

**2026-10-08 round.** H4vC merged 11 of our PRs between 00:53 and 01:40 UTC, pushing code or test
fixups onto 10 (#14755 got only a CHANGELOG move), and at 01:32 wrote change requests on 7 others, 6 of them
roboomp P0 "lgtm": #14749 broke the parent's explicit `/session pin` (#11939) for revived
subagents; #14751's lookback bound skipped the issuing turn and counted tool runs per block;
#14752 read a row index across an `await` and left a 401 caller rotating tokens; #14754's latch
fired after the prompt was captured and regressed resumes whose prompt lacked the late tool;
#14757 held a primary off for days when another account was free; #14765 conflicted with his
#14764 fixup; #14659 let `read ?q=` drop failing lines silently. Every one opened with the
CHANGELOG rebase note. Common thread: what `main` did on a neighbouring path, which the
independent review in workflow step 3 now asks about.

**2026-10-08 second round.** Between 10:00 and 17:24 UTC H4vC merged 9: four as sent, three with a
one-line CHANGELOG fix (two `### Fixed` headings our sibling PRs both added, one entry that drifted
after a release), and code on two, #14751 and #14754 above. Those two were the only PRs whose last
fix commits went out after a "needs changes" review without another review. A re-review gate was
built for that on 10-08 and retired on 10-10 (one review round per PR; `workflow.md` step 3).
No new change requests.

**2026-10-05 merge round.** H4vC merged 38 of our PRs between 22:18 and 00:36 UTC and pushed
code fixups onto 16, then 4 more (#14420, #14425, #14431, #14485) by 01:02 with 14 fixup commits.
Changelog placement was the most frequent fix: on all 7 browser PRs with fixups, plus
#14245, #14251, #14286, #14338 and #14277, he moved our line out of a released section or merged a
duplicate `###` heading, as separate commits (`5884d6cdfe`, `31dc7a144f`, `b66d936c75`),
inside code fixups, or inside his merge commit (`git show --remerge-diff bf15e67ba3`). P0 "lgtm"
PRs got fixups too (#14236, #14417). Codex posted on none of them. His one written comment
(#14434) invited a follow-up: per-tab or per-session download folders.

The same patterns on others' PRs: `8a9660df00` restored a contributor's field order, accessor and
a deleted JSDoc ("unrelated churn"); `9311adf9b7` reverted stray blank lines; `42c7369016` deleted
tests that passed without the fix; `327289f19c` un-exported a constant exported only for a test and
replaced a `beforeAll` monkey-patch with a restored spy; `0fb8d5b67e` moved a TS
`Record<string, Record<string, true>>` model table into a KDL axis. H4vC's written reviews ask to
split bundles (#11207 "bundles four independent changes", #9368 "carrying hitchhikers", #11834)
and to drop churn (#13284, #9374).

## Measured gap (added non-test source lines since 2026-08-15, regex counts)

| | can1357 | H4vC | Our open PRs (2026-10-04) |
|---|---|---|---|
| Comment lines / source lines | 18% | 28% | 24% (snapcompact PRs 27–47%) |
| `/**` blocks per 1k lines | 39 | 41 | 73 |
| New functions per 1k lines | 19 | 23 | 27 |
| Test lines per source line | 0.5 | 1.0 | 0.7 (small fixes 1.5–3×) |
| CHANGELOG entry, median words | 20 | 31 | 39 (our merged entries: 23) |
| `as` casts per 1k lines | 4.9 | 6.7 | 2.3 |

Comment volume is not the gap: both maintainers write multi-line why-comments above one-line
changes, and H4vC writes more than we do. The gap is what goes into comments and doc blocks, how
many symbols get a multi-line doc, and how much gets built beyond the fix.

## Patterns in our open PRs that maintainers would remove (2026-10-04)

- Beyond the title: `snapcompact.archiveShare` setting with min/max/UI (#14285);
  `AudioChunkerConfig` with `Partial` overrides for one caller (#13826); `documentationDelivery`
  on every prelude to deliver one guide (#13688); a full multi-vendor `imageTokens()` with
  gpt-4.1 tile and o-series rules to price snapcompact frames (#14286); a warn-once `Set` with a
  NUL-joined key carried across reloads (#14233); runtime validation of repo-owned KDL output
  (#14286); the same range validated in two modules (#14237); a 25-line hand-written glob checker
  (#14244).
- Side channels: `WeakMap<AbortSignal, string>` so another module can read a click-refusal reason
  (#14230); module `WeakSet` marking pinned settings objects (#14244).
- Provenance in comments: "Opus 5.5 / Fable 5.1 / Opus 4.7 billed +4,765 …" (#14286 KDL),
  "Measured without failures: 70 Opus frames / 12 MB …" (#14285), "CLI 3000.11.3" (#13656),
  "used to run …" test headers (#14291), "The darwin tests in browser-interactions.test.ts are the
  canary …" (#14225), 5-line JSDoc on a boolean field beside one-line siblings (#14228).
- Duplication inside our own stack: `tree-elide.ts` re-parses rows `observation.ts` already parses
  (#13692); `createSession` defined in two of our test files (#14291, #14285); a hand-rolled PNG
  header reader next to `parseImageMetadata` (#14291, flagged by roboomp).
- Tests: timing bounds `toBeGreaterThan(700)` (#14236); internals exported for tests (#14234
  `resolveEffectiveSettings`, #14230 `lastClickRefusal`); a seeded PRNG and 400-turn generator
  for a cap fix (#14277).
- Churn: unrelated reformat of `docs/tools/browser.md` (#14232); a 10-line maintainer comment
  reflowed to add one clause (#14234).

## What already matches (keep)

Long descriptive names, `#private`, early returns, named constants with units, numeric separators,
error messages that tell the user what to do, clean cutovers that delete the old path (#13677
src +70/−116), behavior-sentence test names, `test.each` tables, many-key `toEqual` integration
assertions (can1357 uses them too). Commit tense is not a signal: can1357 writes past tense ("kept"), H4vC
mostly imperative, and the PR title becomes the merge subject either way.
