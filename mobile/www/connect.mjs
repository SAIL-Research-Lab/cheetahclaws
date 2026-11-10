// Pure helpers for the connect screen — no DOM, so `npm test` runs them in
// Node. The app pairs with the CheetahClaws server on the user's computer by
// the link shown (as a QR code) on that computer's /pair page:
//     http://192.168.1.20:47821/chat?token=<pairing token>
// We keep the origin + token; opening <origin>/chat?token=… signs the app in
// (the server swaps the token for a long-lived cookie).

const TOKEN_RE = /^[A-Za-z0-9_-]{16,256}$/;

/**
 * Parse whatever the user scanned or pasted.
 * Accepts a full pairing link, a bare "host:port", or a URL without a token
 * (password-mode servers — the user signs in on the page).
 * @returns {{origin:string, token:string|null, name:string}}
 * @throws Error with a user-facing message.
 */
export function parseLink(input) {
  let text = String(input || '').trim();
  if (!text) throw new Error('Paste the link from your computer first.');
  // A pasted message may wrap the link in other text — pull the URL out.
  const found = text.match(/https?:\/\/[^\s"'<>]+/i);
  if (found) text = found[0];
  else if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = 'http://' + text;

  let url;
  try {
    url = new URL(text);
  } catch (_) {
    throw new Error("That doesn't look like a CheetahClaws link.");
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('Only http:// and https:// links are supported.');
  }
  if (!url.hostname) throw new Error("That link has no computer address in it.");

  const raw = url.searchParams.get('token');
  const token = raw && TOKEN_RE.test(raw) ? raw : null;
  if (raw && !token) throw new Error('The pairing code in that link is damaged — copy it again.');
  return { origin: url.origin, token, name: url.host };
}

/** The URL the WebView opens to use a saved computer. */
export function chatUrl(computer) {
  const q = computer.token ? `?token=${encodeURIComponent(computer.token)}` : '';
  return `${computer.origin}/chat${q}`;
}

/** Insert or update (by origin), most recently used first. */
export function upsert(list, computer, now = Date.now()) {
  const rest = (list || []).filter((c) => c.origin !== computer.origin);
  const prev = (list || []).find((c) => c.origin === computer.origin) || {};
  return [{ ...prev, ...computer, name: computer.name || prev.name, lastUsed: now }, ...rest];
}

export function remove(list, origin) {
  return (list || []).filter((c) => c.origin !== origin);
}

/** URL of this app's own start page, to come back from a server page. */
export function appHomeUrl(userAgent) {
  return /Android/i.test(userAgent || '')
    ? 'https://localhost/?switch=1'
    : 'capacitor://localhost/?switch=1';
}
