"use strict";
const root = document.documentElement;
const savedTheme = localStorage.getItem("brickmissing-theme");
if (savedTheme === "light" || savedTheme === "dark") root.dataset.theme = savedTheme;
document.getElementById("theme-toggle")?.addEventListener("click", () => {
  root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("brickmissing-theme", root.dataset.theme);
});
document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
document.querySelectorAll("[data-print-page]").forEach((button) => {
  button.addEventListener("click", () => window.print());
});
document.querySelectorAll("a[data-history-back]").forEach((link) => {
  link.addEventListener("click", (event) => {
    if (window.history.length <= 1) return;
    event.preventDefault();
    window.history.back();
  });
});
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
}
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    const field = document.getElementById("global-search");
    if (field) field.focus(); else window.location.assign("/suche/");
  }
});
