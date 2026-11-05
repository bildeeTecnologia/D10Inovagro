const CACHE = 'fechamento-campo-v11';
const ASSETS = ['/static/app.css?v=d10-pwa-mobile-2', '/static/field-app.js', '/static/manifest.json?v=d10-pwa-2', '/static/images/inovagro-logo.jpg', '/static/images/pwa-icon-180.png?v=d10-pwa-2', '/static/images/pwa-icon-192.png?v=d10-pwa-2', '/static/images/pwa-icon-512.png?v=d10-pwa-2', '/static/images/pwa-icon-512-maskable.png?v=d10-pwa-2'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('fechamento-campo-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const request = event.request;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then(response => {
      const clone = response.clone();
      caches.open(CACHE).then(cache => cache.put(request, clone));
      return response;
    }).catch(() => caches.match(request).then(cached => cached || caches.match('/campo/'))));
    return;
  }
  event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
    if (response.ok && new URL(request.url).origin === self.location.origin) {
      const clone = response.clone();
      caches.open(CACHE).then(cache => cache.put(request, clone));
    }
    return response;
  })));
});
