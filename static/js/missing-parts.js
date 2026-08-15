(() => {
  "use strict";
  const activeStatus = new URLSearchParams(window.location.search).get("status") || "";

  function updateGroup(row) {
    const allocations = [...row.querySelectorAll("[data-part-allocation]")];
    if (!allocations.length) {
      row.remove();
      return;
    }
    const statuses = new Set(allocations.map((item) => item.dataset.partStatus));
    const badge = row.querySelector("[data-group-workflow-status]");
    if (!badge) return;
    if (statuses.size === 1) {
      const allocation = allocations[0];
      badge.textContent = allocation.querySelector("[data-allocation-status-label]")?.textContent || "–";
      badge.className = `badge ${allocation.dataset.partStatus}`;
    } else {
      badge.textContent = "Gemischt";
      badge.className = "badge mixed";
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
