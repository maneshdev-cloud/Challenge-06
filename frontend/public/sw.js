const CACHE_VERSION = "prana-ai-shell-v2";
const PRECACHE_URLS = [
  "/",
  "/index.html",
  "/manifest.json",
  "/icons/icon-180.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(PRECACHE_URLS)).catch(() => { })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Bypass API endpoints so dynamic air/plan/chat/audit responses are never served stale
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/v1/")) {
    return;
  }

  // Navigation requests: network-first with cached shell fallback
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          if (resp && resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE_VERSION).then((c) => c.put("/", clone)).catch(() => {});
          }
          return resp;
        })
        .catch(() => caches.match("/index.html").then((cached) => cached || caches.match("/")))
    );
    return;
  }

  // Static shell assets: stale-while-revalidate for instant mobile opens
  if (
    url.pathname.startsWith("/assets/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname === "/manifest.json"
  ) {
    event.respondWith(
      caches.open(CACHE_VERSION).then((cache) =>
        cache.match(request).then((cached) => {
          const networkPromise = fetch(request)
            .then((resp) => {
              if (resp && resp.ok) cache.put(request, resp.clone());
              return resp;
            })
            .catch(() => cached);
          return cached || networkPromise;
        })
      )
    );
  }
});
