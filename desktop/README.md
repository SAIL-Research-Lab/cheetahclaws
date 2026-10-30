# CheetahClaws Desktop (P1 MVP)

A thin native-window shell around CheetahClaws' existing, production-ready web
UI. It launches `cheetahclaws --web --no-auth` as a localhost-only **sidecar**
and points a webview at its `/chat` page — so the browser UI (WebSocket
streaming chat, xterm terminal, permission approval, themes) *becomes* the
desktop app, with nothing reimplemented.

```
┌─ Desktop shell (Electron) ─────────────────────────────┐
│  loading.html  →  spawn `cheetahclaws --web --no-auth`  │
│                   (127.0.0.1, auto-picked free port)    │
│     ↓ parse the printed "Chat UI: …/chat?token=<T>"     │
│  BrowserWindow.loadURL(…:<port>/chat?token=<T>)         │
└─────────────────────────────────────────────────────────┘
```

The server binds to `127.0.0.1` only and runs as you, with your own API key —
no network exposure, no multi-tenancy. Binding to localhost is not enough on
its own (any website open in your browser can reach `127.0.0.1`), so even with
`--no-auth` the server requires a random per-launch token: it prints it in the
ready line, the sidecar passes it in the window URL, and the server swaps it
for an HttpOnly cookie. Cross-origin WebSocket/POST requests are also refused. This is the local, bring-your-own-key
model; the hard SaaS problems (sandboxing, billing) are deliberately out of
scope for P1.

## Status

- ✅ **Runs end-to-end on macOS** — the Electron shell launches the server,
  discovers its port, and loads the chat UI in a native window.
- ✅ **Sidecar integration verified** — `npm run smoke` launches the real
  server, discovers its port + launch token, and confirms `/health` serves,
  `/chat` is refused without the token, and `/chat`, `/` serve with it.
- ✅ **Self-contained server verified** — `scripts/build-server.sh` freezes the
  server with PyInstaller into a ~95 MB standalone binary that serves the full
  web UI with **no Python installed**; the sidecar drives it identically. So a
  packaged installer needs neither Node nor Python on the user's machine.
- ⛏️ **Remaining for a shippable installer:** code signing / notarization (see
  open items) — everything else is wired and tested.

## Prerequisites

- **Node.js 18+** and npm.
- The **`cheetahclaws` CLI on your PATH, with the web extra**:
  ```bash
  pip install 'cheetahclaws[web]'
  cheetahclaws --version    # should print a version
  ```
  (Point at a different binary with `CHEETAHCLAWS_BIN=/path/to/cheetahclaws`.)

## Run

```bash
cd desktop
npm install        # pulls Electron (~150 MB first time)
npm start          # opens the window
```

Verify just the sidecar wiring (no GUI, no Electron needed):

```bash
npm run smoke      # DEBUG=1 npm run smoke  to echo server logs
```

## Troubleshooting `npm install` / `npm start`

The Electron npm package only downloads its ~90 MB binary in a `postinstall`
script. On hardened-npm setups (`allow-scripts`), very new Node versions, or
slow/blocked networks, that step misbehaves. Symptoms and fixes:

- **`Electron failed to install correctly`** — the binary didn't download or
  `path.txt` wasn't written. First make sure the binary is present, using a
  China-friendly mirror:
  ```bash
  rm -rf node_modules/electron ~/Library/Caches/electron      # (Linux: ~/.cache/electron)
  ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
    npm install electron --foreground-scripts
  npm run fix-electron        # writes the correct path.txt
  npm start
  ```
- **`spawn .../dist/dist/Electron.app/... ENOENT` (double `dist`)** — `path.txt`
  has a stray `dist/` prefix. `npm run fix-electron` rewrites it correctly
  (Electron expects the path *relative to* `dist/`).
- **Extraction left a tiny/partial `dist/`** — download the full zip yourself
  from <https://npmmirror.com/mirrors/electron/> (match your platform + arch,
  e.g. `electron-vXX-darwin-arm64.zip`), unzip into `node_modules/electron/dist/`,
  then `npm run fix-electron`.
- **macOS "Electron is damaged / cannot be verified"** — clear the quarantine
  flag on the dev binary: `xattr -dr com.apple.quarantine node_modules/electron/dist/Electron.app`.
- **Node version** — Electron 31 is happiest on an LTS Node (18/20). Bleeding-edge
  Node has been seen to skip writing `path.txt`; `npm run fix-electron` papers
  over that, or use `nvm use 20`.

None of this affects **end users** — a packaged `.dmg`/`.exe`/`.AppImage`
(below) bundles Electron, so installers never hit the postinstall path.

## Build a self-contained installer (.dmg / .exe / .AppImage)

This produces an installer that bundles **both** Electron and a
PyInstaller-frozen copy of the server, so the **end user needs neither Node nor
Python** — they just double-click.

```bash
cd desktop
bash scripts/build-app.sh
# → out/  contains the .dmg (macOS) / .exe (Windows) / .AppImage (Linux)
```

What it does, in order:

1. **`scripts/build-server.sh`** — freezes `cheetahclaws --web` with PyInstaller
   in a *clean* virtualenv (only the core + `[web]` deps, so the bundle is
   ~95 MB, not GBs — the trading/voice/research stacks aren't installed and the
   modular loaders skip them gracefully). Output:
   `server/dist/cheetahclaws-server/`.
2. **`electron-builder`** (`npm run dist`) — packages the Electron shell and
   copies the frozen server into the app's `Resources/server/` (see
   `build.extraResources`). At runtime `src/main.js` spawns
   `Resources/server/cheetahclaws-server` when packaged, falling back to the
   global `cheetahclaws` CLI in dev.

> **PyInstaller does not cross-compile** — run `build-app.sh` *on each target
> OS*: a Mac to get the `.dmg`, Windows to get the `.exe`. (The whole server +
> sidecar pipeline is verified on Linux; only the per-OS packaging differs.)

## Known open items (next steps)

1. **Code signing + notarization.** macOS Gatekeeper / Windows SmartScreen will
   block an unsigned build (users get "damaged / unverified developer"). Needs
   an Apple Developer cert (`CSC_LINK`/`CSC_KEY_PASSWORD` + `notarize` in
   electron-builder) and a Windows code-signing cert. Paid prerequisite for
   public distribution — the only thing between `build-app.sh` and a
   shippable installer.
2. **First-run onboarding.** A GUI provider/API-key step (the CLI's setup
   wizard, as a screen) — the main lever for reaching non-CLI users.
3. **Auto-update.** Wire electron-updater (or Tauri's updater) so users don't
   stay pinned to old builds.
4. **Slim the server further (optional).** 95 MB is fine; if you want smaller,
   `strip`/UPX the binary or prune more stdlib via the spec's `excludes`.

## Why Electron here (and Tauri later)

This MVP is Electron because it only needs Node, which let the sidecar
integration be **actually run and verified** on the dev box (no Rust toolchain
was available). For the *shipped* product, **Tauri** is the better target — a
~5 MB Rust shell vs Electron's ~150 MB — and the sidecar logic in
[`src/sidecar.js`](src/sidecar.js) is intentionally framework-agnostic so it
ports across with only the window code rewritten.
