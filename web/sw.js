const CACHE_NAME = 'reading-diary-v1';
const urlsToCache = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png'
];

// Install Event - Cache resources
self.addEventListener('install', event => {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[SW] Caching files');
        return cache.addAll(urlsToCache.map(url => {
          // Verwende relatives URL für bessere Kompatibilität
          return new Request(url, { mode: 'no-cors' });
        })).catch(err => {
          console.log('[SW] Cache error:', err);
          // Fallback: Cache nur die wichtigsten Dateien
          return cache.addAll(['/', '/static/style.css', '/static/app.js']);
        });
      })
      .then(() => {
        console.log('[SW] All files cached');
        self.skipWaiting();
      })
      .catch(err => {
        console.log('[SW] Install error:', err);
      })
  );
});

// Activate Event - Clean up old caches
self.addEventListener('activate', event => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[SW] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => {
      console.log('[SW] Activated');
      self.clients.claim();
    })
  );
});

// Fetch Event - Serve from cache with network fallback
self.addEventListener('fetch', event => {
  // Ignoriere Chrome-Extensions und andere Nicht-HTTP-Requests
  if (!event.request.url.startsWith('http')) {
    return;
  }

  // Ignoriere API-Requests für Live-Daten
  if (event.request.url.includes('/api/')) {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Cache hit - return response
        if (response) {
          console.log('[SW] Cache hit:', event.request.url);
          return response;
        }

        // Network request mit Fehlerbehandlung
        return fetch(event.request)
          .then(response => {
            // Prüfe ob es eine gültige Antwort ist
            if (!response || response.status !== 200 || response.type !== 'basic') {
              return response;
            }

            // Clone die Antwort für Cache
            const responseToCache = response.clone();

            caches.open(CACHE_NAME)
              .then(cache => {
                cache.put(event.request, responseToCache);
              })
              .catch(err => {
                console.log('[SW] Cache put error:', err);
              });

            return response;
          })
          .catch(err => {
            console.log('[SW] Fetch error:', err);
            
            // Fallback für HTML-Requests
            if (event.request.headers.get('accept').includes('text/html')) {
              return caches.match('/');
            }
            
            // Für andere Requests, gib einen leeren Response zurück
            return new Response('', {
              status: 200,
              statusText: 'OK',
              headers: { 'Content-Type': 'text/plain' }
            });
          });
      })
  );
});

// Message Event - Handle messages from main thread
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// Sync Event - Background sync (optional)
self.addEventListener('sync', event => {
  if (event.tag === 'background-sync') {
    event.waitUntil(
      // Hier können Sie Background-Sync-Logik hinzufügen
      Promise.resolve()
    );
  }
});

// Push Event - Push notifications (optional)
self.addEventListener('push', event => {
  if (event.data) {
    const data = event.data.json();
    const options = {
      body: data.body,
      icon: '/static/icons/icon-192x192.png',
      badge: '/static/icons/icon-72x72.png',
      tag: 'reading-diary-notification'
    };

    event.waitUntil(
      self.registration.showNotification(data.title, options)
    );
  }
});

// Notification Click Event
self.addEventListener('notificationclick', event => {
  event.notification.close();

  event.waitUntil(
    clients.openWindow('/')
  );
});

console.log('[SW] Service Worker loaded');
