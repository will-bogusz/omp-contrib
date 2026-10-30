## What

I had an extension from omp 18.6.1 still running under 18.8.7 for days without knowing, so now the extension knows which omp installed it and a relay open says when that's older than the omp you're running.

Every omp upgrade still left me running `omp browser-relay install` and clicking Reload in Chrome myself, so now the relay rewrites the extension and has it reload itself once nothing is using it.

Chrome never updates the relay extension, since it is loaded unpacked: after an omp upgrade the old one runs until it is reinstalled and reloaded, silently while it speaks the relay protocol.

| Extension in Chrome after an omp upgrade | main | this PR |
|---|---|---|
| loaded from `~/.omp/browser-relay/extension`, relay idle | old one runs silently | files rewritten, extension reloads and reconnects on the new version, no clicks |
| same, any CDP client connected or a tab attached | same | opens carry the note below; updates when the last client leaves |
| loaded from another folder, installed before this change, its folder holding a newer omp's files, or already reloaded once from that version | same | opens add `The OMP Browser Relay extension is out of date (installed by omp 18.6.1; this is omp 18.8.7). Run \`omp browser-relay install\` and reload the extension in Chrome.` |
| without the relay protocol | fails "out of date" | unchanged |

<details><summary>Reading order</summary>

- `omp browser-relay install` stamps the installing omp's version on the first line of `background.js` (`stampRelayExtensionScript`, `protocol.ts`) and in the manifest's `version_name`; the files it writes moved to `relay/extension-files.ts`, each renamed into place. `build-extension.ts` stamps the release zip the same way.
- `background.ts`: the hello carries the stamp as `ompVersion` and `reloadProtocol: 1`; a relay `{ t: "reload" }` calls `chrome.runtime.reload()`.
- `RelayBridge` (`bridge.ts`): `versionInfo` reports `ompExtensionVersion` on `/json/version`, the oldest connected extension, so a current browser cannot hide a stale one; `#maybeUpdateExtension` runs on each hello and when the last CDP client closes.
- `relay/server.ts`: the extension id comes from the `/ext` upgrade's `Origin`; `extensionUpdaterFor` writes, one call at a time, only when it is Chrome's id for the install folder and the files there are not from a newer omp.
- `relayExtensionNotice` (`relay/probe.ts`) reads the version; `openOnKind` appends the note.

</details>

## Why

- Reload, not restart: a restart re-reads `manifest.json` but keeps running the old service worker (branded Chrome 154 and 155); a reload re-reads the folder under the same id, keeping storage, permissions and the file-URL choice. For the same reason the stamp is read from the running script, not the manifest.
- A reload drops the extension's socket and debugger attachments, so it waits for no CDP client and no attached tab, and checks again after the write.
- Only the folder `install` owns, never over a newer omp's files, so two omps don't trade it back and forth. Atomic writes, the stamped script last: a reload that meets a half-written manifest unloads the extension behind an error dialog.
- One reload per browser and version; an extension that comes back unchanged keeps the note.
- Where it cannot update, a note, not an error: the extension still works. The note's read is one loopback request per open, before the tab is acquired, bounded by 2 s and the open's deadline.
- `version_name`, not `version`: Chrome requires dotted integers; canary versions aren't.
- Not the Web Store or an `update_url`: both need a listing or signed package someone maintains.

## Testing

- Unit tests on real relays, cases below; each self-update guard, removed, fails its test.
<details><summary>Unit test cases</summary>

- `browser-relay-self-update.test.ts`: which hellos update and which never do; waits for clients and attached tabs; nothing more reaches a browser asked to reload; once per version (A→B→A); real relay with files on disk: install folder rewritten, three profiles each reloaded, another folder and newer files left alone; Chromium's id fixtures (macOS/Linux and Windows). Removing any one guard fails its test.
- `relayExtensionNotice` on a real relay: current, older and unstamped extensions, a protocol-less hello, a relay without the field, stale plus current browsers in both orders, reconnects, non-version stamps, a read that outlives the deadline; `browser-open-lease` covers cancels during the read. `browser-relay-cli.test.ts` runs omp 18.6.1's installed `background.js` under this omp's manifest (a restart after a reinstall): the open notes 18.6.1. Reverting the bridge and install changes fails 3; using the last hello instead of the oldest fails 2.

</details>

- Live, branded Chrome 155 in a macOS VM, *Load unpacked* from `~/.omp/browser-relay/extension`, relays from this branch stamped 18.11.0 to 18.11.7:
  - restart without *Reload* after an install: files on disk say 18.11.1, the relay reports `"ompExtensionVersion":"18.11.0"` and the note.
  - extension from before the self-update: left alone, note shown; then one manual install and *Reload*.
  - new relay, nothing connected: `extension reloading into update`, back on the new version with the same instance id, file-URL toggle still off, no error in `chrome://extensions`; an open waiting on the relay got `ready` 459 ms later, no note.
  - two CDP clients holding a puppeteer tab: `update deferred … CDP clients connected`, the tab kept working; 0.5 s after they left, the extension was on the new version.
- `bun test` on `browser-relay-{probe,bridge,server,daemon,kind,debugger-ownership,self-update}`, `browser-open-lease` and `browser-relay-cli`: 140 pass. `bun check` (TS and Rust; Rust forced with `CI=1`, as CI runs it) passes on macOS; `check:ts` again after the last fix.

---

- [x] `bun check` passes
- [x] Tested locally
- [x] CHANGELOG updated with the required attribution (if user-facing; internal issue fixes use issue links, external contributions add the PR link and contributor credit after creation)

