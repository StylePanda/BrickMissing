(function () {
  const form = document.querySelector('[data-batch-form]');
  if (!form) return;
  const previewArea = document.querySelector('[data-batch-preview-area]');
  const rows = document.querySelector('[data-batch-rows]');
  const message = document.querySelector('[data-batch-message]');
  const importButton = document.querySelector('[data-batch-import]');
  const progress = document.querySelector('[data-batch-progress]');
  const progressBar = document.querySelector('[data-batch-progress-bar]');
  const progressText = document.querySelector('[data-batch-progress-text]');
  const summary = document.querySelector('[data-batch-summary]');
  const importUrl = form.action.replace(/vorschau\/?$/, 'importieren/');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  const defaultDate = document.querySelector('[name=default_purchase_date]');
  const defaultCondition = document.querySelector('[name=default_condition]');
  const defaultNotes = document.querySelector('[name=default_notes]');
  let previewSets = [];
  const escapeHtml = value => String(value).replace(/[&<>'"]/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[char]));

  function post(url, data) {
    data.append('csrfmiddlewaretoken', csrf);
    return fetch(url, { method: 'POST', body: data, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
  }

  function renderPreview(payload) {
    previewSets = payload.sets || [];
    rows.replaceChildren();
    (payload.invalid || []).forEach(number => {
      const p = document.createElement('p'); p.textContent = `${number}: Ungültige Setnummer`; rows.appendChild(p);
    });
    previewSets.forEach((item, index) => {
      const label = document.createElement('label'); label.className = 'batch-set-row';
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = item.status === 'ready'; checkbox.disabled = item.status !== 'ready'; checkbox.dataset.index = index;
      const text = document.createElement('span'); text.textContent = `${item.number} – ${item.name || item.message || (item.status === 'existing' ? 'Bereits vorhanden' : item.status)}`;
      label.append(checkbox, text); rows.appendChild(label);
      if (item.status === 'ready') {
        const metadata = document.createElement('div'); metadata.className = 'batch-set-metadata';
        metadata.innerHTML = `<label>Kaufdatum <input type="date" data-field="purchase_date" value="${escapeHtml(defaultDate?.value || '')}"></label><label>Preis <input type="number" min="0" step="0.01" data-field="purchase_price" value=""></label><label>Zustand <select data-field="condition"><option value="neu"${defaultCondition?.value === 'neu' ? ' selected' : ''}>Neu</option><option value="gebraucht"${defaultCondition?.value === 'gebraucht' ? ' selected' : ''}>Gebraucht</option></select></label><label>Notizen <input type="text" data-field="notes" value="${escapeHtml(defaultNotes?.value || '')}"></label>`;
        metadata.dataset.index = index; rows.appendChild(metadata);
      }
    });
    message.textContent = `${payload.duplicates || 0} doppelte Eingabe(n) entfernt.`;
    importButton.disabled = !previewSets.some(item => item.status === 'ready');
    previewArea.hidden = false;
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const previewData = new FormData(form);
    previewData.append('default_purchase_date', defaultDate?.value || '');
    previewData.append('default_condition', defaultCondition?.value || 'neu');
    previewData.append('default_notes', defaultNotes?.value || '');
    const response = await post(form.action, previewData);
    if (!response.ok) { message.textContent = 'Vorschau konnte nicht geladen werden.'; previewArea.hidden = false; return; }
    renderPreview(await response.json());
  });

  importButton.addEventListener('click', async () => {
    const selected = [...rows.querySelectorAll('input[type=checkbox]:checked')].map(input => previewSets[Number(input.dataset.index)]).filter(Boolean);
    if (!selected.length) return;
    importButton.disabled = true;
    progress.hidden = false; progressBar.max = selected.length; progressBar.value = 0;
    let successful = 0; let failed = 0; let skipped = 0;
    for (let index = 0; index < selected.length; index += 1) {
      const item = selected[index]; progressText.textContent = `Set ${index + 1} von ${selected.length}: ${item.number}`;
      const data = new FormData(); data.append('set_number', item.number);
      const metadata = rows.querySelector(`.batch-set-metadata[data-index="${previewSets.indexOf(item)}"]`);
      metadata?.querySelectorAll('[data-field]').forEach(field => data.append(field.dataset.field, field.value));
      try {
        const response = await post(importUrl, data);
        const result = await response.json();
        if (result.status === 'imported') successful += 1; else if (result.status === 'existing') skipped += 1; else failed += 1;
      } catch (error) { failed += 1; }
      progressBar.value = index + 1;
    }
    progressText.textContent = 'Import abgeschlossen.';
    summary.textContent = `${successful} erfolgreich, ${skipped} übersprungen, ${failed} fehlgeschlagen.`;
  });
}());
