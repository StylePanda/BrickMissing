"use strict";
const CACHE = "brickmissing-shell-__BRICKMISSING_VERSION__";
const SHELL = [
  "/static/css/app.css?v=__BRICKMISSING_VERSION__",
  "/static/css/offline.css?v=__BRICKMISSING_VERSION__",
  "/static/js/app.js?v=__BRICKMISSING_VERSION__",
  "/static/manifest.webmanifest?v=__BRICKMISSING_VERSION__",
  "/static/offline.html?v=__BRICKMISSING_VERSION__",
  "/static/icons/brickmissing.svg",
  "/static/icons/favicon.ico",
  "/static/icons/apple-touch-icon.png",
];
self.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL))));
self.addEventListener("activate", (event) => event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(fetch(event.request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(event.request, copy));
      return response;
    }).catch(() => caches.match(event.request)));
  } else if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/static/offline.html?v=__BRICKMISSING_VERSION__")));
  }
});
