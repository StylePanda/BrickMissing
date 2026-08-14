"use strict";

const pro7 = {copies: [], copySort: "updated-desc", copySearch: "", mocs: [], inventory: [], movements: [], minifigures: [], orders: [], quality: [], labelSetIds: new Set(), labelMode: "set", labelShowImages: true, labelStartPosition: 1, labelQrTarget: "set", labelBaseUrl: "", checkedBagLabelText: "DURCHSUCHT", checkedBagLabelCount: 8};
const LEGO_COLORS = [
  "Black","Blue","Green","Dark Turquoise","Red","Dark Pink","Brown","Light Gray",
  "Dark Gray","Light Blue","Bright Green","Light Turquoise","Salmon","Pink","Yellow",
  "White","Light Green","Light Yellow","Tan","Light Violet","Purple","Violet","Orange",
  "Magenta","Lime","Dark Tan","Bright Pink","Medium Lavender","Lavender","Sand Green",
  "Sand Blue","Sand Red","Medium Blue","Dark Blue","Dark Green","Dark Red","Dark Brown",
  "Medium Green","Olive Green","Nougat","Medium Nougat","Dark Nougat","Medium Tan",
  "Very Light Gray","Very Light Bluish Gray","Light Bluish Gray","Dark Bluish Gray",
  "Reddish Brown","Bright Light Blue","Bright Light Orange","Bright Light Yellow",
  "Bright Light Green","Yellowish Green","Dark Orange","Dark Purple","Medium Azure",
  "Dark Azure","Aqua","Light Aqua","Spring Yellowish Green","Coral","Neon Yellow",
  "Warm Tan","Sienna Brown","Fabuland Brown","Rust","Maersk Blue","Royal Blue",
  "Trans-Clear","Trans-Black","Trans-Red","Trans-Neon Orange","Trans-Light Blue",
  "Trans-Dark Blue","Trans-Neon Green","Trans-Bright Green","Trans-Yellow","Trans-Orange",
  "Trans-Purple","Trans-Pink","Trans-Neon Yellow","Trans-Brown","Trans-Light Purple",
  "Trans-Medium Blue","Trans-Green","Trans-Very Light Blue","Trans-Black IR Lens",
  "Chrome Gold","Chrome Silver","Chrome Black","Chrome Blue","Chrome Green","Chrome Pink",
  "Chrome Antique Brass","Pearl Black","Pearl Dark Gray","Pearl Light Gray","Pearl Gold",
  "Pearl White","Pearl Very Light Gray","Pearl Red","Pearl Blue","Flat Silver",
  "Metallic Gold","Metallic Silver","Metallic Green","Metallic Black","Metallic Copper",
  "Speckle Black-Silver","Speckle Black-Gold","Speckle Black-Copper","Speckle Dark Bluish Gray-Silver",
  "Milky White","Glow In Dark Opaque","Glow In Dark White","Glow In Dark Trans",
  "Glitter Trans-Clear","Glitter Trans-Purple","Glitter Trans-Light Blue",
  "Glitter Trans-Dark Pink","Glitter Trans-Neon Green","Satin Trans-Clear","Satin Trans-Black",
  "Satin Trans-Light Blue","Satin Trans-Dark Pink","Satin Trans-Bright Green",
  "Satin White","Modulex Black","Modulex White","Modulex Light Gray","Modulex Charcoal Gray",
  "Modulex Red","Modulex Pink Red","Modulex Orange","Modulex Light Orange","Modulex Buff",
  "Modulex Light Yellow","Modulex Ochre Yellow","Modulex Lemon","Modulex Pastel Green",
  "Modulex Olive Green","Modulex Aqua Green","Modulex Teal Blue","Modulex Cyan",
  "Modulex Pastel Blue","Modulex Violet","Modulex Brown","Modulex Foil Dark Gray",
  "Modulex Foil Light Gray","Modulex Foil Dark Green","Modulex Foil Light Green","Modulex Foil Dark Blue",
  "Modulex Foil Light Blue","Modulex Foil Violet","Modulex Foil Red","Modulex Foil Yellow",
  "Unknown","No Color"
];
const pro7Titles = {
  copies: "Set-Exemplare", mocs: "MOCs", inventory: "Teileinventar",
  minifigures: "Minifiguren",
  "goods-receipt": "Wareneingang", labels: "Etiketten & QR-Codes",
  quality: "Datenqualität", system: "Systemstatus"
};

async function pro7Get(resource, extra = "") {
  const separator = extra ? "&" : "";
  return request(`/api/pro7?resource=${encodeURIComponent(resource)}&user_id=${state.userId}${separator}${extra}`);
}

async function pro7Post(payload) {
  return request("/api/pro7", {method: "POST", body: JSON.stringify({...payload, user_id: state.userId})});
}

function pro7Empty(text, action = "") {
  return `<div class="pro7-empty"><strong>${esc(text)}</strong>${action}</div>`;
}
function marketMoney(value){
  const price=Number(value||0);
  return price?price.toLocaleString("de-DE",{style:"currency",currency:"EUR"}):"Noch nicht ermittelt";
}

async function loadPro7View(view) {
  if (!pro7Titles[view]) return;
  el("pageTitle").textContent = pro7Titles[view];
  try {
    if (view === "copies") {
      pro7.copies = (await pro7Get("copies")).data;
      const copies = [...pro7.copies].sort((a,b)=>{
        if(pro7.copySort==="set-asc") return clean(a.set_number).localeCompare(clean(b.set_number),"de",{numeric:true});
        if(pro7.copySort==="price-desc") return Number(b.purchase_price)-Number(a.purchase_price);
        if(pro7.copySort==="condition-asc") return clean(a.condition).localeCompare(clean(b.condition),"de");
        return clean(b.updated_at).localeCompare(clean(a.updated_at));
      });
      el("pro7Copies").innerHTML = `
        <section class="panel copies-panel"><div class="panel-head copies-head"><div><p class="eyebrow">MEHRERE EXEMPLARE</p><h2>Set-Exemplare</h2><p class="sub">Alle Ausgaben, Zustände und Lagerorte deiner Sets verwalten.</p></div><div class="actions"><button class="btn refresh-data-btn" data-pro7-action="refresh-copies">↻ Aktualisieren</button><button class="btn primary" data-pro7-action="new-copy">＋ Exemplar</button></div></div>
        <div class="copy-filter-bar"><label class="copy-search"><span aria-hidden="true">⌕</span><input id="copySearch" type="search" value="${esc(pro7.copySearch)}" placeholder="Setnummer, Name, Status oder Lagerort suchen"></label><label class="copy-sort"><span>Sortierung</span><select id="copySort"><option value="updated-desc">Zuletzt bearbeitet</option><option value="set-asc">Setnummer</option><option value="condition-asc">Zustand</option><option value="price-desc">Kaufpreis absteigend</option></select></label></div>
        <div class="pro7-grid">${copies.length ? copies.map(copy => `
          <article class="pro7-card" data-copy-search="${esc([copy.set_number,copy.set_name,copy.inventory_number,copy.serial_number,copy.condition,copy.completeness,copy.build_status,copy.location_name,copy.notes].join(" ").toLowerCase())}"><span class="status">${esc(copy.condition)}</span><h3>${esc(copy.set_number)} · ${esc(copy.set_name)}</h3>
          <p>${esc(copy.inventory_number || "Ohne Inventarnummer")}</p><dl><div><dt>Vollständigkeit</dt><dd>${esc(copy.completeness)}</dd></div>
          <div><dt>Bauzustand</dt><dd>${esc(copy.build_status)}</dd></div><div><dt>Lagerort</dt><dd>${esc(copy.location_name || "Nicht zugeordnet")}</dd></div><div><dt>Kaufpreis</dt><dd>${Number(copy.purchase_price||0).toLocaleString("de-DE",{style:"currency",currency:"EUR"})}</dd></div></dl>
          <div class="row-actions pro7-card-actions"><button class="btn" data-pro7-action="edit-copy" data-id="${copy.id}">Bearbeiten</button></div></article>`).join("") :
          pro7Empty("Noch keine Set-Exemplare vorhanden.", `<button class="btn primary" data-pro7-action="new-copy">Erstes Exemplar anlegen</button>`)}</div><div id="copySearchEmpty" class="empty hidden">Keine passenden Set-Exemplare gefunden.</div></section>`;
      el("copySort").value=pro7.copySort;
      el("copySort").addEventListener("change",event=>{pro7.copySort=event.target.value;loadPro7View("copies")});
      const applyCopySearch=()=>{pro7.copySearch=clean(el("copySearch").value);const query=pro7.copySearch.toLowerCase();let visible=0;document.querySelectorAll("#pro7Copies [data-copy-search]").forEach(card=>{const show=!query||card.dataset.copySearch.includes(query);card.classList.toggle("hidden",!show);if(show)visible++});el("copySearchEmpty").classList.toggle("hidden",visible>0||!copies.length)};
      el("copySearch").addEventListener("input",applyCopySearch);applyCopySearch();
    } else if (view === "mocs") {
      pro7.mocs = (await pro7Get("mocs")).data;
      el("pro7Mocs").innerHTML = `<section class="panel"><div class="panel-head"><div><p class="eyebrow">EIGENE MODELLE</p><h2>MOCs & Versionen</h2></div>
        <button class="btn primary" data-pro7-action="new-moc">＋ MOC</button></div><div class="pro7-grid">${pro7.mocs.length ? pro7.mocs.map(m => `
        <article class="pro7-card"><span class="status">${esc(m.status)}</span><h3>${esc(m.name)}</h3><p>${esc(m.project_code || "Ohne Projektcode")} · Version ${esc(m.version)}</p>
        <div class="inventory-progress"><i style="width:${Number(m.progress)}%"></i></div><small>${Number(m.progress)} % · ${Number(m.allocated_parts)}/${Number(m.required_parts)} Teile</small></article>`).join("") :
        pro7Empty("Noch keine eigenen Modelle vorhanden.", `<button class="btn primary" data-pro7-action="new-moc">Erstes MOC anlegen</button>`)}</div></section>`;
    } else if (view === "inventory") {
      [pro7.inventory, pro7.movements] = await Promise.all([
        pro7Get("inventory").then(x => x.data), pro7Get("movements").then(x => x.data)
      ]);
      el("pro7Inventory").innerHTML = `<div class="toolbar"><input id="pro7InventorySearch" placeholder="Teilenummer, Name, Farbe oder Lagerort"><button class="btn primary" data-pro7-action="new-inventory">＋ Teil</button></div>
        <section class="panel"><div class="panel-head"><h2>Zentrales Teileinventar</h2><span>${pro7.inventory.reduce((n,x)=>n+Number(x.quantity),0)} Teile</span></div>
        <div class="table-wrap"><table><thead><tr><th>Teil</th><th>Farbe</th><th>Lagerort</th><th>Bestand</th><th>Reserviert</th><th>Verfügbar</th><th>Stückpreis</th><th>Bestandswert</th><th></th></tr></thead><tbody id="pro7InventoryRows"></tbody></table></div></section>
        <section class="panel pro7-spaced"><div class="panel-head"><h2>Letzte Bestandsbewegungen</h2></div><div class="table-wrap"><table><thead><tr><th>Zeit</th><th>Teil</th><th>Art</th><th>Änderung</th><th>Benutzer</th></tr></thead><tbody>
        ${pro7.movements.slice(0,30).map(m=>`<tr><td>${esc(m.created_at)}</td><td>${esc(m.part_number)} · ${esc(m.name)}</td><td>${esc(m.movement_type)}</td><td>${Number(m.difference)>0?"+":""}${Number(m.difference)}</td><td>${esc(m.user_name||"System")}</td></tr>`).join("")}</tbody></table></div></section>`;
      renderPro7Inventory();
      el("pro7InventorySearch").addEventListener("input", renderPro7Inventory);
    } else if (view === "minifigures") {
      pro7.minifigures = (await pro7Get("minifigures")).data;
      el("pro7Minifigures").innerHTML = `<div class="toolbar minifigure-toolbar"><input id="minifigureSearch" placeholder="Minifigur, Figurennummer oder Set suchen"><select id="minifigureSetFilter"><option value="all">Alle Sets</option>${state.sets.map(set=>`<option value="${set.id}">${esc(set.set_number)} · ${esc(set.name)}</option>`).join("")}</select><select id="minifigureSort"><option value="set-asc">Setnummer aufsteigend</option><option value="set-desc">Setnummer absteigend</option><option value="name-asc">Minifigur A–Z</option><option value="missing-desc">Meiste Fehlteile zuerst</option><option value="missing-asc">Wenigste Fehlteile zuerst</option></select><button class="btn" data-pro7-action="fetch-minifigures">Daten aktualisieren</button><button class="btn primary" data-pro7-action="new-minifigure">＋ Minifigur</button></div><section class="minifigure-page"><div class="minifigure-page-head"><div><p class="eyebrow">SETS & FIGUREN</p><h2>Minifiguren</h2><p>Figuren, Einzelteile und Vollständigkeit nach Sets geordnet.</p></div><strong>${pro7.minifigures.reduce((sum,item)=>sum+Number(item.quantity),0)} Figuren</strong></div><div id="minifigureGrid" class="minifigure-collection"></div></section>`;
      renderMinifigures();
      el("minifigureSearch").addEventListener("input",renderMinifigures);
      el("minifigureSetFilter").addEventListener("change",renderMinifigures);
      el("minifigureSort").addEventListener("change",renderMinifigures);
    } else if (view === "goods-receipt") {
      pro7.orders = state.orders || [];
      el("pro7GoodsReceipt").innerHTML = `<section class="panel"><div class="panel-head"><div><p class="eyebrow">GEFÜHRTER PROZESS</p><h2>Wareneingang</h2></div></div>
        <div class="panel-body"><label>Bestellung auswählen<select id="receiptOrder"><option value="">Bitte wählen</option>${pro7.orders.map(o=>`<option value="${o.id}">${esc(o.supplier)} · ${esc(o.order_number||"#"+o.id)}</option>`).join("")}</select></label>
        <div id="receiptPositions" class="pro7-spaced">${pro7Empty("Wähle eine Bestellung, um ihre Positionen zu prüfen.")}</div></div></section>`;
      el("receiptOrder").addEventListener("change", loadReceipt);
    } else if (view === "labels") {
      pro7.copies = (await pro7Get("copies")).data;
      pro7.labelSetIds=new Set(state.sets.map(set=>Number(set.id)));
      el("pro7Labels").innerHTML = `<section class="panel label-generator"><div class="panel-head"><div><p class="eyebrow">HERMA NO. 5077 · WORD-VORLAGE</p><h2>Etikettengenerator</h2><p class="sub">99,1 × 67,7 mm · exakte Abstände und Ränder der bereitgestellten Hochformat-Vorlage</p></div><div class="actions"><button class="btn" data-pro7-action="select-all-label-sets">Alle auswählen</button><button class="btn primary" data-pro7-action="print-labels">Etiketten drucken</button></div></div>
        <div class="label-generator-layout"><aside class="label-set-picker"><div class="label-set-picker-head"><strong>Sets auswählen</strong><span id="labelSelectionCount"></span></div><label class="label-image-option"><input id="labelShowImages" type="checkbox" checked><span><strong>Setbilder anzeigen</strong><small>Gilt für Vorschau und Ausdruck</small></span></label><label class="label-setting">Erste Etikettenposition<select id="labelStartPosition">${Array.from({length:8},(_,index)=>`<option value="${index+1}">Position ${index+1} · Reihe ${Math.floor(index/2)+1}, ${index%2===0?"links":"rechts"}</option>`).join("")}</select><small>Bereits verwendete Felder auf dem ersten Bogen werden übersprungen.</small></label><label class="label-setting">QR-Ziel<select id="labelQrTarget"><option value="set">Setseite</option><option value="inventory">Inventarliste</option><option value="missing">Fehlteile</option><option value="edit">Bearbeiten</option><option value="bricklink">BrickLink</option><option value="rebrickable">Rebrickable</option></select></label><label class="label-setting">BrickMissing-Adresse für QR-Codes<input id="labelBaseUrl" value="${esc(location.origin)}" placeholder="http://192.168.1.10:8088"></label><input id="labelSetSearch" placeholder="Setnummer oder Name suchen"><div id="labelSetOptions"></div></aside>
        <div class="label-preview-area"><div class="label-print-hint">Passend zur bereitgestellten HERMA-Vorlage: A4, Hochformat, Skalierung 100 %, Ränder „Keine“ und Kopf-/Fußzeilen deaktivieren.</div><div id="labelSheets"></div></div></div></section>`;
      renderLabelSetOptions();
      pro7.labelBaseUrl=location.origin;
      el("labelShowImages").closest("label").insertAdjacentHTML("beforebegin",`<label class="label-setting">Etikettentyp<select id="labelMode"><option value="set">Vollständiges Set-Etikett</option><option value="minifigure-number">Nur Setnummer · einmal pro Minifigur</option><option value="checked-bag">Farbsackerl · durchsucht</option></select><small>Set-Etiketten, Minifiguren-Nummern oder Kontrollaufkleber drucken.</small></label><div id="checkedBagLabelSettings" class="checked-bag-label-settings hidden"><label class="label-setting">Text auf dem Etikett<input id="checkedBagLabelText" maxlength="32" value="${esc(pro7.checkedBagLabelText)}"></label><label class="label-setting">Anzahl Etiketten<input id="checkedBagLabelCount" type="number" min="1" max="200" value="${pro7.checkedBagLabelCount}"></label></div>`);
      el("labelMode").value=pro7.labelMode;
      renderLabelPositionOptions();
      renderSetLabels();
      el("labelSetSearch").addEventListener("input",renderLabelSetOptions);
      el("labelMode").addEventListener("change",event=>{pro7.labelMode=event.target.value;pro7.labelStartPosition=1;updateLabelModeControls();renderLabelPositionOptions();renderSetLabels()});
      el("checkedBagLabelText").addEventListener("input",event=>{pro7.checkedBagLabelText=clean(event.target.value)||"DURCHSUCHT";renderSetLabels()});
      el("checkedBagLabelCount").addEventListener("input",event=>{pro7.checkedBagLabelCount=Math.min(200,Math.max(1,Number(event.target.value)||1));renderSetLabels()});
      el("labelQrTarget").addEventListener("change",event=>{pro7.labelQrTarget=event.target.value;renderSetLabels()});
      el("labelStartPosition").addEventListener("change",event=>{const capacity=pro7.labelMode==="minifigure-number"?189:8;pro7.labelStartPosition=Math.min(capacity,Math.max(1,Number(event.target.value)||1));renderSetLabels()});
      el("labelBaseUrl").addEventListener("input",event=>{pro7.labelBaseUrl=clean(event.target.value)||location.origin;renderSetLabels()});
      updateLabelModeControls();
    } else if (view === "quality") {
      pro7.quality = (await pro7Get("quality")).data;
      el("pro7Quality").innerHTML = `<section class="panel"><div class="panel-head"><div><p class="eyebrow">PLAUSIBILITÄT</p><h2>Datenqualität</h2></div><button class="btn primary" data-pro7-action="quality-scan">Neu prüfen</button></div>
        <div class="panel-body">${pro7.quality.length ? pro7.quality.map(i=>`<article class="quality-row severity-${esc(i.severity)}"><span>${esc(i.severity)}</span><strong>${esc(i.message)}</strong><small>${esc(i.entity_type)} #${Number(i.entity_id||0)}</small></article>`).join("") :
        pro7Empty("Keine offenen Datenprobleme gefunden.")}</div></section>`;
    } else if (view === "system") {
      if (state.authUser?.role !== "admin") {
        el("pro7System").innerHTML = pro7Empty("Der Systemstatus ist Administratoren vorbehalten.");
        return;
      }
      const data = await pro7Get("system");
      const s = data.system;
      el("pro7System").innerHTML = `<section class="panel"><div class="panel-head"><div><p class="eyebrow">DIAGNOSE</p><h2>Systemstatus</h2></div><span class="status">Betriebsbereit</span></div>
        <div class="system-grid">${Object.entries({
          "Anwendung": `BrickMissing Pro ${s.application_version}`, "Python": s.python_version,
          "Datenbank": s.database, "Schema": `Version ${s.schema_version}`,
          "Freier Speicher": `${(Number(s.free_space)/1073741824).toFixed(1)} GB`,
          "Wartungsmodus": s.settings.maintenance_mode === "true" ? "Aktiv" : "Aus"
        }).map(([k,v])=>`<article><span>${esc(k)}</span><strong>${esc(v)}</strong></article>`).join("")}</div></section>`;
    }
  } catch (error) {
    toast(error.message, true);
  }
}

function renderPro7Inventory() {
  const target = el("pro7InventoryRows");
  if (!target) return;
  const query = clean(el("pro7InventorySearch")?.value).toLowerCase();
  const items = pro7.inventory.filter(x => [x.part_number,x.name,x.color,x.location_name].some(v=>clean(v).toLowerCase().includes(query)));
  target.innerHTML = items.length ? items.map(i=>`<tr><td><strong>${esc(i.part_number)}</strong><small>${esc(i.name)}</small></td><td>${esc(i.color)}</td><td>${esc(i.location_name||"Nicht zugeordnet")}</td>
    <td>${Number(i.quantity)}</td><td>${Number(i.reserved_quantity)}</td><td>${Number(i.available_quantity)}</td><td>${marketMoney(i.unit_price)}</td><td>${marketMoney(Number(i.quantity)*Number(i.unit_price||0))}</td><td><button class="btn" data-pro7-action="adjust-inventory" data-id="${i.id}">Bestand ändern</button></td></tr>`).join("") :
    `<tr><td colspan="9">Keine passenden Inventarteile.</td></tr>`;
}

function renderMinifigures(){
  const target=el("minifigureGrid");
  if(!target)return;
  const query=clean(el("minifigureSearch")?.value).toLowerCase();
  const setFilter=el("minifigureSetFilter")?.value||"all";
  const sort=el("minifigureSort")?.value||"set-asc";
  const missingCount=item=>(item.parts||[]).filter(part=>!Number(part.is_spare)).reduce((sum,part)=>sum+Math.max(Number(part.quantity||1)-Number(part.owned_quantity||0),0),0);
  const items=pro7.minifigures.filter(item=>
    (setFilter==="all"||String(item.set_id)===setFilter)&&
    [item.fig_number,item.name,item.set_number,item.set_name].join(" ").toLowerCase().includes(query)
  ).sort((a,b)=>{
    if(sort==="set-desc")return clean(b.set_number).localeCompare(clean(a.set_number),"de",{numeric:true})||clean(a.name).localeCompare(clean(b.name),"de");
    if(sort==="name-asc")return clean(a.name).localeCompare(clean(b.name),"de",{numeric:true});
    if(sort==="missing-desc")return missingCount(b)-missingCount(a)||clean(a.name).localeCompare(clean(b.name),"de");
    if(sort==="missing-asc")return missingCount(a)-missingCount(b)||clean(a.name).localeCompare(clean(b.name),"de");
    return clean(a.set_number).localeCompare(clean(b.set_number),"de",{numeric:true})||clean(a.name).localeCompare(clean(b.name),"de");
  });
  const groups=new Map();
  items.forEach(item=>{
    const key=String(item.set_id);
    if(!groups.has(key))groups.set(key,{set_number:item.set_number,set_name:item.set_name,figures:[]});
    groups.get(key).figures.push(item);
  });
  const renderPart=part=>{
    const partRequired=Math.max(1,Number(part.quantity||1));
    const partOwned=Math.min(partRequired,Math.max(0,Number(part.owned_quantity||0)));
    const partMissing=Math.max(partRequired-partOwned,0);
    return `<div class="mini-part-row ${partMissing?"is-missing":"is-present"}">
      <div class="mini-part-picture">${part.image_url?`<img class="click-image" data-action="zoom-image" data-src="${esc(proxiedImage(part.image_url))}" src="${esc(proxiedImage(part.image_url))}" alt="${esc(part.name)}" title="Bild vergrößern">`:'<span>–</span>'}</div>
      <div class="mini-part-name"><strong>${esc(part.name)}</strong><small>${esc(part.part_num)}${part.element_id?` · ${esc(part.element_id)}`:""}</small></div>
      <span class="mini-part-color">${esc(part.color_name||"Ohne Farbe")}</span>
      <span class="mini-part-required">${partRequired}×</span>
      <label class="mini-part-owned"><span>Vorhanden</span><input type="number" min="0" max="${partRequired}" value="${partOwned}" data-pro7-minifigure-owned="${part.id}" aria-label="Vorhandene Menge von ${esc(part.name)}"></label>
      <span class="mini-part-result ${partMissing?"missing":"complete"}">${partMissing?`${partMissing} fehlt`:`✓ Komplett`}</span>
      <div class="mini-part-actions"><button type="button" title="Alle vorhanden" data-pro7-action="minifigure-part-all" data-id="${part.id}" class="${partMissing===0?"active":""}">✓</button><button type="button" title="Keine vorhanden" data-pro7-action="minifigure-part-none" data-id="${part.id}" class="${partOwned===0?"active danger":""}">×</button></div>
    </div>`;
  };
  const renderFigure=item=>{
    const parts=item.parts||[];
    const required=parts.filter(part=>!Number(part.is_spare)).reduce((sum,part)=>sum+Number(part.quantity||1),0);
    const owned=parts.filter(part=>!Number(part.is_spare)).reduce((sum,part)=>sum+Math.min(Number(part.owned_quantity||0),Number(part.quantity||1)),0);
    const missing=Math.max(required-owned,0);
    return `<article class="mini-figure-row">
      <div class="mini-figure-summary">
        <div class="mini-figure-picture">${item.image_url?`<img class="click-image" data-action="zoom-image" data-src="${esc(proxiedImage(item.image_url))}" src="${esc(proxiedImage(item.image_url))}" alt="${esc(item.name)}" title="Bild vergrößern">`:'<span>♟</span>'}</div>
        <div class="mini-figure-title"><small>${esc(item.fig_number)}</small><h3>${esc(item.name)}</h3><span>${Number(item.quantity||1)}× im Set</span></div>
        <div class="mini-figure-progress"><strong>${owned}/${required}</strong><span>Teile vorhanden</span><i><b style="width:${required?Math.round(owned/required*100):0}%"></b></i></div>
        <span class="mini-figure-state ${missing?"missing":"complete"}">${missing?`${missing} fehlen`:"✓ Vollständig"}</span>
        <button class="btn mini-edit-button" data-pro7-action="edit-minifigure" data-id="${item.id}">Bearbeiten</button>
      </div>
      <details class="mini-parts-details" data-figure-id="${item.id}"><summary><span>Einzelteile anzeigen</span><b>${parts.length} Positionen</b></summary>
        <div class="mini-parts-table"><div class="mini-parts-head"><span>Bild</span><span>Teil</span><span>Farbe</span><span>Benötigt</span><span>Bestand</span><span>Status</span><span>Aktion</span></div>${parts.length?parts.map(renderPart).join(""):`<div class="empty">Noch keine Einzelteile geladen. Bitte „Von Rebrickable laden“ verwenden.</div>`}</div>
      </details>
    </article>`;
  };
  target.innerHTML=items.length?[...groups.values()].map(group=>`<section class="mini-set-group"><header><div><span class="mini-set-number">SET ${esc(group.set_number)}</span><h2>${esc(group.set_name)}</h2></div><span>${group.figures.length} Minifigur${group.figures.length===1?"":"en"}</span></header><div class="mini-figure-list">${group.figures.map(renderFigure).join("")}</div></section>`).join(""):pro7Empty("Keine passenden Minifiguren vorhanden.",`<button class="btn primary" data-pro7-action="fetch-minifigures">Von Rebrickable laden</button>`);
}

async function updatePro7MinifigurePart(id,payload){
  const scrollPosition=window.scrollY;
  const openFigures=[...document.querySelectorAll(".mini-parts-details[open]")].map(details=>String(details.dataset.figureId));
  const activeFigure=String(document.querySelector(`[data-pro7-minifigure-owned="${Number(id)}"]`)?.closest(".mini-parts-details")?.dataset.figureId||"");
  if(activeFigure&&!openFigures.includes(activeFigure))openFigures.push(activeFigure);
  const result=await request("/api/minifigure-parts/update",{method:"POST",body:JSON.stringify({id:Number(id),...payload})});
  await reloadData();
  pro7.minifigures=(await pro7Get("minifigures")).data;
  renderMinifigures();
  openFigures.forEach(figureId=>{
    const details=document.querySelector(`.mini-parts-details[data-figure-id="${figureId}"]`);
    if(details)details.open=true;
  });
  requestAnimationFrame(()=>window.scrollTo(0,scrollPosition));
  toast(result.set_complete?"Teil gespeichert · Das Set ist jetzt vollständig.":"Minifiguren-Bestand aktualisiert.");
}

async function loadReceipt() {
  const orderId = Number(el("receiptOrder").value);
  if (!orderId) return;
  try {
    const items = (await pro7Get("order-items", `order_id=${orderId}`)).data;
    el("receiptPositions").innerHTML = items.length ? `<form id="receiptForm"><div class="receipt-list">${items.map(i=>`
      <article><strong>${esc(i.part_number)} · ${esc(i.name)}</strong><span>Bestellt: ${Number(i.quantity)}</span>
      <label>Geliefert<input type="number" min="0" max="${Number(i.quantity)}" value="${Number(i.received_quantity)}" data-received="${i.id}"></label>
      <label>Beschädigt<input type="number" min="0" value="${Number(i.damaged_quantity)}" data-damaged="${i.id}"></label>
      <label>Falsch<input type="number" min="0" value="${Number(i.wrong_quantity)}" data-wrong="${i.id}"></label></article>`).join("")}</div>
      <button class="btn primary">Wareneingang buchen</button></form>` :
      pro7Empty("Diese Bestellung besitzt noch keine Positionen. Füge sie in der Bestellverwaltung hinzu.");
    el("receiptForm")?.addEventListener("submit", submitReceipt);
  } catch (error) { toast(error.message, true); }
}

async function submitReceipt(event) {
  event.preventDefault();
  const orderId = Number(el("receiptOrder").value);
  const positions = [...document.querySelectorAll("[data-received]")].map(input=>({
    id:Number(input.dataset.received), received_quantity:Number(input.value),
    damaged_quantity:Number(document.querySelector(`[data-damaged="${input.dataset.received}"]`).value),
    wrong_quantity:Number(document.querySelector(`[data-wrong="${input.dataset.received}"]`).value)
  }));
  await pro7Post({resource:"goods-receipt",order_id:orderId,positions});
  toast("Wareneingang wurde gebucht.");
  await reloadData(); await loadReceipt();
}

function renderLabelSetOptions(){
  const query=clean(el("labelSetSearch")?.value).toLowerCase();
  const sets=state.sets.filter(set=>[set.set_number,set.name,set.theme].join(" ").toLowerCase().includes(query));
  el("labelSetOptions").innerHTML=sets.length?sets.map(set=>`
    <label><input type="checkbox" data-label-set="${set.id}" ${pro7.labelSetIds.has(Number(set.id))?"checked":""}><span><strong>${esc(set.set_number)}</strong><small>${esc(set.name)}</small></span></label>
  `).join(""):pro7Empty("Keine passenden Sets gefunden.");
}

function updateLabelModeControls(){
  const checkedBag=pro7.labelMode==="checked-bag";
  el("checkedBagLabelSettings")?.classList.toggle("hidden",!checkedBag);
  el("labelSetSearch")?.classList.toggle("hidden",checkedBag);
  el("labelSetOptions")?.classList.toggle("hidden",checkedBag);
  el("labelShowImages")?.closest("label")?.classList.toggle("hidden",checkedBag);
  el("labelQrTarget")?.closest("label")?.classList.toggle("hidden",checkedBag);
  el("labelBaseUrl")?.closest("label")?.classList.toggle("hidden",checkedBag);
  document.querySelector('[data-pro7-action="select-all-label-sets"]')?.classList.toggle("hidden",checkedBag);
  const heading=document.querySelector(".label-set-picker-head strong");
  if(heading)heading.textContent=checkedBag?"Kontrolletiketten":"Sets auswählen";
}

function renderLabelPositionOptions(){
  const select=el("labelStartPosition");
  if(!select)return;
  const numberOnly=pro7.labelMode==="minifigure-number";
  const capacity=numberOnly?189:8;
  pro7.labelStartPosition=Math.min(capacity,Math.max(1,Number(pro7.labelStartPosition)||1));
  select.innerHTML=Array.from({length:capacity},(_,index)=>{
    const position=index+1;
    const columns=numberOnly?7:2;
    return `<option value="${position}">Position ${position} · Reihe ${Math.floor(index/columns)+1}, Spalte ${index%columns+1}</option>`;
  }).join("");
  select.value=String(pro7.labelStartPosition);
  const hint=document.querySelector(".label-print-hint");
  if(hint)hint.textContent=numberOnly
    ?"Avery Zweckform 25x10-R: 25,4 × 10 mm · 189 Etiketten · 7 Spalten × 27 Reihen. Beim Drucken 100 % / Tatsächliche Größe verwenden."
    :pro7.labelMode==="checked-bag"
      ?"Kontrolletiketten für durchsuchte Farbsackerln · HERMA 5077, 99,1 × 67,7 mm · beim Drucken 100 % verwenden."
      :"Passend zur bereitgestellten HERMA-Vorlage: A4, Hochformat, Skalierung 100 %, Ränder „Keine“ und Kopf-/Fußzeilen deaktivieren.";
}

function renderSetLabels(){
  const selected=state.sets.filter(set=>pro7.labelSetIds.has(Number(set.id)));
  const checkedBag=pro7.labelMode==="checked-bag";
  const labels=checkedBag
    ?Array.from({length:pro7.checkedBagLabelCount},()=>({checkedBag:true}))
    :pro7.labelMode==="minifigure-number"
    ?selected.flatMap(set=>Array.from({length:Math.max(0,Number(set.minifigure_count||0))},()=>set))
    :selected;
  el("labelSelectionCount").textContent=checkedBag
    ?`${labels.length} Etiketten`
    :pro7.labelMode==="minifigure-number"
    ?`${selected.length} Sets · ${labels.length} Etiketten`
    :`${selected.length} von ${state.sets.length}`;
  const sheets=[];
  const emptyLabelMessage=selected.length&&pro7.labelMode==="minifigure-number"
    ?"Die ausgewählten Sets enthalten keine Minifiguren."
    :"Wähle mindestens ein Set für den Etikettendruck aus.";
  const numberOnly=pro7.labelMode==="minifigure-number";
  const sheetCapacity=numberOnly?189:8;
  const firstOffset=Math.min(sheetCapacity-1,Math.max(0,Number(pro7.labelStartPosition)-1));
  if(labels.length){
    const firstCount=Math.min(sheetCapacity-firstOffset,labels.length);
    sheets.push([...Array(firstOffset).fill(null),...labels.slice(0,firstCount)]);
    for(let index=firstCount;index<labels.length;index+=sheetCapacity)sheets.push(labels.slice(index,index+sheetCapacity));
  }
  el("labelSheets").innerHTML=sheets.length?sheets.map((sheet,page)=>`
    <section class="label-sheet ${numberOnly?"minifigure-number-sheet":""} ${pro7.labelShowImages?"":"hide-label-images"}" aria-label="Etikettenbogen ${page+1}">
      ${sheet.map((set,slot)=>set?(checkedBag?`
        <article class="checked-bag-label" aria-label="${esc(pro7.checkedBagLabelText)}">
          <span class="checked-bag-label-icon">✓</span>
          <strong>${esc(pro7.checkedBagLabelText)}</strong>
          <small>INHALT KONTROLLIERT</small>
        </article>`:pro7.labelMode==="minifigure-number"?`
        <article class="minifigure-number-label" aria-label="Setnummer ${esc(set.set_number)}">
          <strong>${esc(set.set_number)}</strong>
        </article>`:(()=>{const statuses=setLabelStatuses(set),qrTarget=setLabelQrTarget(set);return`
        <article class="set-label">
          <div class="set-label-image">${setImage(set)?`<img src="${esc(setImage(set))}" alt="">`:""}</div>
          <div class="set-label-content">
            <span class="set-label-brand">BRICKMISSING · LEGO SET</span>
            <strong class="set-label-number">${esc(set.set_number)}</strong>
            <h3>${esc(set.name)}</h3>
            <p>${[set.theme,set.year].filter(Boolean).map(esc).join(" · ")||"Sammlung"}</p>
            <div class="set-label-facts">${statuses.map(status=>`<span class="set-label-status status-${status.key}">${status.icon} ${status.label}</span>`).join("")}<span class="set-label-minifigs">♟ ${Number(set.minifigure_count||0)} Minifigur${Number(set.minifigure_count||0)===1?"":"en"}</span></div>
            <div class="set-label-meta"><span>${Number(set.total_parts||0).toLocaleString("de-DE")} Teile</span><span>ID ${Number(set.id)}</span></div>
          </div>
          <div class="set-label-qr"><img src="/api/qr?text=${encodeURIComponent(qrTarget)}" alt="QR-Code"><small>${esc(labelQrTargetName())}</small></div>
        </article>`})()):`<div class="label-slot-empty" aria-label="Freie Etikettenposition ${slot+1}"><span>Position ${slot+1} frei</span></div>`).join("")}
    </section>`).join(""):pro7Empty(emptyLabelMessage);
}

function setLabelStatuses(set){
  const copies=pro7.copies.filter(copy=>Number(copy.set_id)===Number(set.id));
  const conditions=[set.condition,...copies.map(copy=>copy.condition)].map(value=>clean(value).toLowerCase());
  const builds=[set.build_status,...copies.map(copy=>copy.build_status)].map(value=>clean(value).toLowerCase());
  const completeness=[set.completeness,...copies.map(copy=>copy.completeness)].map(value=>clean(value).toLowerCase());
  const statuses=[];
  const hasMissing=Number(set.missing_quantity||0)>0||completeness.some(value=>value.includes("unvoll"));
  const isExplicitlyComplete=completeness.some(value=>
    (value.includes("vollständig")||value.includes("vollstaendig"))
    &&!value.includes("unvoll")
  );
  if(conditions.some(value=>value.includes("versiegelt"))||builds.some(value=>value.includes("versiegelt"))){
    statuses.push({key:"sealed",icon:"●",label:"Versiegelt"});
  }
  if(builds.some(value=>value.includes("zerlegt"))){
    statuses.push({key:"dismantled",icon:"●",label:"Zerlegt"});
  }
  if(hasMissing){
    statuses.push({key:"missing",icon:"●",label:"Fehlteile"});
  }
  if(isExplicitlyComplete&&!hasMissing){
    statuses.push({key:"complete",icon:"✓",label:"Vollständig"});
  }
  if(!statuses.length)statuses.push({key:"complete",icon:"✓",label:"Vollständig"});
  return statuses;
}

function labelQrTargetName(){
  return{set:"Setseite",inventory:"Inventarliste",missing:"Fehlteile",edit:"Bearbeiten",bricklink:"BrickLink",rebrickable:"Rebrickable"}[pro7.labelQrTarget]||"Setseite";
}

function setLabelQrTarget(set){
  const number=clean(set.set_number).includes("-")?clean(set.set_number):`${clean(set.set_number)}-1`;
  if(pro7.labelQrTarget==="bricklink")return`https://www.bricklink.com/v2/catalog/catalogitem.page?S=${encodeURIComponent(number)}`;
  if(pro7.labelQrTarget==="rebrickable")return`https://rebrickable.com/sets/${encodeURIComponent(number)}/`;
  const base=clean(pro7.labelBaseUrl||location.origin).replace(/\/+$/,"");
  return`${base}/?label_action=${encodeURIComponent(pro7.labelQrTarget)}&set_id=${Number(set.id)}`;
}

document.addEventListener("click", async event => {
  const nav = event.target.closest("[data-view]");
  if (nav && pro7Titles[nav.dataset.view]) queueMicrotask(()=>loadPro7View(nav.dataset.view));
  const button = event.target.closest("[data-pro7-action]");
  if (!button) return;
  try {
    const action = button.dataset.pro7Action;
    if (action === "new-copy") {
      openCopyEditor();
    } else if (action === "refresh-copies") {
      const original=button.textContent;
      button.disabled=true;button.textContent="↻ Wird aktualisiert …";
      try{
        const refresh=Date.now();
        const sets=await request(`/api/sets?user_id=${state.userId}&_refresh=${refresh}`);
        state.sets=sets.sets||[];
        await loadPro7View("copies");
        toast(`Set-Exemplare aktualisiert · ${pro7.copies.length} Exemplare geladen.`);
      } finally {
        if(button.isConnected){button.disabled=false;button.textContent=original}
      }
    } else if (action === "edit-copy") {
      openCopyEditor(pro7.copies.find(x=>Number(x.id)===Number(button.dataset.id)));
    } else if (action === "new-moc") {
      const name = prompt("Name des neuen MOCs:");
      if (name) await pro7Post({resource:"moc",name});
      await loadPro7View("mocs");
    } else if (action === "new-inventory") {
      openCentralInventoryEditor();
    } else if (action === "adjust-inventory") {
      const item = pro7.inventory.find(x=>Number(x.id)===Number(button.dataset.id));
      openCentralInventoryEditor(item);
    } else if (action === "new-minifigure") {
      openMinifigureEditor();
    } else if (action === "edit-minifigure") {
      openMinifigureEditor(pro7.minifigures.find(x=>Number(x.id)===Number(button.dataset.id)));
    } else if (action === "minifigure-part-all") {
      await updatePro7MinifigurePart(button.dataset.id,{present:true});
    } else if (action === "minifigure-part-none") {
      await updatePro7MinifigurePart(button.dataset.id,{present:false});
    } else if (action === "fetch-minifigures") {
      const selected=el("minifigureSetFilter")?.value;
      const result=await pro7Post({resource:"minifigures-fetch",set_id:selected&&selected!=="all"?Number(selected):0});
      toast(`${result.imported} Minifiguren wurden den Sets zugeordnet.`);
      await loadPro7View("minifigures");
    } else if (action === "quality-scan") {
      await pro7Post({resource:"quality-scan"}); await loadPro7View("quality");
    } else if (action === "select-all-label-sets") {
      const allSelected=state.sets.length>0&&pro7.labelSetIds.size===state.sets.length;
      pro7.labelSetIds=allSelected?new Set():new Set(state.sets.map(set=>Number(set.id)));
      renderLabelSetOptions();renderSetLabels();
    } else if (action === "print-labels") {
      if(pro7.labelMode!=="checked-bag"&&!pro7.labelSetIds.size){toast("Wähle mindestens ein Set aus.",true);return}
      window.print();
    }
  } catch (error) { toast(error.message, true); }
});

document.addEventListener("change",event=>{
  const ownedInput=event.target.closest("[data-pro7-minifigure-owned]");
  if(ownedInput){
    updatePro7MinifigurePart(ownedInput.dataset.pro7MinifigureOwned,{owned_quantity:Number(ownedInput.value)||0}).catch(error=>toast(error.message,true));
    return;
  }
  if(event.target.id==="labelShowImages"){
    pro7.labelShowImages=event.target.checked;
    renderSetLabels();
    return;
  }
  const input=event.target.closest("[data-label-set]");
  if(!input)return;
  const setId=Number(input.dataset.labelSet);
  input.checked?pro7.labelSetIds.add(setId):pro7.labelSetIds.delete(setId);
  renderSetLabels();
});

function locationOptions(selected){
  return `<option value="">Nicht zugeordnet</option>${state.locations.map(x=>`<option value="${x.id}" ${Number(x.id)===Number(selected)?"selected":""}>${esc(x.name)}</option>`).join("")}`;
}

function openCopyEditor(copy=null){
  if(!state.sets.length){toast("Lege zuerst ein Set an.",true);return}
  el("copyModalTitle").textContent=copy?"Exemplar bearbeiten":"Exemplar anlegen";
  el("copyId").value=copy?.id||"";
  el("copySetId").innerHTML=state.sets.map(s=>`<option value="${s.id}" ${Number(s.id)===Number(copy?.set_id)?"selected":""}>${esc(s.set_number)} · ${esc(s.name)}</option>`).join("");
  el("copyLocationId").innerHTML=locationOptions(copy?.location_id);
  el("copyInventoryNumber").value=copy?.inventory_number||`SET-${state.sets[0].id}-${Date.now().toString().slice(-5)}`;
  el("copySerialNumber").value=copy?.serial_number||"";
  el("copyPurchaseDate").value=clean(copy?.purchase_date).slice(0,10);
  el("copyPurchasePrice").value=Number(copy?.purchase_price||0);
  el("copyCondition").value=copy?.condition||"gebraucht";
  el("copyCompleteness").value=copy?.completeness||"unbekannt";
  el("copyBuildStatus").value=copy?.build_status||"zerlegt vollständig";
  el("copyNotes").value=copy?.notes||"";
  openModal("copyModal");
}

async function saveCopy(event){
  event.preventDefault();
  await pro7Post({
    resource:"copy",id:Number(el("copyId").value)||null,set_id:Number(el("copySetId").value),
    inventory_number:clean(el("copyInventoryNumber").value),serial_number:clean(el("copySerialNumber").value),
    purchase_date:el("copyPurchaseDate").value||null,purchase_price:Number(el("copyPurchasePrice").value)||0,
    location_id:Number(el("copyLocationId").value)||null,condition:el("copyCondition").value,
    completeness:el("copyCompleteness").value,build_status:el("copyBuildStatus").value,
    notes:clean(el("copyNotes").value)
  });
  closeModal("copyModal");toast("Set-Exemplar wurde gespeichert.");await loadPro7View("copies");
}

function openCentralInventoryEditor(item=null){
  el("centralInventoryTitle").textContent=item?"Inventarteil bearbeiten":"Teil anlegen";
  el("centralInventoryId").value=item?.id||"";
  el("centralPartNumber").value=item?.part_number||"";
  el("centralElementId").value=item?.element_id||"";
  el("centralDesignId").value=item?.design_id||"";
  el("centralPartName").value=item?.name||"";
  el("centralPartColor").value=item?.color||"";
  el("legoColors").innerHTML=LEGO_COLORS.map(color=>`<option value="${esc(color)}"></option>`).join("");
  el("centralPartCategory").value=item?.category||"Sonstiges";
  el("centralPartCondition").value=item?.condition||"gebraucht";
  el("centralPartLocation").innerHTML=locationOptions(item?.location_id);
  el("centralPartQuantity").value=Number(item?.quantity||0);
  el("centralPartReserved").value=Number(item?.reserved_quantity||0);
  el("centralPartPurchasePrice").value=Number(item?.purchase_price||0);
  el("centralPartUnitPrice").value=Number(item?.unit_price||0);
  el("centralPartSource").value=item?.source||"";
  el("centralPartImage").value=item?.image_url||"";
  el("centralPartNotes").value=item?.notes||"";
  openModal("centralInventoryModal");
  el("centralPartNumber").focus();
}

function openMinifigureEditor(item=null){
  if(!state.sets.length){toast("Lege zuerst ein Set an.",true);return}
  el("minifigureModalTitle").textContent=item?"Minifigur bearbeiten":"Minifigur hinzufügen";
  el("minifigureId").value=item?.id||"";
  el("minifigureSet").innerHTML=state.sets.map(set=>`<option value="${set.id}" ${Number(set.id)===Number(item?.set_id)?"selected":""}>${esc(set.set_number)} · ${esc(set.name)}</option>`).join("");
  el("minifigureNumber").value=item?.fig_number||"";
  el("minifigureName").value=item?.name||"";
  el("minifigureQuantity").value=Number(item?.quantity||1);
  el("minifigureOwned").value=Number(item?.owned_quantity||0);
  el("minifigureImage").value=item?.image_url||"";
  el("minifigureNotes").value=item?.notes||"";
  openModal("minifigureModal");
}

async function saveMinifigure(event){
  event.preventDefault();
  await pro7Post({
    resource:"minifigure",id:Number(el("minifigureId").value)||null,
    set_id:Number(el("minifigureSet").value),fig_number:clean(el("minifigureNumber").value),
    name:clean(el("minifigureName").value),quantity:Number(el("minifigureQuantity").value)||1,
    owned_quantity:Number(el("minifigureOwned").value)||0,
    image_url:clean(el("minifigureImage").value),notes:clean(el("minifigureNotes").value)
  });
  closeModal("minifigureModal");toast("Minifigur wurde gespeichert.");await loadPro7View("minifigures");
}

async function saveCentralInventory(event){
  event.preventDefault();
  const quantity=Number(el("centralPartQuantity").value);
  const reserved_quantity=Number(el("centralPartReserved").value);
  if(reserved_quantity>quantity) throw new Error("Die reservierte Menge darf den Gesamtbestand nicht übersteigen.");
  await pro7Post({
    resource:"inventory",id:Number(el("centralInventoryId").value)||null,
    part_number:clean(el("centralPartNumber").value),element_id:clean(el("centralElementId").value),
    design_id:clean(el("centralDesignId").value),name:clean(el("centralPartName").value),
    color:clean(el("centralPartColor").value),category:el("centralPartCategory").value,
    condition:el("centralPartCondition").value,location_id:Number(el("centralPartLocation").value)||null,
    quantity,reserved_quantity,purchase_price:Number(el("centralPartPurchasePrice").value)||0,
    unit_price:Number(el("centralPartUnitPrice").value)||0,source:clean(el("centralPartSource").value),
    image_url:clean(el("centralPartImage").value),notes:clean(el("centralPartNotes").value),
    movement_type:"Korrektur"
  });
  closeModal("centralInventoryModal");toast("Inventarteil wurde gespeichert.");await loadPro7View("inventory");
}

el("copyForm").addEventListener("submit",event=>saveCopy(event).catch(error=>toast(error.message,true)));
el("centralInventoryForm").addEventListener("submit",event=>saveCentralInventory(event).catch(error=>toast(error.message,true)));
el("minifigureForm").addEventListener("submit",event=>saveMinifigure(event).catch(error=>toast(error.message,true)));

document.addEventListener("keydown", event => {
  if (["INPUT","TEXTAREA","SELECT"].includes(document.activeElement?.tagName)) return;
  if (event.key.toLowerCase() === "t") { event.preventDefault(); setView("inventory"); loadPro7View("inventory"); }
  if (event.key.toLowerCase() === "b") { event.preventDefault(); setView("orders"); }
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(()=>{}));
}
