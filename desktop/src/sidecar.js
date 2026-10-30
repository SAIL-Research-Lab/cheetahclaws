'use strict';

// Sidecar manager — launch the existing `cheetahclaws --web` server as a
// child process, discover the port it bound, and own its lifecycle.
//
// Deliberately framework-agnostic (plain Node, no Electron import) so it can
// be unit-smoke-tested without a GUI, and so the exact same logic can be
// lifted into a Tauri (Rust) shell later — only the window code differs.

const { spawn } = require('child_process');
const readline = require('readline');

// The server prints its ready line to stdout with an explicit flush, e.g.:
//   Chat UI:  http://localhost:8771/chat?token=AbC123...
// We treat the appearance of that URL as the readiness signal and pull the
// port straight out of it (the server may auto-pick a free port).
//
// With --no-auth the server still requires a random per-launch token (so
// other websites open in the user's browser can't drive the local server);
// it's printed in the same line. We hand it to the window URL; the server
// swaps it for an HttpOnly cookie and redirects to the clean /chat URL.
// Older servers print no token — then the group is simply undefined.
const READY_RE = /https?:\/\/(?:localhost|127\.0\.0\.1):(\d+)\/chat(?:\?token=([A-Za-z0-9_-]+))?/i;

/**
 * Start the CheetahClaws web server as a sidecar.
 * Resolves once the server is listening, with { child, port, token, url, stop }.
 * `url` already carries the launch token when the server printed one.
 *
 * @param {object} [opts]
 * @param {string} [opts.command]  Executable to run (default: $CHEETAHCLAWS_BIN or "cheetahclaws").
 * @param {string[]} [opts.args]   Args (default: --web --no-auth --host 127.0.0.1).
 * @param {string} [opts.host]     Host to build the URL with (default: 127.0.0.1).
 * @param {number} [opts.readyTimeoutMs]  How long to wait for the ready line (default: 30000).
 * @param {(line:string)=>void} [opts.onLog]  Called for every server log line.
 */
function startSidecar(opts = {}) {
  const {
    command = process.env.CHEETAHCLAWS_BIN || 'cheetahclaws',
    args = ['--web', '--no-auth', '--host', '127.0.0.1'],
    host = '127.0.0.1',
    readyTimeoutMs = 30000,
    onLog = () => {},
  } = opts;

  return new Promise((resolve, reject) => {
    // The server refuses to boot when CHEETAHCLAWS_WEB_SERVER=1 (its recursion
    // guard against `alias cheetahclaws='cheetahclaws --web'`). Hand the child
    // a clean env so a shell alias can't make the desktop app fail to launch.
    const env = { ...process.env };
    delete env.CHEETAHCLAWS_WEB_SERVER;

    let child;
    try {
      child = spawn(command, args, {
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,   // don't flash a console window on Windows
      });
    } catch (err) {
      return reject(new Error(`failed to launch "${command}": ${err.message}`));
    }

    let settled = false;

    const timer = setTimeout(() => {
      fail(new Error(`server did not become ready within ${readyTimeoutMs}ms`));
    }, readyTimeoutMs);

    function fail(err) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { child.kill('SIGKILL'); } catch (_) { /* already gone */ }
      reject(err);
    }

    function succeed(port, token) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const query = token ? `?token=${encodeURIComponent(token)}` : '';
      resolve({
        child,
        port,
        token: token || null,
        url: `http://${host}:${port}/chat${query}`,
        stop: () => stopChild(child),
      });
    }

    function scan(line) {
      // Don't echo the launch token into logs.
      onLog(line.replace(/([?&]token=)[A-Za-z0-9_-]+/g, '$1***'));
      const m = READY_RE.exec(line);
      if (m) succeed(Number(m[1]), m[2]);
    }

    // The ready line goes to stdout, but watch stderr too in case logging is
    // reconfigured — either way we only act on the chat-URL pattern.
    readline.createInterface({ input: child.stdout }).on('line', scan);
    readline.createInterface({ input: child.stderr }).on('line', scan);

    child.on('error', (err) =>
      fail(new Error(`failed to launch "${command}": ${err.message}`)));
    child.on('exit', (code, signal) =>
      fail(new Error(`server exited before becoming ready (code=${code}, signal=${signal})`)));
  });
}

/**
 * Stop a sidecar child gracefully (SIGTERM, then SIGKILL after a grace
 * period). Resolves once the process is gone. Safe to call more than once.
 */
function stopChild(child) {
  return new Promise((resolve) => {
    if (!child || child.exitCode !== null || child.signalCode) return resolve();

    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };

    child.once('exit', finish);
    try {
      child.kill('SIGTERM');
    } catch (_) {
      return finish();
    }

    // Escalate if it doesn't shut down promptly.
    const kill = setTimeout(() => {
      if (!done) { try { child.kill('SIGKILL'); } catch (_) { /* gone */ } }
    }, 3000);
    if (kill.unref) kill.unref();
  });
}

module.exports = { startSidecar, stopChild, READY_RE };
