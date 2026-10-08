// Ancien service worker de l'application mobile : il se desinstalle et vide ses caches
// pour que les visiteurs voient toujours la derniere version du site.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) await caches.delete(k);
  await self.registration.unregister();
  for (const c of await self.clients.matchAll()) c.navigate(c.url);
})()));
