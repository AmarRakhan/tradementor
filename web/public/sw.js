const CACHE_NAME = "amar-bot-shell-v46-build451";

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

self.addEventListener("push", (event) => {
  event.waitUntil((async () => {
    let payload = {};
    try {
      payload = event.data ? event.data.json() : {};
    } catch {
      payload = { title: "Melding", body: event.data ? event.data.text() : "" };
    }
    const title = String(payload.title || "Melding");
    const data = payload.data && typeof payload.data === "object" ? payload.data : {};
    await self.registration.showNotification(title, {
      body: String(payload.body || ""),
      icon: String(payload.icon || "/tradementor-icon-192.png"),
      badge: String(payload.badge || "/tradementor-icon-192.png"),
      tag: String(payload.tag || payload.eventId || "amar-crypto-bot"),
      renotify: false,
      data: { ...data, url: String(payload.url || data.url || "/"), notificationType: String(payload.type || "") },
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    const target = new URL(String(event.notification.data?.url || "/"), self.location.origin).href;
    const windows = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if ("focus" in client && new URL(client.url).origin === self.location.origin) {
        if ("navigate" in client && client.url !== target) await client.navigate(target);
        return client.focus();
      }
    }
    return clients.openWindow(target);
  })());
});
