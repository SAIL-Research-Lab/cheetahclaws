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

function getJson(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers }, (res) => {
      let data = '';
      res.on('data', (d) => { data += d; });
      res.on('end', () => {
        try { resolve({ code: res.statusCode, body: JSON.parse(data) }); }
        catch (e) { reject(e); }
      });
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
  } finally {
    await stopChild(sc.child);
    console.log('→ sidecar stopped');
  }

  // Phone access: what the desktop "Connect Phone…" menu launches.
  console.log('→ starting sidecar with phone access: --web --no-auth --lan');
  const lan = await startSidecar({
    args: ['--web', '--no-auth', '--lan'],
    readyTimeoutMs: 30000,
    onLog: (l) => process.env.DEBUG && console.log('   |', l),
  });
  try {
    const base = `http://127.0.0.1:${lan.port}`;
    const r = await get(`${base}/pair?token=${lan.token}`);
    expect('/pair?token=…', r.code, 302);
    const cookie = (r.headers['set-cookie'] || [])
      .map((c) => String(c).split(';')[0])
      .find((c) => c.startsWith('cclaunch='));
    expect('/pair (cookie)', (await get(`${base}/pair`, { Cookie: cookie })).code, 200);
    const info = await getJson(`${base}/api/pair/info`, { Cookie: cookie });
    expect('/api/pair/info', info.code, 200);
    if (!info.body.lan) throw new Error('pair info says LAN is off');
    console.log(`   phone links: ${info.body.urls.length} (${info.body.urls.map((u) => u.ip).join(', ') || 'no LAN address'})`);
    // A phone opening the pairing link gets in, and stays in (Max-Age cookie).
    for (const u of info.body.urls.slice(0, 1)) {
      const phone = await get(u.url);
      expect('phone pairing link', phone.code, 302);
      const pc = (phone.headers['set-cookie'] || []).find((c) => String(c).startsWith('cclaunch='));
      if (!/Max-Age=\d+/.test(String(pc))) throw new Error('pairing cookie is not persistent');
      const host = new URL(u.url).origin;
      expect('phone /chat (cookie)', (await get(`${host}/chat`, { Cookie: String(pc).split(';')[0] })).code, 200);
    }
  } finally {
    await stopChild(lan.child);
    console.log('→ sidecar stopped');
  }
  console.log('✅ SMOKE PASS — shell can launch the server, reach the chat UI, and pair a phone');
})().catch((err) => {
  console.error('❌ SMOKE FAIL —', err.message);
  process.exit(1);
});
