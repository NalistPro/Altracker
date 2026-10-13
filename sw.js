// Altracker — service worker
// Coquille de l'app : cache puis mise à jour en arrière-plan.
// Données (JSON) : réseau d'abord, cache en secours (mode hors ligne).
const V = 'altracker-v3';
const SHELL = ['./', 'index.html', 'manifest.json', 'icon.svg', 'icon-180.png', 'icon-192.png', 'icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(V)
      .then(c => Promise.allSettled(SHELL.map(u => c.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== V).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const isData = u =>
  u.hostname === 'raw.githubusercontent.com' ||
  u.pathname.includes('/data/') ||
  (u.pathname.endsWith('.json') && !u.pathname.endsWith('manifest.json'));

self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);

  if (isData(u)) {
    e.respondWith(
      fetch(r)
        .then(res => {
          if (res.ok) { const cp = res.clone(); caches.open(V).then(c => c.put(r, cp)); }
          return res;
        })
        .catch(() => caches.match(r))
    );
    return;
  }

  if (u.origin === location.origin) {
    e.respondWith(
      caches.match(r, { ignoreSearch: true }).then(hit => {
        const net = fetch(r)
          .then(res => {
            if (res.ok) { const cp = res.clone(); caches.open(V).then(c => c.put(r, cp)); }
            return res;
          })
          .catch(() => hit || caches.match('index.html'));
        return hit || net;
      })
    );
  }
});
