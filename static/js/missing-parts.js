(() => {
  "use strict";
  document.querySelectorAll(".status-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.dataset.saving === "true") return;
      const allocation = form.closest("[data-part-allocation]");
      const button = form.querySelector("button");
      const select = form.querySelector('select[name="status"]');
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 15000);
      let errorMessage = "Status konnte nicht gespeichert werden.";
      form.dataset.saving = "true";
      button?.classList.add("is-loading");
      button?.setAttribute("aria-busy", "true");
      button?.setAttribute("disabled", "disabled");
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          signal: controller.signal,
          headers: {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        });
        let payload;
        if (response.headers.get("Content-Type")?.toLowerCase().includes("application/json")) {
          try { payload = await response.json(); } catch { /* An invalid JSON response uses the neutral error below. */ }
        }
        if (!response.ok || payload?.ok !== true || !payload.part) {
          if (typeof payload?.message === "string" && payload.message.trim()) errorMessage = payload.message;
          throw new Error("Status response failed");
        }
        allocation.querySelector("[data-status-error]")?.remove();
        window.setTimeout(() => window.location.reload(), 100);
      } catch {
        if (select && allocation?.dataset.partStatus) select.value = allocation.dataset.partStatus;
        let notice = allocation?.querySelector("[data-status-error]");
        if (!notice && allocation) {
          notice = document.createElement("small");
          notice.dataset.statusError = "true";
          notice.className = "inline-error";
          allocation.append(notice);
        }
        if (notice) notice.textContent = errorMessage;
      } finally {
        window.clearTimeout(timeout);
        delete form.dataset.saving;
        button?.classList.remove("is-loading");
        button?.removeAttribute("aria-busy");
        button?.removeAttribute("disabled");
      }
    });
  });
})();
