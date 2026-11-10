'use strict';

// CheetahClaws desktop shell (Electron).
//
// Architecture: this process owns a single BrowserWindow. On launch it shows a
// loading page, spawns the existing `cheetahclaws --web --no-auth` server as a
// sidecar (see sidecar.js), then points the webview at that server's /chat
// URL — so the production-ready web UI *is* the desktop app, no
// reimplementation. The server runs as the local user (bring-your-own API
// key) and by default listens on 127.0.0.1 only.
//
// Phone access ("Connect Phone…" in the menu) restarts the server with
// --lan: it then also listens on the local network, on a fixed port so a
// paired phone keeps working across restarts, and only accepts devices that
// hold the persistent pairing token shown as a QR code on /pair.

const { app, BrowserWindow, Menu, dialog, shell } = require('electron');
const fs = require('fs');
const path = require('path');
const { startSidecar, stopChild } = require('./sidecar');

let mainWindow = null;
let pairWindow = null;
let sidecar = null;
let restarting = false;

const DEFAULT_PHONE_PORT = 47821;

// ── Persisted preferences (userData/settings.json) ─────────────────────────

function settingsPath() {
  return path.join(app.getPath('userData'), 'settings.json');
}

function loadSettings() {
  try {
    return { phoneAccess: false, phonePort: DEFAULT_PHONE_PORT,
      ...JSON.parse(fs.readFileSync(settingsPath(), 'utf8')) };
  } catch (_) {
    return { phoneAccess: false, phonePort: DEFAULT_PHONE_PORT };
  }
}

function saveSettings(s) {
  try {
    fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
    fs.writeFileSync(settingsPath(), JSON.stringify(s, null, 2));
  } catch (err) {
    console.error('[desktop] could not save settings:', err.message);
  }
}

let settings = null;

// ── Server sidecar ─────────────────────────────────────────────────────────

// Where to find the CheetahClaws server:
//   - $CHEETAHCLAWS_BIN wins (explicit override, handy for dev).
//   - A packaged app ships the PyInstaller-frozen server under Resources/server
//     (see build/extraResources) — no Python needed on the user's machine.
//   - In dev (npm start) we fall back to the pip-installed `cheetahclaws` CLI.
function resolveServerCommand() {
  if (process.env.CHEETAHCLAWS_BIN) return process.env.CHEETAHCLAWS_BIN;
  if (app.isPackaged) {
    const exe = process.platform === 'win32'
      ? 'cheetahclaws-server.exe' : 'cheetahclaws-server';
    return path.join(process.resourcesPath, 'server', exe);
  }
  return 'cheetahclaws';
}

async function launchServer() {
  const base = { command: resolveServerCommand(),
    onLog: (line) => console.log('[cheetahclaws]', line) };
  if (!settings.phoneAccess) {
    return startSidecar(base);
  }
  // Phone access: fixed port so paired phones find us again. If something
  // else holds that port, fall back to any free port (phones then need the
  // new QR code) rather than failing to start.
  const lanArgs = ['--web', '--no-auth', '--lan'];
  try {
    return await startSidecar({ ...base,
      args: [...lanArgs, '--port', String(settings.phonePort)] });
  } catch (err) {
    console.warn('[desktop] phone port busy, using a free port:', err.message);
    return startSidecar({ ...base, args: lanArgs });
  }
}

function watchServer(sc) {
  // If the server dies while the app is open, say so instead of going blank.
  sc.child.on('exit', (code, signal) => {
    if (app.isQuitting || restarting || sc !== sidecar) return;
    showFatal(new Error(
      `The CheetahClaws server stopped unexpectedly (code=${code}, signal=${signal}).`));
  });
}

function serverAlive() {
  return sidecar && sidecar.child && sidecar.child.exitCode === null
    && !sidecar.child.signalCode;
}

function serverOrigin() {
  return sidecar ? `http://127.0.0.1:${sidecar.port}` : null;
}

async function restartServer() {
  restarting = true;
  try {
    if (pairWindow && !pairWindow.isDestroyed()) pairWindow.close();
    if (mainWindow && !mainWindow.isDestroyed()) {
      await mainWindow.loadFile(path.join(__dirname, 'loading.html'));
    }
    if (sidecar) await stopChild(sidecar.child);
    sidecar = await launchServer();
    watchServer(sidecar);
    if (mainWindow && !mainWindow.isDestroyed()) await mainWindow.loadURL(sidecar.url);
  } catch (err) {
    showFatal(err);
  } finally {
    restarting = false;
  }
  buildMenu();
}

// ── Windows ────────────────────────────────────────────────────────────────

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 800,
    minWidth: 720,
    minHeight: 480,
    backgroundColor: '#0b0f14',
    title: 'CheetahClaws',
    autoHideMenuBar: true,
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    webPreferences: {
      // The window loads our own localhost server; keep Node out of the
      // renderer and isolate contexts (Electron security defaults).
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.on('closed', () => { mainWindow = null; });

  // macOS keeps the app (and server) alive with no windows; reopening just
  // needs a window, not a second server.
  if (serverAlive()) {
    await mainWindow.loadURL(sidecar.url);
    return;
  }

  // Show something immediately while the server boots (cold start is ~1s).
  await mainWindow.loadFile(path.join(__dirname, 'loading.html'));

  try {
    sidecar = await launchServer();
  } catch (err) {
    return showFatal(err);
  }
  watchServer(sidecar);
  // sidecar.url carries the per-launch access token; keep it out of logs.
  console.log('[desktop] server ready on port', sidecar.port,
    settings.phoneAccess ? '(phone access on)' : '');

  if (mainWindow && !mainWindow.isDestroyed()) {
    await mainWindow.loadURL(sidecar.url);
  }
  buildMenu();
}

function openPairWindow() {
  if (!serverAlive()) return;
  if (pairWindow && !pairWindow.isDestroyed()) {
    pairWindow.focus();
    return;
  }
  pairWindow = new BrowserWindow({
    width: 760,
    height: 820,
    title: 'Connect a phone',
    parent: process.platform === 'darwin' ? undefined : mainWindow || undefined,
    backgroundColor: '#0b0f14',
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  pairWindow.on('closed', () => { pairWindow = null; });
  // The token query is swapped for the same session cookie the main window
  // already holds; passing it keeps this window independent of load order.
  const q = sidecar.token ? `?token=${encodeURIComponent(sidecar.token)}` : '';
  pairWindow.loadURL(`${serverOrigin()}/pair${q}`);
}

async function connectPhone() {
  if (!settings.phoneAccess) {
    const { response } = await dialog.showMessageBox(mainWindow || undefined, {
      type: 'question',
      buttons: ['Turn On Phone Access', 'Cancel'],
      defaultId: 0,
      cancelId: 1,
      message: 'Use CheetahClaws from your phone?',
      detail: 'Your phone connects to the agent running on this computer. '
        + 'CheetahClaws will accept connections from your local network, but only '
        + 'from devices that scan the pairing QR code.\n\n'
        + 'Your computer may ask you to allow incoming connections — choose Allow.',
    });
    if (response !== 0) return;
    settings.phoneAccess = true;
    saveSettings(settings);
    await restartServer();
  }
  openPairWindow();
}

async function turnOffPhoneAccess() {
  if (!settings.phoneAccess) return;
  settings.phoneAccess = false;
  saveSettings(settings);
  await restartServer();
}

// ── Menu ───────────────────────────────────────────────────────────────────

function buildMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    { role: 'fileMenu' },
    { role: 'editMenu' },
    {
      label: 'Phone',
      submenu: [
        { label: 'Connect Phone…', accelerator: 'CmdOrCtrl+Shift+P',
          click: () => { connectPhone(); } },
        { label: 'Turn Off Phone Access', enabled: !!(settings && settings.phoneAccess),
          click: () => { turnOffPhoneAccess(); } },
      ],
    },
    { role: 'viewMenu' },
    { role: 'windowMenu' },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function showFatal(err) {
  console.error('[desktop] fatal:', err);
  const msg = String((err && err.message) || err);
  if (mainWindow && !mainWindow.isDestroyed()) {
    const html = `<!doctype html><html><head><meta charset="utf-8">
<style>
  html,body{height:100%;margin:0;background:#0b0f14;color:#e6edf3;
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{height:100%;display:flex;align-items:center;justify-content:center;padding:2rem}
  .card{max-width:560px}
  h1{font-size:18px;margin:0 0 .5rem}
  code{background:#161b22;padding:.15rem .4rem;border-radius:4px}
  p{color:#9aa5b1}
</style></head><body><div class="wrap"><div class="card">
  <h1>Couldn't start CheetahClaws</h1>
  <p>${escapeHtml(msg)}</p>
  <p>Make sure the CLI is installed and on your PATH:
     <code>pip install 'cheetahclaws[web]'</code></p>
</div></div></body></html>`;
    mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  } else {
    dialog.showErrorBox('CheetahClaws', msg);
    app.quit();
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Links: our own /pair page opens in an app window (it needs the session
// cookie the system browser doesn't have); other http(s) links go to the
// system browser; nothing ever gets a raw new Electron window.
app.on('web-contents-created', (_e, contents) => {
  contents.setWindowOpenHandler(({ url }) => {
    let u = null;
    try { u = new URL(url); } catch (_) { return { action: 'deny' }; }
    const origin = serverOrigin();
    if (origin && u.origin === origin && u.pathname === '/pair') {
      connectPhone();
      return { action: 'deny' };
    }
    if (u.protocol === 'http:' || u.protocol === 'https:') shell.openExternal(url);
    return { action: 'deny' };
  });
});

// Single instance — a second launch focuses the existing window.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    settings = loadSettings();
    buildMenu();
    return createWindow();
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });

  // Tear down the sidecar when the app quits (SIGTERM; the OS reaps it).
  app.on('before-quit', () => {
    app.isQuitting = true;
    if (sidecar && sidecar.child) {
      try { sidecar.child.kill('SIGTERM'); } catch (_) { /* already gone */ }
    }
  });
}
