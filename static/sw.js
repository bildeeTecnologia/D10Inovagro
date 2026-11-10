const CACHE = 'fechamento-campo-v15';
const ASSETS = ['/static/app.css?v=d10-pwa-mobile-3', '/static/field-app.js', '/static/manifest.json?v=d10-pwa-3', '/static/images/inovagro-logo.jpg', '/static/images/pwa-icon-180.png?v=d10-pwa-3', '/static/images/pwa-icon-192.png?v=d10-pwa-3', '/static/images/pwa-icon-512.png?v=d10-pwa-3', '/static/images/pwa-icon-512-maskable.png?v=d10-pwa-3'];
const OFFLINE_PAGE = '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sem conexão — D10 Agro</title><body style="font:16px system-ui,sans-serif;max-width:36rem;margin:12vh auto;padding:1.5rem;color:#17352c"><h1>Você está sem conexão</h1><p>Para proteger os dados e abrir a conta correta, reconecte-se à internet e tente abrir o D10 Agro novamente.</p><p>Se o app já estava aberto quando a conexão caiu, você pode continuar registrando; os lançamentos ficam na fila deste aparelho para sincronização posterior.</p></body></html>';
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('fechamento-campo-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const request = event.request;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => new Response(OFFLINE_PAGE, {
      status: 503,
      headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
    })));
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/static/')) {
    event.respondWith(fetch(request));
    return;
  }
  event.respondWith(caches.open(CACHE).then(async cache => {
    const cached = await cache.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  }));
});
