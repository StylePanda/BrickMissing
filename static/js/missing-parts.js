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
      form.dataset.saving = "true";
      button?.setAttribute("disabled", "disabled");
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.message || "Status konnte nicht gespeichert werden.");
        allocation.dataset.partStatus = payload.part.status;
        const label = allocation.querySelector("[data-allocation-status-label]");
        if (label) label.textContent = payload.part.status_label;
        if (activeStatus && activeStatus !== payload.part.status) allocation.remove();
        updateGroup(row);
      } catch (error) {
        let notice = allocation?.querySelector("[data-status-error]");
        if (!notice && allocation) {
          notice = document.createElement("small");
          notice.dataset.statusError = "true";
          notice.className = "inline-error";
          allocation.append(notice);
        }
        if (notice) notice.textContent = error.message || "Status konnte nicht gespeichert werden.";
      } finally {
        delete form.dataset.saving;
        button?.removeAttribute("disabled");
      }
    });
  });
})();
