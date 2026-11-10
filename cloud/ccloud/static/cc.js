// Shared helpers for the platform pages.
window.cc = {
  inApp: /CheetahClawsApp\//.test(navigator.userAgent),
  $: (id) => document.getElementById(id),
  async api(path, body) {
    const opts = body === undefined
      ? { credentials: 'same-origin' }
      : { method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const res = await fetch('/_cc/api/' + path, opts);
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) throw new Error(data.error || res.statusText || 'request failed');
    return data;
  },
  next(fallback) {
    const n = new URLSearchParams(location.search).get('next') || fallback;
    // Same-site paths only — never bounce to another origin.
    return /^\/(?!\/)/.test(n) ? n : fallback;
  },
  usd(x) {
    if (x === null || x === undefined) return '';
    // Whole cents → 2 decimals ($0.40); tiny amounts keep their precision ($0.0024).
    if (x === 0 || Math.abs(Math.round(x * 100) - x * 100) < 1e-9 || Math.abs(x) >= 1) return '$' + x.toFixed(2);
    return '$' + x.toFixed(6).replace(/0+$/, '');
  },
};
