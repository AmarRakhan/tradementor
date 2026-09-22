const CACHE_NAME = "amar-bot-shell-v46-stable-update-2";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.add("/offline.html")));
  // Deliberately do not call skipWaiting here. A newly downloaded worker must
  // never seize control of an already-running signed-in app during startup.
});

self.addEventListener("activate", (event) => event.waitUntil(
  caches.keys()
    .then((names) => Promise.all(
      names
        .filter((name) => name.startsWith("amar-bot-shell-") && name !== CACHE_NAME)
        .map((name) => caches.delete(name)),
    )),
));

self.addEventListener("message", (event) => {
  // Explicit user-driven update only. Activation does not take control of
  // the current document; it stays untouched until its next navigation.
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  if (event.request.url.includes("/api/")) return;
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request, { cache: "no-store" }).catch(() => caches.match("/offline.html")));
});
