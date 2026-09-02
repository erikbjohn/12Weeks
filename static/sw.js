const CACHE_NAME = '12weeks-v142';
// '/' is deliberately NOT precached — it's the authenticated, per-user app
// shell. Caching it (and falling back to that cache offline) risked
// serving a previous user's page to a different user on a shared device
// once this worker went live. See the 'fetch' handler below.
// S147: no precache list — asset_url() hashes + a no-store index.html
// guarantee freshness; the old list pointed at three dead ?v=297 URLs.
const DATA_CACHE = '12weeks-data-v7';

// Install: cache static assets
self.addEventListener('install', (e) => {
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME && k !== DATA_CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Skip non-GET requests
  if (e.request.method !== 'GET') return;

  // HTML pages — network only, NEVER cached. This is the authenticated,
  // per-user app shell; caching it and serving that cache offline could
  // hand a different user's page to whoever is next on a shared device.
  // The offline fallback is a static, content-free message instead of a
  // cache lookup.
  if (e.request.mode === 'navigate' || url.pathname === '/') {
    e.respondWith(
      fetch(e.request).catch(() => new Response(
        '<!doctype html><meta charset="utf-8"><title>Offline</title>' +
        '<body style="font-family:system-ui,sans-serif;text-align:center;' +
        'padding:48px 16px;color:#333">You’re offline. Reconnect and ' +
        'reload to continue.</body>',
        { status: 503, headers: { 'Content-Type': 'text/html' } }
      ))
    );
    return;
  }

  // S144/S147: ONLY /api/workouts is worth an offline read. Every other
  // authenticated GET (doses, weigh-ins, chat history, export) used to be
  // persisted in CacheStorage on the device — and stale/error bodies too.
  if (url.pathname === '/api/workouts') {
    e.respondWith(
      caches.open(DATA_CACHE).then(cache =>
        fetch(e.request).then(res => {
          if (res.ok) cache.put(e.request, res.clone());
          return res;
        }).catch(() => cache.match(e.request))
      )
    );
    return;
  }
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Static assets — cache first
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

// NOTE: the offline POST outbox is replayed by the PAGE (app.js
// replayOutbox), not here. index.html now registers this worker (needed so
// push notifications keep working with the app closed), but it still
// clears CacheStorage on every load and there is still no 'sync'-event
// handler here — the page-side replay in app.js remains the only replay
// path. Do not add a SW-side replay without removing the page-side one
// (both deleting from the same outbox can double-POST).

// ─── PUSH NOTIFICATIONS ──────────────────────────────────────────────────
self.addEventListener('push', (e) => {
  let data = { title: '12 Weeks', body: 'Time to check in!' };
  try {
    data = e.data.json();
  } catch (err) {
    // Use defaults
  }
  e.waitUntil(
    self.registration.showNotification(data.title || '12 Weeks', {
      body: data.body || '',
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      tag: data.tag || 'general',
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window' }).then(clientList => {
      for (const client of clientList) {
        if ('focus' in client) { if ('navigate' in client && target !== '/') client.navigate(target); return client.focus(); }
      }
      return clients.openWindow(target);
    })
  );
});
