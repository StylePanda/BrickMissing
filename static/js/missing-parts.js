(() => {
  "use strict";
  const activeStatus = new URLSearchParams(window.location.search).get("status") || "";

  function updateGroup(row) {
    const allocations = [...row.querySelectorAll("[data-part-allocation]")];
    if (!allocations.length) {
      row.remove();
      return;
    }
    const badge = row.querySelector("[data-group-status]");
    if (!badge) return;
    const owned = allocations.reduce((total, allocation) => total + Number(allocation.querySelector("[data-allocation-owned]")?.textContent || 0), 0);
    const missing = allocations.reduce((total, allocation) => total + Number(allocation.querySelector("[data-allocation-missing]")?.textContent || 0), 0);
    if (missing <= 0) {
      badge.textContent = "Erhalten";
      badge.className = "badge complete";
    } else if (owned <= 0) {
      badge.textContent = "Fehlt";
      badge.className = "badge missing";
    } else {
      badge.textContent = "Teilweise";
      badge.className = "badge partial";
    }
  }

  document.querySelectorAll(".status-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.dataset.saving === "true") return;
      const allocation = form.closest("[data-part-allocation]");
      const row = form.closest("[data-part-group]");
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
        allocation.dataset.partStatus = payload.part.status;
        const label = allocation.querySelector("[data-allocation-status-label]");
        if (label) {
          label.textContent = payload.part.status_label;
          label.dataset.status = payload.part.status;
        }
        allocation.querySelector("[data-status-error]")?.remove();
        if (activeStatus && activeStatus !== payload.part.status) allocation.remove();
        updateGroup(row);
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
