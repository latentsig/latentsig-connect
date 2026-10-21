const CACHE_NAME = 'latentsig-shell-v1'
const SHELL = ['/index.html', '/manifest.webmanifest', '/icon.svg', '/logo.png']

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('latentsig-shell-') && key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim()))
})

self.addEventListener('fetch', event => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then(response => {
      if (response.ok) void caches.open(CACHE_NAME).then(cache => cache.put('/index.html', response.clone()))
      return response
    }).catch(async () => (await caches.match(request)) || (await caches.match('/index.html'))))
    return
  }
  if (['script', 'style', 'image', 'font'].includes(request.destination)) {
    event.respondWith(caches.open(CACHE_NAME).then(async cache => {
      try {
        const response = await fetch(request)
        if (response.ok) void cache.put(request, response.clone())
        return response
      } catch {
        const cached = await cache.match(request)
        if (cached) return cached
        throw new Error('Offline asset unavailable')
      }
    }))
  }
})
