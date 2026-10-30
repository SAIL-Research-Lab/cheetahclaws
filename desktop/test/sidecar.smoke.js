'use strict';

// Smoke test for the sidecar manager — no Electron, no GUI required.
// Launches the real `cheetahclaws --web --no-auth`, waits for readiness,
// checks the launch-token gate, hits the served endpoints, then shuts the
// server down.
//
//   node test/sidecar.smoke.js          (DEBUG=1 to echo server logs)
//
// Requires the `cheetahclaws` CLI on PATH with the web extra installed:
//   pip install 'cheetahclaws[web]'

const http = require('http');
const { startSidecar, stopChild } = require('../src/sidecar');

function get(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers }, (res) => {
      res.resume();
      resolve({ code: res.statusCode, headers: res.headers });
    });
    req.on('error', reject);
    req.setTimeout(5000, () => req.destroy(new Error('request timeout')));
  });
}

function expect(ep, got, want) {
  console.log(`   GET ${ep.padEnd(24)} -> ${got}`);
  if (got !== want) throw new Error(`expected ${want} for ${ep}, got ${got}`);
}

(async () => {
  console.log('→ starting sidecar: cheetahclaws --web --no-auth --host 127.0.0.1');
  const sc = await startSidecar({
    readyTimeoutMs: 30000,
    onLog: (l) => process.env.DEBUG && console.log('   |', l),
  });
  console.log(`→ ready on port ${sc.port} (launch token ${sc.token ? 'present' : 'MISSING'})`);

  try {
    const base = `http://127.0.0.1:${sc.port}`;
    if (!sc.token) throw new Error('server printed no launch token');
    expect('/health', (await get(`${base}/health`)).code, 200);
    // Without the launch token, pages are refused even in --no-auth mode.
    expect('/chat (no token)', (await get(`${base}/chat`)).code, 401);
    // With it: 302 to the clean URL + HttpOnly cookie, which then works.
    const r = await get(sc.url);
    expect('/chat?token=…', r.code, 302);
    const cookie = (r.headers['set-cookie'] || [])
      .map((c) => String(c).split(';')[0])
      .find((c) => c.startsWith('cclaunch='));
    if (!cookie) throw new Error('no launch cookie set');
    for (const ep of ['/chat', '/']) {
      expect(`${ep} (cookie)`, (await get(`${base}${ep}`, { Cookie: cookie })).code, 200);
    }
    console.log('✅ SMOKE PASS — shell can launch the server and reach the chat UI');
  } finally {
    await stopChild(sc.child);
    console.log('→ sidecar stopped');
  }
})().catch((err) => {
  console.error('❌ SMOKE FAIL —', err.message);
  process.exit(1);
});
