"use strict";
const root = document.documentElement;
const savedTheme = localStorage.getItem("brickmissing-theme");
if (savedTheme === "light" || savedTheme === "dark") root.dataset.theme = savedTheme;

document.getElementById("theme-toggle")?.addEventListener("click", () => {
  root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("brickmissing-theme", root.dataset.theme);
});

const navToggle = document.querySelector(".nav-toggle");
const mainNavigation = document.getElementById("main-navigation");
const closeNavigation = () => {
  mainNavigation?.classList.remove("is-open");
  navToggle?.setAttribute("aria-expanded", "false");
};
navToggle?.addEventListener("click", () => {
  const open = mainNavigation?.classList.toggle("is-open") ?? false;
  navToggle.setAttribute("aria-expanded", String(open));
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && mainNavigation?.classList.contains("is-open")) {
    closeNavigation();
    navToggle?.focus();
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    const field = document.getElementById("global-search");
    if (field) field.focus(); else window.location.assign("/suche/");
  }
});

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
document.querySelectorAll("[data-print-page]").forEach((button) => button.addEventListener("click", () => window.print()));
document.querySelectorAll("a[data-history-back]").forEach((link) => {
  link.addEventListener("click", (event) => {
    if (window.history.length <= 1) return;
    event.preventDefault();
    window.history.back();
  });
});
document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (event.defaultPrevented || !form.checkValidity()) return;
    const button = form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
    if (!button || button.classList.contains("is-loading")) return;
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
    window.setTimeout(() => { button.disabled = true; }, 0);
  });
});
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
