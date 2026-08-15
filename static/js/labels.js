(() => {
  let controller;
  let timer;
  let sequence = 0;
  function init() {
    const studio = document.querySelector("[data-label-studio]");
    if (!studio || studio.dataset.ready) return;
    studio.dataset.ready = "true";
    const form = studio.querySelector("[data-label-form]");
    const buildUrl = () => `${form.action || window.location.pathname}?${new URLSearchParams(new FormData(form))}`;
    async function refresh({full = false} = {}) {
      controller?.abort();
      controller = new AbortController();
      const current = ++sequence;
      const preview = studio.querySelector("[data-label-preview]");
      preview?.classList.add("is-loading");
      const timeout = window.setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(buildUrl(), {
          signal: controller.signal,
          headers: full ? {} : {"X-Requested-With": "XMLHttpRequest"},
        });
        const responseText = await response.text();
        if (!response.ok) {
          const detail = responseText.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 180);
          throw new Error(`Vorschau konnte nicht aktualisiert werden (HTTP ${response.status})${detail ? `: ${detail}` : "."}`);
        }
        const documentCopy = new DOMParser().parseFromString(responseText, "text/html");
        if (current !== sequence) return;
        if (full) {
          const replacement = documentCopy.querySelector("[data-label-studio]");
          if (!replacement) throw new Error("Die Serverantwort enthält kein Label-Studio.");
          studio.replaceWith(replacement);
          init();
        } else {
          const replacement = documentCopy.querySelector("[data-label-preview]");
          if (!replacement) throw new Error("Die Serverantwort enthält keine Etikettenvorschau.");
          studio.querySelector("[data-label-preview]").replaceWith(replacement);
        }
        window.history.replaceState({}, "", buildUrl());
      } catch (error) {
        if (error.name === "AbortError" && current !== sequence) return;
        const status = studio.querySelector("[data-label-status]");
        console.error("Label-Vorschau fehlgeschlagen", error);
        if (status) {
          status.replaceChildren();
          const notice = document.createElement("div");
          notice.className = "label-preview-error";
          notice.append(document.createTextNode(error.message || "Vorschau konnte nicht aktualisiert werden."));
          const retry = document.createElement("button");
          retry.type = "button";
          retry.dataset.labelRetry = "true";
          retry.textContent = "Erneut versuchen";
          notice.append(" ", retry);
          status.append(notice);
        }
        studio.querySelector("[data-label-retry]")?.addEventListener("click", () => refresh());
      } finally {
        window.clearTimeout(timeout);
        if (current === sequence) studio.querySelector("[data-label-preview]")?.classList.remove("is-loading");
      }
    }
    form.addEventListener("change", (event) => {
      window.clearTimeout(timer);
      refresh({full: event.target.name === "type"});
    });
    form.querySelectorAll("[data-label-search],[data-label-text]").forEach((input) => input.addEventListener("input", () => {
      window.clearTimeout(timer); timer = window.setTimeout(() => refresh(), 180);
    }));
    const selectAll = document.querySelector("[data-label-select-all]");
    if (selectAll && !selectAll.dataset.labelsReady) {
      selectAll.dataset.labelsReady = "true";
      selectAll.addEventListener("click", () => {
        const activeStudio = document.querySelector("[data-label-studio]");
        activeStudio?.querySelectorAll('input[name="item"]').forEach((item) => { item.checked = true; });
        activeStudio?.querySelector("[data-label-form]")?.dispatchEvent(new Event("change", {bubbles: true}));
      });
    }
    form.querySelector("[data-label-select-none]")?.addEventListener("click", () => { form.querySelectorAll('input[name="item"]').forEach((item) => { item.checked = false; }); refresh(); });
  }
  init();
})();
