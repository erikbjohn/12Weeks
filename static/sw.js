const CACHE_NAME = '12weeks-v4';
const STATIC_ASSETS = [
  '/',
  '/static/style.css?v=61',
  '/static/app.js?v=61',
  '/static/manifest.json',
];
const DATA_CACHE = '12weeks-data-v3';

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

// Background sync for offline POST requests
self.addEventListener('sync', (e) => {
  if (e.tag === 'sync-posts') {
    e.waitUntil(replayQueuedPosts());
  }
});

async function replayQueuedPosts() {
  const db = await openSyncDB();
  const tx = db.transaction('outbox', 'readwrite');
  const store = tx.objectStore('outbox');
  const all = await storeGetAll(store);

  for (const item of all) {
    try {
      const res = await fetch(item.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: item.body,
        credentials: 'same-origin',
      });
      if (res.ok) {
        store.delete(item.id);
      } else if (res.status === 401) {
        break; // Session expired, stop retrying until re-auth
      } else {
        break; // Server error, retry later
      }
    } catch (e) {
      break; // Network error, retry later
    }
  }
}

function openSyncDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('12weeks-sync', 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function storeGetAll(store) {
  return new Promise((resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

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
