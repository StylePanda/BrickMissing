"use strict";
const CACHE = "brickmissing-shell-v2";
const SHELL = [
  "/static/css/app.css",
  "/static/css/offline.css",
  "/static/js/app.js",
  "/static/manifest.webmanifest",
  "/static/offline.html",
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
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
  } else if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/static/offline.html")));
  }
});
