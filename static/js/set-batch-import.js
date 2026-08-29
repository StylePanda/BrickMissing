(function () {
  const form = document.querySelector('[data-batch-form]');
  if (!form) return;
  const previewArea = document.querySelector('[data-batch-preview-area]');
  const rows = document.querySelector('[data-batch-rows]');
  const message = document.querySelector('[data-batch-message]');
  const previewButton = form.querySelector('[data-batch-preview]');
  const importButton = document.querySelector('[data-batch-import]');
  const progress = document.querySelector('[data-batch-progress]');
  const progressBar = document.querySelector('[data-batch-progress-bar]');
  const progressText = document.querySelector('[data-batch-progress-text]');
  const summary = document.querySelector('[data-batch-summary]');
  const importUrl = form.action.replace(/vorschau\/?$/, 'importieren/');
  const previewOneUrl = form.action.replace(/vorschau\/?$/, 'vorschau/einzel/');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  let previewSets = [];
  let running = false;

  function post(url, data) {
    if (!data.has('csrfmiddlewaretoken')) data.append('csrfmiddlewaretoken', csrf);
    return fetch(url, { method: 'POST', body: data, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  }

  function appendPreview(item) {
    const index = previewSets.push(item) - 1;
    const label = document.createElement('label'); label.className = 'batch-set-row';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = item.status === 'ready'; checkbox.disabled = item.status !== 'ready'; checkbox.dataset.index = index;
    const text = document.createElement('span'); text.textContent = `${item.number} – ${item.name || item.message || (item.status === 'existing' ? 'Bereits vorhanden' : item.status)}`;
    label.append(checkbox, text); rows.appendChild(label);
    if (item.status === 'ready') {
      const metadata = document.createElement('div'); metadata.className = 'batch-set-metadata'; metadata.dataset.index = index;
      metadata.innerHTML = '<label>Kaufdatum <input type="date" data-field="purchase_date"></label><label>Preis <input type="text" inputmode="decimal" data-field="purchase_price"></label><label>Zustand <select data-field="condition"><option value="neu" selected>Neu</option><option value="gebraucht">Gebraucht</option></select></label><label>Notizen <input type="text" data-field="notes"></label>';
      rows.appendChild(metadata);
    }
  }

  function finishPreview() {
    previewButton.disabled = false;
    previewButton.textContent = 'Prüfen';
    previewArea.setAttribute('aria-busy', 'false');
    importButton.disabled = !previewSets.some(item => item.status === 'ready');
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (running) return;
    running = true; previewSets = []; rows.replaceChildren(); previewArea.hidden = false; previewArea.setAttribute('aria-busy', 'true');
    previewButton.disabled = true; previewButton.textContent = 'Prüfen…'; importButton.disabled = true;
    const values = [...new Set((new FormData(form).get('set_numbers') || '').split(/[\s,;]+/).map(value => value.trim()).filter(Boolean))];
    progress.hidden = false; progressBar.max = values.length || 1; progressBar.value = 0;
    try {
      for (let index = 0; index < values.length; index += 1) {
        progressText.textContent = `Set ${index + 1} von ${values.length} wird geprüft`;
        const data = new FormData(); data.append('set_number', values[index]);
        try {
          const response = await post(previewOneUrl, data); const payload = await response.json();
          appendPreview(payload.set || { number: values[index], status: 'error', message: 'Vorschau fehlgeschlagen.' });
        } catch (error) { appendPreview({ number: values[index], status: 'error', message: 'Vorschau fehlgeschlagen.' }); }
        progressBar.value = index + 1;
      }
      message.textContent = `${previewSets.length} Set(s) geprüft.`;
    } finally {
      running = false; progressText.textContent = 'Prüfung abgeschlossen.'; finishPreview();
    }
  });

  importButton.addEventListener('click', async () => {
    const selected = [...rows.querySelectorAll('input[type=checkbox]:checked')].map(input => previewSets[Number(input.dataset.index)]).filter(Boolean);
    if (!selected.length || running) return;
    running = true; importButton.disabled = true; progress.hidden = false; progressBar.max = selected.length; progressBar.value = 0;
    let successful = 0; let failed = 0; let skipped = 0;
    try {
      for (let index = 0; index < selected.length; index += 1) {
        const item = selected[index]; progressText.textContent = `Set ${index + 1} von ${selected.length}: ${item.number}`;
        const data = new FormData(); data.append('set_number', item.number);
        const metadata = rows.querySelector(`.batch-set-metadata[data-index="${previewSets.indexOf(item)}"]`);
        metadata?.querySelectorAll('[data-field]').forEach(field => data.append(field.dataset.field, field.value));
        try { const response = await post(importUrl, data); const result = await response.json(); if (result.status === 'imported') successful += 1; else if (result.status === 'existing') skipped += 1; else failed += 1; } catch (error) { failed += 1; }
        progressBar.value = index + 1;
      }
    } finally { running = false; progressText.textContent = 'Import abgeschlossen.'; summary.textContent = `${successful} erfolgreich, ${skipped} übersprungen, ${failed} fehlgeschlagen.`; }
  });
}());
