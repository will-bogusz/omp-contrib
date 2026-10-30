# Sources for the #15105 decision flow

PR head `5946e0375784c49dabc3b5cdcc33c7892444a431` (checked 2026-10-15). Read with
`git -C <your oh-my-pi checkout> show 5946e037:<path>`. Paths are under
`packages/coding-agent/src/tools/browser/` unless noted; "main" is the merge base `3a335e71`.
Body = the live PR body on 2026-10-15 (its What table moves into `<details>` under the figure).

| On the figure (`chart.mjs`) | Code at head | Body |
|---|---|---|
| `TITLE`: after an omp upgrade the relay updates its Chrome extension itself once nothing is using it | `relay/bridge.ts` `RelayBridge#maybeUpdateExtension` | What ¶2 ("the relay rewrites the extension and has it reload itself once nothing is using it") |
| `START`: the old extension says hello to the relay | `relay/bridge.ts` hello handler logs "extension connected", then `#maybeUpdateExtension(inst)`; re-run for every extension from `#updateIdleExtensions` when the last CDP client closes (`cdpClosed`, `#conns.size === 0`) | Reading order ("runs on each hello and when the last CDP client closes") |
| `STEPS[0]` "Does the extension speak the relay protocol?" no → every open fails "extension is out of date", main and this PR | `relay/probe.ts` `waitForRelayExtension`: `ompExtensionDiscardedTabsProtocol` missing or different → `"outdated-extension"`; `registry.ts` throws "The OMP Browser Relay extension is out of date. …" (same message on main, `registry.ts`:310 at `3a335e71`) | table row 4 ("without the relay protocol: fails 'out of date' / unchanged") |
| `STEPS[1]` fork, main: the old extension keeps running, silently, until you reinstall it and click Reload | main has no self-update and no notice (both added by this PR: `#maybeUpdateExtension`, `relayExtensionNotice`) | table main column rows 1–3 ("old one runs silently", "same"); What ¶3 |
| `STEPS[2]` "Was it installed by an omp with this change, so it can reload itself?" no → note | `relay/bridge.ts` `#outdatedReloadable`: `info.reloadProtocol !== EXTENSION_RELOAD_PROTOCOL_VERSION` → null; `extension/background.ts` hello carries `reloadProtocol: 1`. The same function also needs the stamp to be an omp version older than this relay's (`START`'s "still from the older omp") and a Chrome id from the socket's `Origin` (`relay/server.ts` `EXTENSION_ORIGIN`; Chrome always sends it, not drawn) | table row 3 ("installed before this change") |
| `STEPS[3]` "Has the relay already reloaded it once from this version, in this browser?" yes → note | `relay/bridge.ts` `#outdatedReloadable`: `#updateTried.get(inst.instanceId)?.has(ompVersion)` → null; `#updateTried` is filled just before `{ t: "reload" }` is sent. One set per extension instance (browser profile), held in the relay's memory | table row 3 ("already reloaded once from that version"); Why ("One reload per browser and version") |
| `STEPS[4]` "Is it loaded from omp's install folder, and are the files there not from a newer omp?" no → note | `relay/server.ts` `extensionUpdaterFor`: `unpackedExtensionId(dir) !== extensionId` → false; `isOlderOmpVersion(VERSION, installedRelayExtensionVersion(dir))` → false; `dir` = `defaultRelayExtensionDir()` (`~/.omp/browser-relay/extension`). A false result ends in `#maybeUpdateExtension` as "extension update stopped", reason "files not rewritten" | table row 3 ("loaded from another folder", "its folder holding a newer omp's files"); table row 1 (the folder) |
| `SHARED` left alone, with a note: it still works; every open adds "out of date, run omp browser-relay install and reload it in Chrome" | `relay/probe.ts` `relayExtensionNotice` ("The OMP Browser Relay extension is out of date (installed by …). " + `UPDATE_RELAY_EXTENSION` = "Run `omp browser-relay install` and reload the extension in Chrome."); `tools/browser.ts` `openOnKind` appends it; it reads `/json/version`'s `ompExtensionVersion`, which `RelayBridge.versionInfo` sets to the oldest connected extension | table row 3 (the note's text); Why ("a note, not an error: the extension still works") |
| `STEPS[5]` "Is any CDP client connected (an omp browser session, a puppeteer script), or a tab attached?" yes → waits: opens carry the note meanwhile; asks again when the last client leaves | `relay/bridge.ts` `#reloadBlocker`: `#conns.size > 0` → "CDP clients connected"; any of the extension's tabs `attached`, `attaching` or `detaching` → "tabs attached"; logged "extension update deferred". Asks again from `cdpClosed` → `#updateIdleExtensions` (after pending detaches settle) and on the next hello. The note shows meanwhile because the extension still reports its old stamp | table row 2 ("any CDP client connected or a tab attached: opens carry the note below; updates when the last client leaves"); Testing ("two CDP clients holding a puppeteer tab: update deferred … CDP clients connected") |
| `END` updates, no clicks: omp rewrites the files; if still nothing uses it, the extension reloads itself and reconnects on the new omp; no note | `extensionUpdaterFor` → `writeRelayExtension(dir, VERSION)` → true; `#maybeUpdateExtension` re-checks `#reloadBlocker` ("A client may have connected or a tab attached while the files were written") and sends `{ t: "reload" }`, logged "extension reloading into update"; `extension/background.ts` calls `chrome.runtime.reload()` | table row 1 ("files rewritten, extension reloads and reconnects on the new version, no clicks"); Testing ("back on the new version … no note") |
| `FOOT`: the relay asks about clients and tabs before the folder, and again after the rewrite | Order in `#maybeUpdateExtension`: `#outdatedReloadable` (installed by this change, older stamp, not tried) → `#reloadBlocker` → updater (folder, newer files) → `#reloadBlocker` again → reload | Why ("checks again after the write") |

## Drawn order vs code order

The figure asks: protocol → (fork) → installed by this change → already reloaded once → folder and newer
files → clients or tabs → update. The code asks clients-or-tabs before the folder, and again after
writing. Outcomes are the same: a busy extension loaded from another folder waits with the note, then,
once idle, is left with the note ("files not rewritten"); one that becomes busy during the write stops
with the note and is tried again when the last client leaves (`#updateTried` is only set when the reload
is sent). The footer says so.

## Simplifications

- "CDP client" covers every downstream CDP connection to the relay: omp's own browser sessions (their
  long-lived registry connection holds sessions on every tab, `cdpClosed` comment) and puppeteer scripts.
- `#updateTried` is per relay process: a restarted relay may try a version once more. Not drawn.
- An extension whose stamp is not an omp version (`isOmpVersion`) is never updated; not drawn (the
  start box assumes an older omp's stamp).
