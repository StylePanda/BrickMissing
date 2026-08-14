"use strict";

function backupTimestamp(value){
  if(!value)return 0;
  const native=new Date(value).getTime();
  if(!Number.isNaN(native))return native;
  const match=String(value).match(/(\d{1,2})\.(\d{1,2})\.(\d{4})(?:,\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
  if(!match)return 0;
  return new Date(
    Number(match[3]),Number(match[2])-1,Number(match[1]),
    Number(match[4]||0),Number(match[5]||0),Number(match[6]||0)
  ).getTime();
}

const collectionWorkshop = {
  data: {projects:[],loans:[],prices:[],locations:[],wishlist:[],backupReminder:true},
  loadedUserId: null,
  tab: "shopping",
  async ensureLoaded() {
    if(this.loadedUserId===state.userId)return;
    const response=await request(`/api/workshop?user_id=${state.userId}`);
    const remote=response.workshop&&Object.keys(response.workshop).length?response.workshop:null;
    let legacy=null;
    try{legacy=JSON.parse(localStorage.getItem("brickWorkshop")||"null")}catch{}
    this.data=remote||legacy||{projects:[],loans:[],prices:[],locations:[],wishlist:[],backupReminder:true};
    this.loadedUserId=state.userId;
    if(!remote&&legacy){await this.persist();localStorage.removeItem("brickWorkshop")}
    const legacyBackup=localStorage.getItem("brickLastBackup");
    if(!this.data.lastBackup&&legacyBackup){this.data.lastBackup=legacyBackup;await this.persist(false);localStorage.removeItem("brickLastBackup")}
  },
  async persist(render=true) { await request("/api/workshop",{method:"POST",body:JSON.stringify({user_id:state.userId,workshop:this.data})}); if(render)this.render(); },
  currentParts() { return Array.isArray(state?.parts) ? state.parts : []; },

  render() {
    const host = document.querySelector("#collectionWorkshop");
    if (!host) return;
    const tabs = { shopping:"Einkauf & Preise", scan:"Scanner", projects:"Projekte & Wünsche", storage:"Lagerorte", loans:"Ausleihen", export:"Export & Backup" };
    host.innerHTML = `<div class="workshop-shell"><div class="workshop-tabs">${Object.entries(tabs).map(([id,label]) => `<button data-workshop-tab="${id}" class="${id === this.tab ? "active" : ""}">${label}</button>`).join("")}</div><div id="workshopBody"></div></div>`;
    host.querySelectorAll("[data-workshop-tab]").forEach(button => button.addEventListener("click", () => { this.tab = button.dataset.workshopTab; this.render(); }));
    this[`render_${this.tab}`]();
  },

  render_shopping() {
    const parts = this.currentParts().filter(x => x.status === "missing");
    const suppliers = Object.groupBy ? Object.groupBy(parts, x => x.supplier || "Ohne Händler") : parts.reduce((all,x) => ((all[x.supplier || "Ohne Händler"] ||= []).push(x), all), {});
    const duplicates = parts.filter((part,index,list) => list.findIndex(x => x.element_id === part.element_id && x.color === part.color) !== index);
    document.querySelector("#workshopBody").innerHTML = `<div class="workshop-grid"><section class="workshop-card"><h3>Einkauf optimieren</h3><p>${parts.length} offene Positionen bei ${Object.keys(suppliers).length} Händlern.</p><div>${Object.entries(suppliers).map(([name,items]) => `<div class="optimizer-row"><b>${esc(name)}</b><span>${items.reduce((s,x)=>s+Number(x.quantity),0)} Teile · ${items.reduce((s,x)=>s+Number(x.quantity)*Number(x.unit_price||0),0).toFixed(2)} €</span></div>`).join("")}</div></section><section class="workshop-card"><h3>Doppelte Teile</h3><p>${duplicates.length ? `${duplicates.length} mögliche Dubletten gefunden.` : "Keine Dubletten gefunden."}</p><div class="workshop-list">${duplicates.map(x => `<div class="workshop-item"><b>${esc(x.name)}</b><small>${esc(x.element_id)} · ${esc(x.color)}</small></div>`).join("")}</div></section><section class="workshop-card"><h3>Preis erfassen</h3><div class="workshop-form"><input id="priceItem" placeholder="Teil oder Set"><input id="priceSupplier" placeholder="Händler"><input id="priceValue" type="number" step=".01" placeholder="Preis €"><button class="btn primary" id="savePrice">Speichern</button></div></section><section class="workshop-card wide"><h3>Preisverlauf</h3><div class="workshop-list">${this.data.prices.map(x => `<div class="workshop-item"><div><b>${esc(x.item)}</b><small>${esc(x.supplier)} · ${esc(x.date)}</small></div><strong>${Number(x.price).toFixed(2)} €</strong></div>`).join("") || "<p>Noch keine Preise erfasst.</p>"}</div></section></div>`;
    document.querySelector("#savePrice").addEventListener("click", () => { const item=el("priceItem").value.trim(),price=Number(el("priceValue").value); if(!item||!price)return toast("Artikel und Preis fehlen.",true); this.data.prices.unshift({item,supplier:el("priceSupplier").value.trim()||"Unbekannt",price,date:new Date().toLocaleDateString("de-DE")}); this.persist(); });
  },

  render_scan() {
    document.querySelector("#workshopBody").innerHTML = `<div class="workshop-grid"><section class="workshop-card wide"><h3>Barcode-, QR- und Kameraerkennung</h3><p>Scanne eine Element-ID oder fotografiere ein Teil. Unterstützte Barcodes werden automatisch erkannt; das Bild kann anschließend direkt beim Fehlteil verwendet werden.</p><video id="scannerVideo" class="camera-preview" playsinline muted></video><canvas id="scannerCanvas" hidden></canvas><div class="actions"><button class="btn primary" id="startScanner">Kamera starten</button><button class="btn" id="capturePart">Teil aufnehmen</button><button class="btn" id="stopScanner">Stoppen</button></div><p id="scannerResult" class="sub">Noch kein Code erkannt.</p></section></div>`;
    let stream;
    const stop=()=>{stream?.getTracks().forEach(track=>track.stop());stream=null};
    el("startScanner").addEventListener("click",async()=>{try{stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:"environment"}});el("scannerVideo").srcObject=stream;await el("scannerVideo").play();toast("Kamera aktiv.")}catch(error){toast("Kamera konnte nicht geöffnet werden.",true)}});
    el("capturePart").addEventListener("click",async()=>{const video=el("scannerVideo"),canvas=el("scannerCanvas");canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext("2d").drawImage(video,0,0);if("BarcodeDetector" in window){const codes=await new BarcodeDetector({formats:["qr_code","code_128","ean_13"]}).detect(canvas);if(codes[0]){el("scannerResult").textContent=`Erkannt: ${codes[0].rawValue}`;navigator.clipboard?.writeText(codes[0].rawValue);return}}el("scannerResult").textContent="Foto aufgenommen. Kein Barcode erkannt – Bild steht zur manuellen Teilezuordnung bereit.";});
    el("stopScanner").addEventListener("click",stop);
  },

  render_projects() {
    const projects=this.data.projects,wishes=this.data.wishlist;
    document.querySelector("#workshopBody").innerHTML=`<div class="workshop-grid"><section class="workshop-card"><h3>Projekt anlegen</h3><div class="workshop-form"><input id="projectName" class="wide" placeholder="Projektname"><input id="projectDone" type="number" min="0" placeholder="Erledigt"><input id="projectTotal" type="number" min="1" placeholder="Gesamt"><button class="btn primary wide" id="saveProject">Speichern</button></div></section><section class="workshop-card"><h3>Wunschliste</h3><div class="workshop-form"><input id="wishName" placeholder="Set oder Teil"><input id="wishPriority" placeholder="Priorität"><button class="btn primary wide" id="saveWish">Hinzufügen</button></div></section><section class="workshop-card wide"><h3>Baufortschritt</h3><div class="workshop-list">${projects.map((x,i)=>`<div class="workshop-item"><div><b>${esc(x.name)}</b><small>${x.done} von ${x.total}</small><div class="workshop-progress"><i style="width:${Math.min(100,x.done/x.total*100)}%"></i></div></div><button class="icon-btn" data-project-done="${i}">＋1</button></div>`).join("")||"<p>Noch keine Projekte.</p>"}</div><h3>Wünsche</h3><div class="workshop-list">${wishes.map(x=>`<div class="workshop-item"><b>${esc(x.name)}</b><span>${esc(x.priority)}</span></div>`).join("")||"<p>Wunschliste leer.</p>"}</div></section></div>`;
    el("saveProject").addEventListener("click",()=>{const name=el("projectName").value.trim(),total=Number(el("projectTotal").value);if(!name||!total)return toast("Name und Gesamtzahl fehlen.",true);projects.push({name,done:Number(el("projectDone").value)||0,total});this.persist()});
    el("saveWish").addEventListener("click",()=>{const name=el("wishName").value.trim();if(!name)return;wishes.push({name,priority:el("wishPriority").value.trim()||"Normal"});this.persist()});
    document.querySelectorAll("[data-project-done]").forEach(b=>b.addEventListener("click",()=>{const p=projects[Number(b.dataset.projectDone)];p.done=Math.min(p.total,p.done+1);this.persist()}));
  },

  render_storage() {
    document.querySelector("#workshopBody").innerHTML=`<div class="workshop-grid"><section class="workshop-card"><h3>Lagerort zuweisen</h3><div class="workshop-form"><input id="locationItem" placeholder="Element-ID"><input id="locationBox" placeholder="Behälter"><input id="locationDrawer" placeholder="Schublade"><input id="locationSlot" placeholder="Fach"><button class="btn primary wide" id="saveLocation">Speichern</button></div></section><section class="workshop-card wide"><h3>Lagerplan</h3><div class="workshop-list">${this.data.locations.map(x=>`<div class="workshop-item"><div><b>${esc(x.item)}</b><small>${esc(x.box)} · Schublade ${esc(x.drawer)} · Fach ${esc(x.slot)}</small></div></div>`).join("")||"<p>Noch keine Lagerorte.</p>"}</div></section></div>`;
    el("saveLocation").addEventListener("click",()=>{const item=el("locationItem").value.trim();if(!item)return toast("Element-ID fehlt.",true);this.data.locations.push({item,box:el("locationBox").value.trim(),drawer:el("locationDrawer").value.trim(),slot:el("locationSlot").value.trim()});this.persist()});
  },

  render_loans() {
    document.querySelector("#workshopBody").innerHTML=`<div class="workshop-grid"><section class="workshop-card"><h3>Ausleihe erfassen</h3><div class="workshop-form"><input id="loanItem" placeholder="Set"><input id="loanPerson" placeholder="Person"><input id="loanDue" type="date"><button class="btn primary" id="saveLoan">Speichern</button></div></section><section class="workshop-card wide"><h3>Verliehene Sets</h3><div class="workshop-list">${this.data.loans.map((x,i)=>`<div class="workshop-item"><div><b>${esc(x.item)}</b><small>${esc(x.person)} · Rückgabe ${esc(x.due||"offen")}</small></div><button class="btn" data-return-loan="${i}">Zurück</button></div>`).join("")||"<p>Nichts verliehen.</p>"}</div></section></div>`;
    el("saveLoan").addEventListener("click",()=>{const item=el("loanItem").value.trim(),person=el("loanPerson").value.trim();if(!item||!person)return toast("Set und Person fehlen.",true);this.data.loans.push({item,person,due:el("loanDue").value});this.persist()});
    document.querySelectorAll("[data-return-loan]").forEach(b=>b.addEventListener("click",()=>{this.data.loans.splice(Number(b.dataset.returnLoan),1);this.persist()}));
  },

  render_export() {
    const timestamp=backupTimestamp(this.data.lastBackup);
    const last=timestamp?new Date(timestamp).toLocaleString("de-DE"):"Noch nie";
    document.querySelector("#workshopBody").innerHTML=`<div class="workshop-grid"><section class="workshop-card"><h3>Sammlung exportieren</h3><p>CSV für Tabellen oder druckoptimierte PDF-Ansicht.</p><div class="actions"><button class="btn primary" id="workshopCsv">CSV</button><button class="btn" id="workshopPdf">Als PDF drucken</button></div></section><section class="workshop-card"><h3>Backup-Erinnerung</h3><p>Letztes bestätigtes Backup: ${esc(last)}</p><label><input id="backupReminder" type="checkbox" style="width:auto;min-height:auto" ${this.data.backupReminder?"checked":""}> Alle 7 Tage erinnern</label><button class="btn primary" id="backupDone">Backup jetzt erstellen</button></section></div>`;
    el("workshopCsv").addEventListener("click",()=>download(`/api/export/csv?user_id=${state.userId}`));
    el("workshopPdf").addEventListener("click",()=>window.print());
    el("backupReminder").addEventListener("change",e=>{this.data.backupReminder=e.target.checked;this.persist()});
    el("backupDone").addEventListener("click",async()=>{await createBackup();this.render()});
  }
};

document.querySelector('[data-view="workshop"]').addEventListener("click",async()=>{try{await collectionWorkshop.ensureLoaded();collectionWorkshop.render()}catch(error){toast(error.message,true)}});
setTimeout(async()=>{
  await collectionWorkshop.ensureLoaded().catch(()=>{});
  if(!collectionWorkshop.data.backupReminder||sessionStorage.getItem("brickBackupReminderShown"))return;
  const last=backupTimestamp(collectionWorkshop.data.lastBackup);
  if(!last||Date.now()-last>7*86400000){
    sessionStorage.setItem("brickBackupReminderShown","1");
    toast("Backup-Erinnerung: Bitte eine aktuelle Sicherung erstellen.");
  }
},1200);
