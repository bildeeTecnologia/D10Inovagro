const CACHE = 'fechamento-campo-v8';
const ASSETS = ['/static/app.css?v=reports-visual-1', '/static/field-app.js', '/static/manifest.json', '/static/images/inovagro-logo.jpg', '/static/images/pwa-icon-192.png', '/static/images/pwa-icon-512.png', '/static/images/pwa-icon-512-maskable.png'];
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
