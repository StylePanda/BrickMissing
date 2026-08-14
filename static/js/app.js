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

const setForm = document.querySelector("form[data-set-lookup-url]");
if (setForm) {
  const numberField = setForm.querySelector('[name="set_number"]');
  const status = document.getElementById("set-lookup-status");
  const mappedFields = ["name", "theme", "subtheme", "year", "total_parts", "minifigures", "image_url"];
  let timer;
  let controller;
  let lastNumber = "";
  mappedFields.forEach((name) => {
    const field = setForm.elements[name];
    if (field?.value && field.value !== "0") field.dataset.userEdited = "true";
    field?.addEventListener("input", (event) => { event.currentTarget.dataset.userEdited = "true"; });
  });
  numberField?.addEventListener("input", () => {
    window.clearTimeout(timer);
    const number = numberField.value.trim();
    if (number.length < 3 || number === lastNumber) return;
    timer = window.setTimeout(async () => {
      controller?.abort();
      controller = new AbortController();
      status.textContent = "Lade Setinformationen von Rebrickable …";
      status.className = "lookup-status muted is-loading-text";
      try {
        const url = new URL(setForm.dataset.setLookupUrl, window.location.origin);
        url.searchParams.set("set_number", number);
        const response = await fetch(url, {headers: {"Accept": "application/json"}, signal: controller.signal});
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.message || "Setinformationen konnten nicht geladen werden.");
        if (payload.set.set_number && !number.includes("-")) numberField.value = payload.set.set_number;
        mappedFields.forEach((name) => {
          const field = setForm.elements[name];
          const value = payload.set[name];
          if (field && value !== null && value !== "" && (!field.dataset.userEdited || !field.value)) {
            field.value = value;
            field.dispatchEvent(new Event("change", {bubbles: true}));
          }
        });
        lastNumber = number;
        status.textContent = payload.message;
        status.className = "lookup-status good";
      } catch (error) {
        if (error.name === "AbortError") return;
        status.textContent = error.message || "Rebrickable ist momentan nicht erreichbar. Bitte versuche es später erneut.";
        status.className = "lookup-status warn";
      }
    }, 600);
  });
}

const lightbox = document.getElementById("image-lightbox");
if (lightbox) {
  const image = lightbox.querySelector("img");
  const title = document.getElementById("image-lightbox-title");
  const closeButton = lightbox.querySelector("[data-lightbox-close]");
  let opener;
  const close = () => lightbox.close();
  document.querySelectorAll("[data-lightbox-image]").forEach((button) => {
    button.addEventListener("click", () => {
      opener = button;
      image.src = button.dataset.lightboxImage;
      image.alt = button.dataset.lightboxTitle;
      title.textContent = button.dataset.lightboxTitle;
      lightbox.showModal();
      closeButton.focus();
    });
  });
  closeButton.addEventListener("click", close);
  lightbox.addEventListener("click", (event) => { if (event.target === lightbox) close(); });
  lightbox.addEventListener("close", () => {
    image.removeAttribute("src");
    opener?.focus();
  });
}
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
