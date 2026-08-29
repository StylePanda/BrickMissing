(() => {
  "use strict";
  const openButtons = [...document.querySelectorAll("[data-bulk-sync-open]")];
  const dialog = document.querySelector("[data-bulk-sync-dialog]");
  if (!openButtons.length || !dialog) return;
  const startButton = dialog.querySelector("[data-bulk-sync-start]");
  const cancelButton = dialog.querySelector("[data-bulk-sync-cancel]");
  const progress = dialog.querySelector("[data-bulk-sync-progress]");
  const current = dialog.querySelector("[data-bulk-sync-current]");
  const bar = dialog.querySelector("[data-bulk-sync-bar]");
  const summary = dialog.querySelector("[data-bulk-sync-summary]");
  const errorList = dialog.querySelector("[data-bulk-sync-errors]");
  const sets = [...document.querySelectorAll("[data-sync-url]")];
  const csrfToken = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1] || "";
  let running = false;
  openButtons.forEach((button) => button.addEventListener("click", () => dialog.showModal()));
  startButton.addEventListener("click", async () => {
    if (running) return;
    running = true;
    openButtons.forEach((button) => { button.disabled = true; });
    startButton.disabled = true;
    cancelButton.disabled = true;
    progress.hidden = false;
    errorList.replaceChildren();
    let successful = 0;
    for (let index = 0; index < sets.length; index += 1) {
      const item = sets[index];
      current.textContent = `Synchronisiere Set ${index + 1} von ${sets.length}: ${item.dataset.syncNumber} – ${item.dataset.syncName}`;
      const body = new FormData();
      body.append("csrfmiddlewaretoken", csrfToken);
      body.append("bulk", "1");
      try {
        const response = await fetch(item.dataset.syncUrl, {method: "POST", body, headers: {"Accept": "application/json"}});
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.message || "Synchronisation fehlgeschlagen");
        successful += 1;
      } catch (_error) {
        const entry = document.createElement("li");
        entry.textContent = `${item.dataset.syncNumber} – ${item.dataset.syncName}`;
        errorList.append(entry);
      }
      bar.value = index + 1;
      summary.textContent = `Erfolgreich: ${successful} · Fehlgeschlagen: ${index + 1 - successful}`;
    }
    current.textContent = "Synchronisation abgeschlossen.";
    cancelButton.disabled = false;
    cancelButton.textContent = "Schließen";
    running = false;
  });
})();
