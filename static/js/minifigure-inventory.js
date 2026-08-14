(() => {
  const forms = document.querySelectorAll('form[action*="/organisation/minifiguren/"][action$="/bestand/"]');
  if (!forms.length) return;
  const timeoutMs = 8000;
  forms.forEach((form) => {
    form.dataset.inlineInventory = "true";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.dataset.saving === "true") return;
      const input = form.querySelector('input[name="owned_quantity"]');
      const oldValue = input?.value;
      const submitted = event.submitter?.value;
      if (input && submitted !== undefined && event.submitter?.name === "owned_quantity") input.value = submitted;
      const row = form.closest("[data-minifigure-part]") || form.closest("tr");
      const figure = form.closest("[data-minifigure]") || form.closest("details")?.previousElementSibling || form.closest(".minifigure-card");
      const button = event.submitter || form.querySelector("button");
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
      form.dataset.saving = "true";
      button?.classList.add("is-loading");
      button?.setAttribute("aria-busy", "true");
      row?.classList.add("is-saving");
      try {
        const body = new FormData(form);
        if (!input && submitted !== undefined && event.submitter?.name === "owned_quantity") body.set("owned_quantity", submitted);
        const response = await fetch(form.action, {
          method: "POST", body, signal: controller.signal,
          headers: {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.message || "Bestand konnte nicht gespeichert werden.");
        if (input) input.value = payload.part.owned;
        row?.querySelectorAll("[data-part-owned]").forEach((node) => { node.textContent = payload.part.owned; });
        row?.querySelectorAll("[data-part-missing]").forEach((node) => { node.textContent = payload.part.missing; });
        const partStatus = row?.querySelector("[data-part-status]");
        if (partStatus) { partStatus.textContent = payload.part.status_label; partStatus.className = `badge ${payload.part.status}`; }
        figure?.querySelectorAll("[data-figure-owned]").forEach((node) => { node.textContent = payload.figure.owned; });
        figure?.querySelectorAll("[data-figure-required]").forEach((node) => { node.textContent = payload.figure.required; });
        const progress = figure?.querySelector("[data-figure-progress]"); if (progress) progress.value = payload.figure.percent;
        const fallbackCount = figure?.querySelector(".minifigure-progress strong");
        if (fallbackCount) fallbackCount.textContent = `${payload.figure.owned}/${payload.figure.required}`;
        const fallbackProgress = figure?.querySelector(".minifigure-progress progress");
        if (fallbackProgress) fallbackProgress.value = payload.figure.percent;
        const figureStatus = figure?.querySelector("[data-figure-status]") || figure?.querySelector(".minifigure-progress .badge");
        if (figureStatus) { figureStatus.textContent = payload.figure.status_label; figureStatus.className = `badge ${payload.figure.status}`; }
        document.querySelectorAll("[data-set-completeness]").forEach((node) => { node.textContent = payload.set.label; node.className = `badge ${payload.set.key}`; });
        document.querySelectorAll("[data-set-completeness-count]").forEach((node) => { node.textContent = `${payload.set.owned} von ${payload.set.required} vorhanden`; });
        const completenessTerm = [...document.querySelectorAll("dt")].find((node) => node.textContent.trim() === "Vollständigkeit");
        const completenessValue = completenessTerm?.nextElementSibling;
        const completenessBadge = completenessValue?.querySelector(".badge");
        const completenessCount = completenessValue?.querySelector("small");
        if (completenessBadge) { completenessBadge.textContent = payload.set.label; completenessBadge.className = `badge ${payload.set.key}`; }
        if (completenessCount) completenessCount.textContent = `${payload.set.owned} von ${payload.set.required} vorhanden`;
      } catch (error) {
        if (input) input.value = oldValue;
        const message = error.name === "AbortError" ? "Speichern hat zu lange gedauert. Bitte erneut versuchen." : (error.message || "Bestand konnte nicht gespeichert werden.");
        let notice = row?.querySelector("[data-inline-error]");
        if (!notice && row) { notice = document.createElement("p"); notice.dataset.inlineError = "true"; notice.className = "inline-error"; row.append(notice); }
        if (notice) notice.textContent = message;
      } finally {
        window.clearTimeout(timeout);
        delete form.dataset.saving;
        button?.classList.remove("is-loading");
        button?.removeAttribute("aria-busy");
        button?.removeAttribute("disabled");
        row?.classList.remove("is-saving");
      }
    });
  });
})();
