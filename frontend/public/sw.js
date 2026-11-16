// Versnq Core service worker (step C2): makes the app installable and shows a friendly page
// when there is no connection. It never stores company data: API calls are never cached.
const CACHE = "versnq-shell-v1";
const OFFLINE = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return; // pages only; everything else goes to the network
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
