const CACHE_NAME = "dharma-thuis-shell-v1";
const CACHE_PREFIX = "dharma-thuis-shell-";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.add("/offline.html")));
});

self.addEventListener("activate", (event) => event.waitUntil(
  caches.keys().then((names) => Promise.all(
    names.filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
      .map((name) => caches.delete(name))
  ))
));

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request, { cache: "no-store" })
      .catch(() => caches.match("/offline.html"))
  );
});
