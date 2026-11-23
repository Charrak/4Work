/* Service Worker: App-Shell offline, API-Lesezugriffe mit Netzwerk-zuerst + Cache-Fallback, Web-Push. */
const VERSION = "v2";
const SHELL = "shell-" + VERSION;
const API = "api-" + VERSION;
const SHELL_FILES = ["/", "/index.html", "/manifest.webmanifest", "/logo.png", "/icons/icon-192.png"];
// Diese Pfade werden nie zwischengespeichert (sensibel oder zustandsabhängig)
const NO_CACHE = [/^\/api\/auth\//, /^\/api\/admin\//, /^\/api\/ws/, /^\/api\/users\/\d+\/export/, /^\/api\/time\/status/, /^\/api\/reports\//, /^\/api\/documents/];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== API).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "clear-api-cache") event.waitUntil(caches.delete(API));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    if (NO_CACHE.some((re) => re.test(url.pathname))) return;
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(API).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() =>
          caches.match(req).then((hit) =>
            hit || new Response(JSON.stringify({ detail: "offline" }), { status: 503, headers: { "Content-Type": "application/json" } })
          )
        )
    );
    return;
  }

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/index.html")));
    return;
  }

  // Statische Dateien: Cache zuerst, sonst Netzwerk und merken
  event.respondWith(
    caches.match(req).then((hit) =>
      hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(SHELL).then((c) => c.put(req, copy)); }
        return res;
      })
    )
  );
});

self.addEventListener("push", (event) => {
  let data = { title: "Dienstplan", body: "" };
  try { data = event.data ? event.data.json() : data; } catch (e) { /* ignore */ }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, icon: "/icons/icon-192.png", badge: "/icons/icon-192.png",
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((list) => {
      for (const c of list) { if ("focus" in c) return c.focus(); }
      return self.clients.openWindow("/");
    })
  );
});
