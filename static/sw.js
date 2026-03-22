// Reading Diary – Service Worker (PWA install only, no offline cache)
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});
// No fetch handler → no offline support
