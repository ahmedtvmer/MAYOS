/* Imported by the existing Workbox worker. Payloads contain only app routes. */
'use strict';

const pushRoutes = new Set([
  '/home', '/home?push=player', '/home?push=program', '/home?push=nutrition',
  '/coach/alerts?push=coach', '/coach/requests?push=coach',
  '/player-notifications?push=player', '/food-swap-requests?push=player',
]);

function pushTarget(route) {
  const safe = pushRoutes.has(route) ? route : '/home';
  return new URL(`.${safe}`, self.registration.scope).href;
}

// Store before display for at-most-once presentation, including sender timeouts
// after the push service accepted a request and concurrent deliveries.
async function firstPush(tag) {
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open('mayos-push-seen', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('seen');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('seen', 'readwrite');
      const store = tx.objectStore('seen');
      let fresh = false;
      const read = store.get(tag);
      read.onsuccess = () => {
        fresh = read.result === undefined;
        if (fresh) store.put(Date.now(), tag);
      };
      tx.oncomplete = () => resolve(fresh);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

self.addEventListener('push', event => {
  event.waitUntil((async () => {
    let payload;
    try { payload = event.data.json(); } catch (_) { return; }
    if (!payload || typeof payload.tag !== 'string' || typeof payload.body !== 'string') return;
    if (!(await firstPush(payload.tag))) return;
    await self.registration.showNotification('MAYOS', {
      body: payload.body, tag: payload.tag, renotify: false,
      icon: new URL('mayos-icon-192.png', self.registration.scope).href,
      data: {url: pushTarget(payload.url)},
    });
  })());
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    const supplied = event.notification.data && event.notification.data.url;
    const allowed = [...pushRoutes].map(pushTarget);
    const target = allowed.includes(supplied) ? supplied : pushTarget('/home');
    const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    for (const client of windows) {
      if (client.url.startsWith(self.registration.scope) && 'navigate' in client) {
        await client.navigate(target);
        await client.focus();
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
