/* CheetahClaws service worker.
 *
 * Deliberately minimal: the app is a live connection to the agent running on
 * your computer, so nothing is served from cache while the network works
 * (no stale UI after an upgrade, no cached API data). The only job is to
 * make the home-screen app installable and to show a friendly "can't reach
 * your computer" page instead of the browser's error when it is offline.
 */
const CACHE = 'cc-shell-v1';
const OFFLINE_URL = '/offline.html';
const PRECACHE = [OFFLINE_URL, '/static/icons/icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Only page navigations get the offline fallback; everything else
  // (API calls, WebSockets, assets) goes straight to the network.
  if (req.mode !== 'navigate') return;
  event.respondWith(
    fetch(req).catch(() => caches.match(OFFLINE_URL))
  );
});
