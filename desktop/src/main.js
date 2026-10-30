'use strict';

// CheetahClaws desktop shell (Electron).
//
// Architecture: this process owns a single BrowserWindow. On launch it shows a
// loading page, spawns the existing `cheetahclaws --web --no-auth` server as a
// localhost-only sidecar (see sidecar.js), then points the webview at that
// server's /chat URL — so the production-ready web UI *is* the desktop app, no
// reimplementation. The server is bound to 127.0.0.1 and runs as the local
// user (bring-your-own API key); nothing is exposed to the network.

const { app, BrowserWindow, dialog, shell } = require('electron');
const path = require('path');
const { startSidecar } = require('./sidecar');

let mainWindow = null;
let sidecar = null;

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

  // Show something immediately while the server boots (cold start is ~1s).
  await mainWindow.loadFile(path.join(__dirname, 'loading.html'));

  try {
    sidecar = await startSidecar({
      command: resolveServerCommand(),
      onLog: (line) => console.log('[cheetahclaws]', line),
    });
  } catch (err) {
    return showFatal(err);
  }
  // sidecar.url carries the per-launch access token; keep it out of logs.
  console.log('[desktop] server ready on port', sidecar.port);

  if (mainWindow && !mainWindow.isDestroyed()) {
    await mainWindow.loadURL(sidecar.url);
  }

  // If the server dies while the app is open, say so instead of going blank.
  sidecar.child.on('exit', (code, signal) => {
    if (app.isQuitting) return;
    showFatal(new Error(
      `The CheetahClaws server stopped unexpectedly (code=${code}, signal=${signal}).`));
  });
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

// Open target=_blank / external links in the system browser, never a new
// Electron window.
app.on('web-contents-created', (_e, contents) => {
  contents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) { shell.openExternal(url); return { action: 'deny' }; }
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

  app.whenReady().then(createWindow);

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
