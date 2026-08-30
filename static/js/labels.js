(() => {
  let controller;
  let timer;
  let sequence = 0;
  function setLoading(preview, loading) {
    if (!preview) return;
    preview.classList.toggle("is-loading", loading);
    preview.setAttribute("aria-busy", String(loading));
    const indicator = preview.querySelector("[data-label-loading]");
    if (indicator) indicator.hidden = !loading;
  }
  function waitForLabelImages() {
    const images = [...document.querySelectorAll("[data-label-preview] img")]
      .filter((image) => !image.complete);
    if (!images.length) return Promise.resolve();
    const settled = Promise.all(images.map((image) => new Promise((resolve) => {
      image.addEventListener("load", resolve, {once: true});
      image.addEventListener("error", resolve, {once: true});
    })));
    return Promise.race([
      settled,
      new Promise((resolve) => window.setTimeout(resolve, 3000)),
    ]);
  }
  function waitForPreviewUpdate() {
    if (document.querySelector("[data-label-preview]")?.getAttribute("aria-busy") !== "true") {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const started = Date.now();
      const poll = window.setInterval(() => {
        const busy = document.querySelector("[data-label-preview]")?.getAttribute("aria-busy");
        if (busy !== "true" || Date.now() - started >= 3000) {
          window.clearInterval(poll);
          resolve();
        }
      }, 50);
    });
  }
  function init() {
    const studio = document.querySelector("[data-label-studio]");
    if (!studio || studio.dataset.ready) return;
    studio.dataset.ready = "true";
    const form = studio.querySelector("[data-label-form]");
    const endpoint = form.action || window.location.pathname;
    function bindSelectionControls() {
      const search = form.querySelector("[data-label-search]");
      if (search && !search.dataset.labelsReady) {
        search.dataset.labelsReady = "true";
        search.addEventListener("input", () => {
          window.clearTimeout(timer);
          timer = window.setTimeout(() => refresh(), 180);
        });
      }
      const selectNone = form.querySelector("[data-label-select-none]");
      if (selectNone && !selectNone.dataset.labelsReady) {
        selectNone.dataset.labelsReady = "true";
        selectNone.addEventListener("click", () => {
          form.querySelectorAll('input[type="checkbox"][name="item"]').forEach((item) => { item.checked = false; });
          form.querySelectorAll("[data-label-preserved-item]").forEach((item) => item.remove());
          refresh();
        });
      }
    }
    function buildHistoryUrl(formData) {
      const url = new URL(window.location.pathname, window.location.origin);
      ["type", "q", "start", "images", "qr_target", "checked_text", "checked_count"]
        .forEach((name) => {
          const values = formData.getAll(name);
          const value = values.at(-1);
          if (value) url.searchParams.set(name, name === "q" ? value.slice(0, 100) : value);
        });
      return `${url.pathname}${url.search}`;
    }
    async function refresh({full = false} = {}) {
      controller?.abort();
      controller = new AbortController();
      const current = ++sequence;
      const preview = studio.querySelector("[data-label-preview]");
      setLoading(preview, true);
      const timeout = window.setTimeout(() => controller.abort(), 8000);
      try {
        const formData = new FormData(form);
        const response = await fetch(endpoint, {
          method: "POST",
          body: formData,
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
          const replacementState = documentCopy.querySelector("[data-label-selection-state]");
          const replacementPreview = documentCopy.querySelector("[data-label-preview]");
          if (!replacementState || !replacementPreview) throw new Error("Die Serverantwort enthält keine vollständige Studio-Aktualisierung.");
          const activeSearch = document.activeElement === form.querySelector("[data-label-search]");
          const selectionStart = activeSearch ? document.activeElement.selectionStart : null;
          const selectionEnd = activeSearch ? document.activeElement.selectionEnd : null;
          form.querySelector("[data-label-selection-state]").replaceWith(replacementState);
          studio.querySelector("[data-label-preview]").replaceWith(replacementPreview);
          bindSelectionControls();
          if (activeSearch) {
            const updatedSearch = form.querySelector("[data-label-search]");
            updatedSearch?.focus();
            if (selectionStart !== null && selectionEnd !== null) {
              updatedSearch?.setSelectionRange(selectionStart, selectionEnd);
            }
          }
        }
        window.history.replaceState({}, "", buildHistoryUrl(formData));
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
        if (current === sequence) {
          setLoading(document.querySelector("[data-label-preview]"), false);
        }
      }
    }
    form.addEventListener("change", (event) => {
      window.clearTimeout(timer);
      refresh({full: event.target.name === "type"});
    });
    form.querySelectorAll("[data-label-text]").forEach((input) => input.addEventListener("input", () => {
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
    bindSelectionControls();
    const printButton = document.querySelector("[data-label-print]");
    if (printButton && !printButton.dataset.labelsReady) {
      printButton.dataset.labelsReady = "true";
      printButton.addEventListener("click", async () => {
        const originalText = printButton.textContent;
        printButton.disabled = true;
        printButton.textContent = "Druck wird vorbereitet …";
        try {
          await waitForPreviewUpdate();
          await waitForLabelImages();
          window.print();
        } finally {
          printButton.textContent = originalText;
          printButton.disabled = false;
        }
      });
    }
  }
  init();
})();
