const CACHE_NAME = '12weeks-v141';
const STATIC_ASSETS = [
  '/',
  '/static/style.css?v=297',
  '/static/app.js?v=297',
  '/static/manifest.json',
];
const DATA_CACHE = '12weeks-data-v7';

// Install: cache static assets
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
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

  // HTML pages — ALWAYS network first so updates show immediately
  if (e.request.mode === 'navigate' || url.pathname === '/') {
    e.respondWith(
      fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Static workout data — cache with long TTL
  if (url.pathname === '/api/workouts' || url.pathname === '/api/warmups') {
    e.respondWith(
      caches.open(DATA_CACHE).then(cache =>
        fetch(e.request).then(res => {
          cache.put(e.request, res.clone());
          return res;
        }).catch(() => cache.match(e.request))
      )
    );
    return;
  }

  // Other API calls — network first, cache fallback
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(DATA_CACHE).then(cache => cache.put(e.request, clone));
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Static assets — cache first
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

// NOTE: the offline POST outbox is replayed by the PAGE (app.js
// replayOutbox), not here. This worker is never registered — index.html
// deliberately unregisters all service workers to prevent stale assets —
// so a 'sync'-event replay was dead code and queued sets were lost. Do not
// re-add a SW-side replay without removing the page-side one (both deleting
// from the same outbox can double-POST).

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
      data: { url: '/' },
    })
  );
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  e.waitUntil(
    clients.matchAll({ type: 'window' }).then(clientList => {
      for (const client of clientList) {
        if (client.url.includes('/') && 'focus' in client) return client.focus();
      }
      return clients.openWindow('/');
    })
  );
});
