// Connect screen for the CheetahClaws mobile app.
//
// The app is a thin shell: the agent runs on the user's computer, and the
// WebView simply navigates to that computer's chat UI. This page only keeps
// the list of paired computers and gets the user there.

import { parseLink, chatUrl, upsert, remove } from './connect.mjs';

const KEY = 'cc.computers';
const LAST = 'cc.last';                       // 'cloud' or a computer's origin
const CLOUD = String(window.CC_CLOUD_URL || '').replace(/\/+$/, '');
const $ = (id) => document.getElementById(id);
const Cap = window.Capacitor;

function load() {
  try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch (_) { return []; }
}
function save(list) {
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (_) { /* private mode */ }
}

// ── QR scanning (native plugin; hidden when unavailable) ───────────────────

function scanner() {
  if (!Cap || !Cap.isNativePlatform || !Cap.isNativePlatform()) return null;
  if (Cap.isPluginAvailable && !Cap.isPluginAvailable('CapacitorBarcodeScanner')) return null;
  if (Cap.registerPlugin) return Cap.registerPlugin('CapacitorBarcodeScanner');
  return (Cap.Plugins && Cap.Plugins.CapacitorBarcodeScanner) || null;
}

async function scan() {
  const s = scanner();
  if (!s) return;
  try {
    const res = await s.scanBarcode({
      hint: 0,                       // QR_CODE
      scanInstructions: 'Scan the QR code shown on your computer',
      scanButton: false,
      scanText: ' ',
      cameraDirection: 1,            // BACK
      scanOrientation: 3,            // ADAPTIVE
    });
    if (res && res.ScanResult) addFromText(res.ScanResult);
  } catch (err) {
    const msg = String((err && err.message) || err);
    if (!/cancel/i.test(msg)) $('add-err').textContent = msg;
  }
}

// ── Screens ────────────────────────────────────────────────────────────────

function show(screen) {
  $('home').hidden = screen !== 'home';
  $('add').hidden = screen !== 'add';
  if (screen === 'add') {
    $('add-err').textContent = '';
    $('link').value = '';
  }
}

function renderList() {
  const list = load();
  const el = $('list');
  el.innerHTML = '';
  if (!list.length) {
    const d = document.createElement('div');
    d.className = 'empty';
    d.textContent = 'No computers yet. Add one to get started.';
    el.appendChild(d);
    return;
  }
  for (const c of list) {
    const row = document.createElement('div');
    row.className = 'item';
    const main = document.createElement('button');
    main.className = 'main';
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = c.name;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = c.token ? 'Paired' : 'Sign in on connect';
    main.append(name, meta);
    main.onclick = () => connect(c);
    const del = document.createElement('button');
    del.className = 'del';
    del.setAttribute('aria-label', `Remove ${c.name}`);
    del.textContent = '×';
    del.onclick = () => {
      if (confirm(`Remove ${c.name}? You can pair it again any time.`)) {
        save(remove(load(), c.origin));
        renderList();
      }
    };
    row.append(main, del);
    el.appendChild(row);
  }
}

function addFromText(text) {
  let c;
  try {
    c = parseLink(text);
  } catch (err) {
    $('add-err').textContent = err.message;
    return;
  }
  save(upsert(load(), c));
  renderList();
  connect(c);
}

// ── Connecting ─────────────────────────────────────────────────────────────

let attempt = 0;

async function reachable(origin, ms = 5000) {
  // no-cors: we only learn "something answered" — enough to tell a dead
  // address from a live one without needing CORS on the server.
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    await fetch(`${origin}/health`, { mode: 'no-cors', cache: 'no-store', signal: ctl.signal });
    return true;
  } catch (_) {
    return false;
  } finally {
    clearTimeout(t);
  }
}

function remember(last) {
  try { localStorage.setItem(LAST, last); } catch (_) { /* private mode */ }
}

function go(c) {
  save(upsert(load(), c));
  remember(c.origin);
  window.location.href = chatUrl(c);
}

function goCloud() {
  remember('cloud');
  // /chat signs in first if needed, then wakes the user's cloud workspace.
  window.location.href = `${CLOUD}/chat`;
}

async function connect(c) {
  const my = ++attempt;
  $('connecting').classList.add('show');
  $('spinner').hidden = false;
  $('conn-text').textContent = `Connecting to ${c.name}…`;
  $('conn-err').textContent = '';
  $('conn-retry').hidden = true;
  $('conn-retry').onclick = () => go(c);
  if (await reachable(c.origin)) {
    if (my === attempt) go(c);
    return;
  }
  if (my !== attempt) return;
  // The probe can fail where the page would still load (e.g. a WebView that
  // blocks the plain-http probe), so offer to go ahead regardless.
  $('spinner').hidden = true;
  $('conn-text').textContent = `Can't reach ${c.name}`;
  $('conn-err').textContent = 'Is CheetahClaws running on the computer with phone access on, '
    + 'and is this phone on the same Wi-Fi (or Tailscale)?';
  $('conn-retry').hidden = false;
}

function cancelConnect() {
  attempt++;
  $('connecting').classList.remove('show');
}

// ── Wire up ────────────────────────────────────────────────────────────────

$('add-btn').onclick = () => show('add');
$('cancel-add').onclick = () => show('home');
$('add-form').onsubmit = (e) => { e.preventDefault(); addFromText($('link').value); };
$('conn-cancel').onclick = cancelConnect;
if (scanner()) {
  $('scan-btn').hidden = false;
  $('or').hidden = false;
  $('scan-btn').onclick = scan;
}

if (CLOUD) {
  $('cloud').hidden = false;
  $('cloud-btn').onclick = goCloud;
  $('computers-title').textContent = 'Or use your own computer';
}

renderList();
const params = new URLSearchParams(location.search);
const list = load();
let last = null;
try { last = localStorage.getItem(LAST); } catch (_) { /* private mode */ }
// Straight back to where the user was last time, unless they came here from
// the chat page's "switch" button.
const resume = !params.has('switch');
if (CLOUD && resume && (last === 'cloud' || (!last && !list.length))) {
  show('home');
  if (last === 'cloud') goCloud();
} else if (!list.length) {
  show(CLOUD ? 'home' : 'add');
} else {
  show('home');
  const target = list.find((c) => c.origin === last) || list[0];
  if (resume) connect(target);
}
