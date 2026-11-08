// SDI Brief Lite - installable app shell. Live data is never cached.
const SHELL = "sdi-live-v5";   // 8 Nov 2026: renamed SDI Live, new icons
self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(["/pwa/icon-192.png", "/pwa/icon-512.png"]))); self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api") || u.pathname.startsWith("/file")) return;   // always live
  if (u.pathname === "/") {   // the page: network first, the last copy only if the phone is offline
    e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(SHELL).then(s => s.put(e.request, c)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  if (u.pathname.startsWith("/pwa/") || u.pathname === "/logo.png")
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
