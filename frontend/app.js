"use strict";
const state={users:[],settings:{},authUser:null,audit:[],sets:[],parts:[],shopping:[],dashboard:{},notes:[],userId:1,inventorySetId:null,inventory:[],inventoryTotals:{},inventoryMinifigures:[],inventorySelectedColors:new Set(),partsSelectedColors:new Set(),warehouse:[],locations:[],orders:[],trash:{parts:[],sets:[]},selectedParts:new Set(),dirtyForms:new Set()};
const PARTS_PER_PAGE=25;
let partsPage=1;
const partsColorStorageKey=()=>`brickmissing.parts.colors.v1.user-${Number(state.userId)||0}`;
function partsColorSelections(){try{const value=JSON.parse(state.settings.parts_color_filter||"{}");return value&&typeof value==="object"&&!Array.isArray(value)?value:{}}catch{return {}}}
function savePartsColorSelection(){
  const selections=partsColorSelections();
  selections[String(state.userId)]=[...state.partsSelectedColors];
  state.settings.parts_color_filter=JSON.stringify(selections);
  try{localStorage.setItem(partsColorStorageKey(),JSON.stringify([...state.partsSelectedColors]))}catch{}
  savePartsColorSelection.pending=(savePartsColorSelection.pending||Promise.resolve()).catch(()=>{}).then(()=>request("/api/settings",{method:"POST",keepalive:true,body:JSON.stringify({settings:{parts_color_filter:state.settings.parts_color_filter}})})).catch(error=>toast("Farbauswahl konnte nicht gespeichert werden: "+error.message,true));
  return savePartsColorSelection.pending;
}
function loadPartsColorSelection(){
  const databaseSelection=partsColorSelections()[String(state.userId)];
  let stored=databaseSelection;
  if(!Array.isArray(stored)){try{stored=JSON.parse(localStorage.getItem(partsColorStorageKey())||"[]")}catch{stored=[]}}
  state.partsSelectedColors=new Set(Array.isArray(stored)?stored.map(clean).filter(Boolean):[]);
}

function toast(message,error=false){
  el("toast").textContent=message;
  el("toast").classList.add("show");
  el("diagAction").textContent=message;
  clearTimeout(toast.timer);
  toast.timer=setTimeout(()=>el("toast").classList.remove("show"),2800);
  console[error?"error":"log"](message);
}

async function request(url,options={}){
  request.pending=(request.pending||0)+1;
  setBusy(true);
  try{
    const response=await fetch(url,{cache:"no-store",headers:{"Content-Type":"application/json",...(state.authUser?.csrf_token?{"X-CSRF-Token":state.authUser.csrf_token}:{}),...(options.headers||{})},...options});
    const type=response.headers.get("content-type")||"";
    const data=type.includes("application/json")?await response.json():await response.text();
    if(response.status===401&&!url.startsWith("/api/auth/")){
      state.authUser=null;
      el("app").classList.add("hidden");
      el("authPage").classList.remove("hidden");
      setAuthMode("login");
    }
    if(!response.ok||data?.ok===false){
      const html=typeof data==="string"&&(/<!doctype html/i.test(data)||/<html[\s>]/i.test(data));
      const fallback=response.status===404
        ?"Die angeforderte Funktion wurde vom laufenden BrickMissing-Server nicht gefunden. Bitte BrickMissing neu starten."
        :`Die Anfrage ist fehlgeschlagen (HTTP ${response.status}).`;
      const error=new Error(data?.error||data?.message||(html?fallback:data)||fallback);
      error.code=data?.code||`HTTP_${response.status}`;
      throw error;
    }
    return data;
  }catch(error){if(error instanceof TypeError)throw new Error("Der lokale BrickMissing-Server ist nicht erreichbar.");throw error}
  finally{request.pending=Math.max(0,request.pending-1);if(!request.pending)setBusy(false)}
}

function openModal(id){el(id).classList.remove("hidden")}
function closeModal(id){el(id).classList.add("hidden")}

function setView(name){
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  el("view-"+name).classList.add("active");
  document.querySelectorAll("#mainNav [data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===name));
  el("pageTitle").textContent={dashboard:"Dashboard",parts:"Fehlteile",sets:"Sets",shopping:"Einkaufsliste",stats:"Statistiken",warehouse:"Lager",orders:"Bestellungen",notes:"Notizen",workshop:"Sammlungswerkstatt",trash:"Papierkorb",settings:"Einstellungen",admin:"Administration"}[name]||"BrickMissing";
}

async function bootstrap(){
  const data=await request("/api/bootstrap");
  state.users=data.users;
  state.settings=data.settings||{};
  state.authUser=data.auth_user||null;
  state.userId=Number(state.settings.current_user||state.users[0]?.id||1);
  loadPartsColorSelection();
  applyAppearance();
  el("rebrickableKey").value="";
  el("apiKeyStatus").textContent=state.settings.rebrickable_api_key_configured?"Ein eigener API-Key ist sicher hinterlegt. Er wird nicht angezeigt.":"Für dein Konto ist noch kein API-Key gespeichert.";
  const isAdmin=data.permissions?.is_admin===true||state.authUser?.role==="admin";
  document.querySelectorAll('[data-action="quit"],[data-action="open-user"],[data-action="delete-user"]').forEach(node=>node.classList.toggle("hidden",!isAdmin));
  el("adminNavButton").classList.toggle("hidden",!isAdmin);
  el("adminUserSwitcher").classList.toggle("hidden",!isAdmin);
  renderUsers();
  if(isAdmin){await Promise.all([loadAudit(),loadMariaAdmin(),loadEmailAdmin(),loadPricingAdmin()]);renderAdminUsers()}
  await reloadData();
  const requestedLocation=Number(new URLSearchParams(location.search).get("warehouse_location"));
  if(requestedLocation&&state.locations.some(x=>Number(x.id)===requestedLocation)){
    setView("warehouse");el("warehouseSearch").value=locationPath(requestedLocation);renderWarehouse();
  }
  const labelParams=new URLSearchParams(location.search);
  const labelAction=labelParams.get("label_action");
  const labelSetId=Number(labelParams.get("set_id"));
  const labelSet=state.sets.find(set=>Number(set.id)===labelSetId);
  if(labelSet){
    if(labelAction==="set"||labelAction==="inventory")await openInventory(labelSetId);
    else if(labelAction==="missing"){setView("parts");el("partSetFilter").value=String(labelSetId);partsPage=1;renderParts()}
    else if(labelAction==="edit")openSet(labelSet);
    else{setView("sets");el("setSearch").value=labelSet.set_number;renderSets()}
  }
  el("diagServer").textContent="Verbunden";
  if(state.authUser?.must_change_password){setView("settings");toast("Bitte zuerst das temporäre Passwort ändern.",true);el("currentPassword").focus()}
}

function renderUsers(){
  el("userSelect").innerHTML=state.users.map(u=>`<option value="${u.id}" ${Number(u.id)===state.userId?"selected":""}>${esc(u.name)}</option>`).join("");
}

async function reloadData(){
  const [sets,parts,dashboard,shopping,warehouse,orders,trash,notes]=await Promise.all([
    request(`/api/sets?user_id=${state.userId}`),
    request(`/api/parts?user_id=${state.userId}`),
    request(`/api/dashboard?user_id=${state.userId}`),
    request(`/api/shopping?user_id=${state.userId}`),request(`/api/warehouse?user_id=${state.userId}`),request(`/api/orders?user_id=${state.userId}`),request(`/api/trash?user_id=${state.userId}`),request(`/api/notes?user_id=${state.userId}`)
  ]);
  state.sets=sets.sets;
  state.parts=parts.parts;
  state.dashboard=dashboard.dashboard;
  state.shopping=shopping.shopping;state.warehouse=warehouse.warehouse;state.locations=warehouse.locations||[];state.orders=orders.orders;state.trash=trash;state.notes=notes.notes||[];
  renderAdvancedFilterOptions();
  renderAll();
}

async function refreshPartsView(){
  const refresh=Date.now();
  const [sets,parts]=await Promise.all([
    request(`/api/sets?user_id=${state.userId}&_refresh=${refresh}`),
    request(`/api/parts?user_id=${state.userId}&_refresh=${refresh}`)
  ]);
  state.sets=sets.sets||[];
  state.parts=parts.parts||[];
  state.selectedParts.clear();
  renderAdvancedFilterOptions();
  renderParts();
  renderSets();
  renderSetOptions();
  renderMobileCards();
  renderFilterChips();
  return state.parts.length;
}

function renderAll(){renderDashboard();renderParts();renderSets();renderShopping();renderSetOptions();renderWarehouse();renderOrders();renderNotes();renderTrash()}

function renderNotes(){const q=clean(el("noteSearch")?.value).toLowerCase();const list=state.notes.filter(note=>`${note.title} ${note.content}`.toLowerCase().includes(q));el("notesList").innerHTML=list.length?list.map(note=>`<article class="note-card"><header><h3>${esc(note.title)}</h3><span>${esc(note.updated_at||"")}</span></header><p>${esc(note.content).replace(/\n/g,"<br>")}</p><footer><button type="button" class="btn" data-action="edit-note" data-id="${note.id}">Bearbeiten</button><button type="button" class="btn danger" data-action="delete-note" data-id="${note.id}">Löschen</button></footer></article>`).join(""):`<div class="empty">${q?"Keine passende Notiz gefunden.":"Noch keine Notiz gespeichert."}</div>`}
function resetNoteEditor(){el("noteForm").reset();el("noteId").value="";el("noteEditorHeading").textContent="Neue Notiz";el("noteSaveState").textContent="Noch nicht gespeichert"}
function editNote(id){const note=state.notes.find(item=>String(item.id)===String(id));if(!note)return;el("noteId").value=note.id;el("noteTitle").value=note.title;el("noteContent").value=note.content;el("noteEditorHeading").textContent="Notiz bearbeiten";el("noteSaveState").textContent=`Zuletzt gespeichert: ${note.updated_at||"–"}`;el("noteTitle").focus()}
async function saveNote(event){event.preventDefault();const data=await request("/api/notes",{method:"POST",body:JSON.stringify({user_id:state.userId,id:clean(el("noteId").value)||null,title:clean(el("noteTitle").value),content:el("noteContent").value.trim()})});state.notes=data.notes||[];renderNotes();resetNoteEditor();toast("Notiz gespeichert.")}
async function deleteNote(id){if(!confirm("Diese Notiz wirklich löschen?"))return;const data=await request(`/api/notes/${id}`,{method:"DELETE"});state.notes=data.notes||[];renderNotes();if(String(el("noteId").value)===String(id))resetNoteEditor();toast("Notiz gelöscht.")}

function renderDashboard(){
  const d=state.dashboard;
  el("statSets").textContent=d.sets||0;
  el("statMissing").textContent=d.missing||0;
  el("statOrdered").textContent=d.ordered||0;
  el("statCost").textContent=`${Number(d.cost||0).toFixed(2).replace(".",",")} €`;
  const collectionValue=state.sets.reduce((s,x)=>s+Number(x.current_value||0),0);el("statValue").textContent=collectionValue?collectionValue.toLocaleString("de-DE",{style:"currency",currency:"EUR"}):"Noch nicht ermittelt";el("statDone").textContent=(d.entries?Math.round(Number(d.done||0)/Number(d.entries)*100):0)+"%";
  renderBars("statusBars",(d.status||[]).map(x=>({label:labelStatus(x.status),value:x.value})));
  renderBars("colorBars",(d.colors||[]).map(x=>({label:x.color||"Ohne Farbe",value:x.value})));
  renderBars("statsStatus",(d.status||[]).map(x=>({label:labelStatus(x.status),value:x.value})));
  renderBars("statsColors",(d.colors||[]).map(x=>({label:x.color||"Ohne Farbe",value:x.value})));
}

function renderBars(id,data){
  const max=Math.max(1,...data.map(x=>Number(x.value)));
  el(id).innerHTML=data.map(x=>`<div class="bar"><span>${esc(x.label)}</span><div class="track"><i style="width:${Number(x.value)/max*100}%"></i></div><strong>${x.value}</strong></div>`).join("")||`<div class="empty">Keine Daten</div>`;
}

function labelStatus(status){return {missing:"Fehlt",found:"Gefunden",ordered:"Bestellt",shipped:"Versendet",received:"Erhalten",installed:"Eingebaut"}[status]||status}
const PART_STATUSES=["missing","found","ordered","shipped","received","installed"];
function partStatusOptions(current){return PART_STATUSES.map(status=>`<option value="${status}" ${status===current?"selected":""}>${labelStatus(status)}</option>`).join("")}

function proxiedImage(url){
  const value=clean(url);
  return value?`/api/image?url=${encodeURIComponent(value)}`:"";
}

function imageFailed(image,label="Bild"){
  image.removeAttribute("src");
  image.classList.add("image-unavailable");
  const parent=image.parentElement;
  if(parent&&!parent.querySelector(".image-placeholder")){
    parent.insertAdjacentHTML("beforeend",`<span class="image-placeholder" aria-label="${esc(label)} nicht verfügbar">Kein Bild</span>`);
  }
}

function partImage(part){
  const url=part.image_url||`https://www.lego.com/cdn/product-assets/element.img.lod5photo.192x192/${encodeURIComponent(part.element_id)}.jpg`;
  return proxiedImage(url);
}

function partDimensionValue(value){
  const text=clean(value).replace(",",".");
  if(text.includes(" "))return text.split(/\s+/).reduce((sum,item)=>sum+partDimensionValue(item),0);
  if(text.includes("/")){const [top,bottom]=text.split("/").map(Number);return bottom?top/bottom:0}
  return Number(text)||0;
}

function partSizeScore(part){
  const text=clean(part.name);
  const number="(\\d+(?:[.,]\\d+)?(?:\\s+\\d+\\/\\d+)?|\\d+\\/\\d+)";
  const dimensions=text.match(new RegExp(`${number}\\s*[x×]\\s*${number}(?:\\s*[x×]\\s*${number})?`,"i"));
  if(dimensions){
    const values=[dimensions[1],dimensions[2],dimensions[3]].filter(Boolean).map(partDimensionValue).filter(value=>value>0);
    if(values.length>=2)return values.reduce((product,value)=>product*value,1);
  }
  const diameter=text.match(/(?:ø|diameter\s*)\s*(\d+(?:[.,]\d+)?)\s*mm/i)||text.match(/(\d+(?:[.,]\d+)?)\s*mm/i);
  if(diameter){const studs=partDimensionValue(diameter[1])/8;return studs*studs}
  const length=text.match(/(\d+(?:[.,]\d+)?)\s*l\b/i);
  if(length)return partDimensionValue(length[1]);
  return 1;
}

function filteredParts(){
  const q=clean(el("searchInput").value).toLowerCase();
  const status=el("statusFilter").value;
  const shape=clean(el("shapeFilter")?.value).toLowerCase();
  const setId=el("partSetFilter")?.value||"all";
  const partType=el("partTypeFilter")?.value||"all";
  const rarity=el("rarityFilter")?.value||"all";
  const sort=el("sortSelect").value;
  const occurrences=new Map();
  state.parts.forEach(p=>{const key=(clean(p.element_id)||clean(p.design_id)||clean(p.name).toLowerCase())+"\u0000"+clean(p.color).toLowerCase();occurrences.set(key,(occurrences.get(key)||0)+1)});
  const arr=state.parts.filter(p=>{
    const key=(clean(p.element_id)||clean(p.design_id)||clean(p.name).toLowerCase())+"\u0000"+clean(p.color).toLowerCase();
    const count=occurrences.get(key)||1;
    const rarityMatch=rarity==="all"||(rarity==="rare"&&count===1)||(rarity==="uncommon"&&count>=2&&count<=3)||(rarity==="common"&&count>=4);
    const isMinifigurePart=clean(p.notes).toLowerCase().includes("minifigur");
    const typeMatch=partType==="all"||(partType==="minifigure"&&isMinifigurePart)||(partType==="regular"&&!isMinifigurePart);
    const colorMatch=!state.partsSelectedColors.size||state.partsSelectedColors.has(clean(p.color)||"Ohne Farbe");
    return (status==="all"||p.status===status)&&colorMatch&&(!shape||[p.name,p.design_id].join(" ").toLowerCase().includes(shape))&&(setId==="all"||String(p.set_id||"none")===setId)&&typeMatch&&rarityMatch&&[p.name,p.element_id,p.design_id,p.color,p.set_name,p.set_number,p.supplier,p.notes].join(" ").toLowerCase().includes(q);
  });
  arr.sort((a,b)=>sort==="name"?clean(a.name).localeCompare(clean(b.name)):sort==="set"?clean(a.set_number).localeCompare(clean(b.set_number),undefined,{numeric:true}):sort==="quantity"?Number(b.quantity)-Number(a.quantity):sort==="size-desc"?partSizeScore(b)-partSizeScore(a)||clean(a.name).localeCompare(clean(b.name)):sort==="size-asc"?partSizeScore(a)-partSizeScore(b)||clean(a.name).localeCompare(clean(b.name)):clean(b.updated_at).localeCompare(clean(a.updated_at)));
  return arr;
}

function renderAdvancedFilterOptions(){
  const preserve=(select,html)=>{if(!select)return;const value=select.value;select.innerHTML=html;if([...select.options].some(x=>x.value===value))select.value=value};
  renderPartsColorFilter();
  preserve(el("partSetFilter"),`<option value="all">Alle Sets</option><option value="none">Ohne Set</option>`+state.sets.map(x=>`<option value="${x.id}">${esc(x.set_number)} – ${esc(x.name)}</option>`).join(""));
  preserve(el("setYearFilter"),`<option value="all">Alle Jahre</option>`+[...new Set(state.sets.map(x=>x.year).filter(Boolean))].sort((a,b)=>b-a).map(x=>`<option value="${x}">${x}</option>`).join(""));
}

const COLOR_FAMILIES=[["Black",/black/i],["White",/white/i],["Gray",/gr[ae]y/i],["Red",/(?:red|coral)/i],["Orange",/orange/i],["Yellow",/(?:yellow|gold)/i],["Green",/(?:green|lime|olive|aqua|turquoise|teal)/i],["Blue",/blue/i],["Purple",/(?:purple|violet|lavender)/i],["Pink",/(?:pink|magenta)/i],["Brown / Tan",/(?:brown|tan|nougat|flesh|copper)/i],["Trans",/(?!)/],["Metallic",/(?!)/]];
function colorFamily(name){if(/(?:^|[\s-])trans(?:[\s-]|$)|\btransparent\b|\bclear\b/i.test(name))return "Trans";if(/\b(?:flat silver|silver|chrome|metallic|pearl)\b/i.test(name))return "Metallic";return COLOR_FAMILIES.find(([,pattern])=>pattern.test(name))?.[0]||"Weitere Farben"}
function colorShadeRank(name,family){const value=clean(name).toLowerCase();if(value===family.toLowerCase()||(family==="Gray"&&/^(?:gray|grey)$/.test(value)))return 0;if(/\bdark\b/.test(value))return 1;if(/\bsand\b/.test(value))return 2;if(/\blight\b/.test(value))return 3;if(/\bbright\b/.test(value))return 4;if(/\bmedium\b/.test(value))return 5;if(/\btransparent\b|\btrans[- ]/.test(value))return 6;return 7}
function sortedColorGroups(values){const order=new Map(COLOR_FAMILIES.map(([name],index)=>[name,index]));order.set("Weitere Farben",COLOR_FAMILIES.length);return [...values].sort((a,b)=>{const familyA=colorFamily(a),familyB=colorFamily(b);return (order.get(familyA)-order.get(familyB))||colorShadeRank(a,familyA)-colorShadeRank(b,familyB)||a.localeCompare(b,"en",{numeric:true})}).reduce((groups,color)=>{const family=colorFamily(color);(groups[family]??=[]).push(color);return groups},{})}
function updatePartsColorSummary(){const count=state.partsSelectedColors.size;el("partsColorSummary").textContent=count?`${count} Farbe${count===1?"":"n"} ausgewählt`:"Alle Farben"}
function renderPartsColorFilter(){const colors=[...new Set(state.parts.map(part=>clean(part.color)||"Ohne Farbe"))];state.partsSelectedColors=new Set([...state.partsSelectedColors].filter(color=>colors.includes(color)));savePartsColorSelection();const groups=sortedColorGroups(colors);el("partsColorOptions").innerHTML=Object.entries(groups).map(([family,items])=>`<section><strong>${esc(family)}</strong>${items.map(color=>`<label><input type="checkbox" data-parts-color="${esc(color)}" ${state.partsSelectedColors.has(color)?"checked":""}><span>${esc(color)}</span></label>`).join("")}</section>`).join("")||'<div class="sub">Keine Farben verfügbar</div>';updatePartsColorSummary()}

function groupedParts(){
  const groups=new Map();
  filteredParts().forEach(part=>{
    const identity=clean(part.element_id)||clean(part.design_id)||clean(part.name).toLowerCase();
    const key=[identity,clean(part.color).toLowerCase(),clean(part.status)].join("\u0000");
    if(!groups.has(key))groups.set(key,{...part,ids:[],quantity:0,unassigned_found_quantity:0,total_cost:0,sets:[],set_entries:[],entry_count:0});
    const group=groups.get(key);
    group.ids.push(Number(part.id));
    group.quantity+=Number(part.quantity)||0;
    group.unassigned_found_quantity+=Number(part.unassigned_found_quantity)||0;
    group.total_cost+=(Number(part.quantity)||0)*(Number(part.unit_price)||0);
    group.entry_count+=1;
    const setLabel=[part.set_number,part.set_name].filter(Boolean).join(" – ")||"Ohne Set";
    if(!group.sets.includes(setLabel))group.sets.push(setLabel);
    group.set_entries.push({
      id:Number(part.id),
      label:setLabel,
      set_id:Number(part.set_id)||null,
      required_quantity:Math.max(1,Number(part.quantity)||1),
      owned_quantity:Math.max(0,Math.min(Number(part.quantity)||1,Number(part.owned_quantity)||0)),
      is_present:Boolean(Number(part.is_present)),
    });
  });
  const rows=[...groups.values()];
  const sort=el("sortSelect").value;
  if(sort==="cost-asc"||sort==="cost-desc"){
    const direction=sort==="cost-asc"?1:-1;
    rows.sort((a,b)=>{
      const aHasPrice=Number(a.total_cost)>0;
      const bHasPrice=Number(b.total_cost)>0;
      if(aHasPrice!==bHasPrice)return aHasPrice?-1:1;
      return direction*(Number(a.total_cost)-Number(b.total_cost))
        ||clean(a.name).localeCompare(clean(b.name));
    });
  }else if(sort==="size-asc"||sort==="size-desc"){
    const direction=sort==="size-asc"?1:-1;
    rows.sort((a,b)=>direction*(partSizeScore(a)-partSizeScore(b))||clean(a.name).localeCompare(clean(b.name)));
  }else if(sort==="quantity"){
    rows.sort((a,b)=>Number(b.quantity)-Number(a.quantity)||clean(a.name).localeCompare(clean(b.name)));
  }
  return rows;
}

function updateBulkSelectionUi(){
  const visibleIds=currentPartGroups().flatMap(group=>group.ids);
  const selectedVisible=visibleIds.filter(id=>state.selectedParts.has(id)).length;
  const checkbox=el("selectAllMissingParts");
  if(checkbox){
    checkbox.checked=visibleIds.length>0&&selectedVisible===visibleIds.length;
    checkbox.indeterminate=selectedVisible>0&&selectedVisible<visibleIds.length;
    checkbox.disabled=visibleIds.length===0;
  }
  document.querySelectorAll("[data-part-ids]").forEach(input=>{
    const ids=input.dataset.partIds.split(",").map(Number);
    const selected=ids.filter(id=>state.selectedParts.has(id)).length;
    input.checked=selected===ids.length;
    input.indeterminate=selected>0&&selected<ids.length;
  });
  el("bulkBar").classList.toggle("hidden",state.selectedParts.size===0);
  el("bulkCount").textContent=`${state.selectedParts.size} ausgewählt`;
}

function toggleAllVisibleParts(checked){
  currentPartGroups().flatMap(group=>group.ids).forEach(id=>{
    checked?state.selectedParts.add(id):state.selectedParts.delete(id);
  });
  renderParts();
}

function currentPartGroups(){
  const rows=groupedParts();
  const pages=Math.max(1,Math.ceil(rows.length/PARTS_PER_PAGE));
  partsPage=Math.min(Math.max(1,partsPage),pages);
  return rows.slice((partsPage-1)*PARTS_PER_PAGE,partsPage*PARTS_PER_PAGE);
}

function renderParts(){
  const allRows=groupedParts();
  const pages=Math.max(1,Math.ceil(allRows.length/PARTS_PER_PAGE));
  partsPage=Math.min(Math.max(1,partsPage),pages);
  const rows=allRows.slice((partsPage-1)*PARTS_PER_PAGE,partsPage*PARTS_PER_PAGE);
  const pageButtons=Array.from({length:pages},(_,index)=>index+1).filter(page=>pages<=7||page===1||page===pages||Math.abs(page-partsPage)<=1);
  const pager=pages>1?`<nav class="pagination" aria-label="Seiten der Fehlteileliste"><button class="icon-btn" data-action="parts-page" data-page="${partsPage-1}" ${partsPage===1?"disabled":""}>← Zurück</button><span>${pageButtons.map((page,index)=>`${index&&page-pageButtons[index-1]>1?'<i>…</i>':""}<button class="page-button ${page===partsPage?"active":""}" data-action="parts-page" data-page="${page}" aria-current="${page===partsPage?"page":"false"}">${page}</button>`).join("")}</span><small>Seite ${partsPage} von ${pages} · ${allRows.length} gruppierte Teile</small><button class="icon-btn" data-action="parts-page" data-page="${partsPage+1}" ${partsPage===pages?"disabled":""}>Weiter →</button></nav>`:"";
  el("partsTable").innerHTML=allRows.length?`<table><thead><tr><th><input type="checkbox" id="selectAllMissingParts" class="part-check" title="Diese Seite auswählen" aria-label="Alle Fehlteile dieser Seite auswählen"></th><th>Bild</th><th>Teil</th><th>Set</th><th>Gesamtmenge</th><th>Status</th><th>Kosten</th><th></th></tr></thead><tbody>${rows.map(p=>`<tr><td><input class="part-check" type="checkbox" data-part-ids="${p.ids.join(",")}" aria-label="${p.entry_count} gruppierte Einträge auswählen"></td><td><div class="thumb"><img class="click-image" data-action="zoom-image" data-src="${esc(partImage(p))}" src="${esc(partImage(p))}"></div></td><td><strong>${esc(p.name)}</strong><div class="sub">Element ${esc(p.element_id)}${p.color?" · "+esc(p.color):""}${p.entry_count>1?" · "+p.entry_count+" Einträge gruppiert":""}</div></td><td>${p.sets.map(esc).join("<br>")}</td><td><div class="group-quantity-control"><strong>${p.quantity}× benötigt</strong><label><span>Gefunden, nicht zugeordnet</span><input type="number" min="0" value="${p.unassigned_found_quantity}" data-action="unassigned-found" data-ids="${p.ids.join(",")}" aria-label="Unzugeordnet gefundene Menge für ${esc(p.name)}"></label></div></td><td><select class="part-status-select status-${esc(p.status)}" data-part-status-ids="${p.ids.join(",")}" aria-label="Status für ${esc(p.name)}">${partStatusOptions(p.status)}</select></td><td>${p.total_cost>0?`${p.total_cost.toFixed(2).replace(".",",")} €`:'<span class="price-unavailable">Teil wird nicht mehr verkauft</span>'}</td><td><div class="row-actions"><button class="icon-btn" data-action="history-part" data-id="${p.id}">Verlauf</button><button class="icon-btn" data-action="edit-part" data-id="${p.id}" title="${p.entry_count>1?"Ersten Eintrag bearbeiten":"Bearbeiten"}">Bearbeiten</button><button class="icon-btn" data-action="delete-part-group" data-ids="${p.ids.join(",")}">×</button></div></td></tr>`).join("")}</tbody></table>${pager}`:`<div class="empty">Noch keine Fehlteile vorhanden.</div>`;
  renderPartPresenceControls(rows);
  requestAnimationFrame(updateBulkSelectionUi);
}

function renderPartPresenceControls(rows){
  const table=el("partsTable").querySelector("table");
  if(!table)return;
  const setMissingTotals=new Map();
  state.parts.forEach(part=>{if(!part.set_id||["found","received","installed"].includes(part.status))return;const remaining=Math.max((Number(part.quantity)||1)-(Number(part.owned_quantity)||0),0);setMissingTotals.set(Number(part.set_id),(setMissingTotals.get(Number(part.set_id))||0)+remaining)});
  const setHeader=table.querySelector("thead th:nth-child(4)");
  if(setHeader)setHeader.textContent="Set und vorhanden";
  table.querySelectorAll("tbody tr").forEach((row,index)=>{
    const group=rows[index];
    const cell=row.children[3];
    if(!group||!cell)return;
    cell.innerHTML=`<div class="part-presence-list">${group.set_entries.map(entry=>{const missing=Math.max(entry.required_quantity-entry.owned_quantity,0);return`
      <div class="part-presence ${missing===0?"is-present":""}">
        <div class="part-presence-set"><strong>${esc(entry.label)}</strong><small>${missing} von ${entry.required_quantity} fehlen · Set gesamt: ${entry.set_id?(setMissingTotals.get(entry.set_id)||0):missing} Teile fehlen</small></div>
        <label class="part-owned-control"><span>Vorhanden</span><input type="number" min="0" max="${entry.required_quantity}" value="${entry.owned_quantity}" data-action="part-owned" data-id="${entry.id}" aria-label="Vorhandene Menge für ${esc(entry.label)}"></label>
        <div class="part-presence-actions"><small class="part-presence-state">${missing===0?"Vollständig":`${missing} fehlt${missing===1?"":"en"}`}</small><button type="button" class="icon-btn part-entry-edit" data-action="edit-part" data-id="${entry.id}">Bearbeiten</button></div>
      </div>`}).join("")}</div>`;
  });
}

function setImage(set){
  if(set.image_url)return proxiedImage(set.image_url);
  const num=clean(set.set_number).includes("-")?clean(set.set_number):clean(set.set_number)+"-1";
  return proxiedImage(`https://images.brickset.com/sets/large/${encodeURIComponent(num)}.jpg`);
}

function rebrickableSetUrl(setNumber){
  const number=clean(setNumber);
  const normalized=number.includes("-")?number:number+"-1";
  return `https://rebrickable.com/sets/${encodeURIComponent(normalized)}/`;
}

function renderSets(){const q=clean(el("setSearch")?.value).toLowerCase();const f=el("setFilter")?.value||"all";const year=el("setYearFilter")?.value||"all";const sort=el("setSort")?.value||"newest";const isComplete=s=>Number(s.missing_quantity||0)===0;const list=state.sets.filter(s=>[s.set_number,s.name,s.theme].join(" ").toLowerCase().includes(q)&&(year==="all"||String(s.year)===year)&&(f==="all"||(f==="favorite"&&s.favorite)||(f==="incomplete"&&!isComplete(s))||(f==="complete"&&isComplete(s)))).sort((a,b)=>{if(sort==="oldest")return Number(a.id)-Number(b.id);if(sort==="complete-first")return Number(isComplete(b))-Number(isComplete(a))||Number(b.id)-Number(a.id);if(sort==="incomplete-first")return Number(isComplete(a))-Number(isComplete(b))||Number(b.id)-Number(a.id);if(sort==="number-asc")return clean(a.set_number).localeCompare(clean(b.set_number),"de",{numeric:true});if(sort==="number-desc")return clean(b.set_number).localeCompare(clean(a.set_number),"de",{numeric:true});return Number(b.id)-Number(a.id);});
  el("setGrid").innerHTML=list.map(s=>{const pct=Number(s.positions)?Math.round(Number(s.done_positions)/Number(s.positions)*100):0;const purchase=Number(s.purchase_price||0);const value=Number(s.current_value||0);return`<article class="set-card"><div class="set-image"><img class="click-image" data-action="zoom-image" data-src="${esc(setImage(s))}" src="${esc(setImage(s))}"></div><div class="set-body"><p class="eyebrow">SET <a class="set-number-link" href="${esc(rebrickableSetUrl(s.set_number))}" target="_blank" rel="noopener noreferrer" title="Set ${esc(s.set_number)} bei Rebrickable öffnen">${esc(s.set_number)} ↗</a></p><h3>${esc(s.name)}</h3><div class="sub">${esc(s.theme||"")}${s.year?" · "+s.year:""}</div><div class="set-price-row"><div><span>Kaufpreis</span><strong>${purchase.toLocaleString("de-DE",{style:"currency",currency:"EUR"})}</strong></div><div><span>Sammlungswert</span><strong>${value.toLocaleString("de-DE",{style:"currency",currency:"EUR"})}</strong></div></div><div class="progress"><i style="width:${pct}%"></i></div><div class="sub">${s.done_positions}/${s.positions} Positionen · ${s.missing_quantity} Teile fehlen</div><div class="row-actions" style="margin-top:12px"><button class="icon-btn" data-action="open-instructions" data-number="${esc(s.set_number)}" data-name="${esc(s.name)}">Bauanleitung</button><button class="icon-btn" data-action="open-inventory" data-id="${s.id}">Teileliste</button><button class="icon-btn" data-action="sync-set-spares" data-id="${s.id}">Ersatzteile prüfen</button><button class="icon-btn" data-action="edit-set" data-id="${s.id}">Bearbeiten</button><button class="icon-btn" data-action="add-part-to-set" data-id="${s.id}">＋ Teil</button><button class="icon-btn" data-action="delete-set" data-id="${s.id}">Löschen</button></div></div></article>`}).join("")||`<div class="empty">Noch keine Sets vorhanden.</div>`;
}

function renderShopping(){
  el("shoppingTable").innerHTML=state.shopping.length?`<table><thead><tr><th>Teil</th><th>Farbe</th><th>Sets</th><th>Menge</th><th>Gesamt</th></tr></thead><tbody>${state.shopping.map(x=>`<tr><td><strong>${esc(x.name)}</strong><div class="sub">${esc(x.element_id)}</div></td><td>${esc(x.color)}</td><td>${esc(x.sets||"")}</td><td>${x.quantity}</td><td>${(Number(x.quantity)*Number(x.unit_price||0)).toFixed(2).replace(".",",")} €</td></tr>`).join("")}</tbody></table>`:`<div class="empty">Die Einkaufsliste ist leer.</div>`;
}

function renderSetOptions(){
  el("partSet").innerHTML=`<option value="">Ohne Set</option>`+state.sets.map(s=>`<option value="${s.id}">${esc(s.set_number)} – ${esc(s.name)}</option>`).join("");
}


async function openInventory(setId){
  state.inventorySetId=Number(setId);
  state.inventorySelectedColors.clear();
  el("inventorySearch").value="";
  el("inventoryStateFilter").value="all";
  el("inventorySpareFilter").value="all";
  el("inventorySort").value="name-asc";
  openModal("inventoryModal");
  await loadInventory();
}

async function loadInventory(){
  if(!state.inventorySetId)return;
  const data=await request(`/api/set-inventory?set_id=${state.inventorySetId}`);
  state.inventory=data.inventory||[];
  state.inventoryTotals=data.totals||{};
  state.inventoryMinifigures=data.minifigures||[];
  el("inventoryTitle").textContent=`${data.set.set_number} – ${data.set.name}`;
  renderInventoryColorFilter();
  renderInventory();
}

function renderInventoryColorFilter(){
  const colors=[...new Set(state.inventory.map(item=>clean(item.color_name)||"Ohne Farbe"))]
    .sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  state.inventorySelectedColors=new Set(
    [...state.inventorySelectedColors].filter(color=>colors.includes(color))
  );
  el("inventoryColorOptions").innerHTML=colors.map(color=>`
    <label><input type="checkbox" data-inventory-color="${esc(color)}" ${state.inventorySelectedColors.has(color)?"checked":""}><span>${esc(color)}</span></label>
  `).join("")||'<div class="sub">Keine Farben verfügbar</div>';
  const count=state.inventorySelectedColors.size;
  el("inventoryColorSummary").textContent=count?`${count} Farbe${count===1?"":"n"} ausgewählt`:"Alle Farben";
}

function filteredInventory(){
  const q=clean(el("inventorySearch").value).toLowerCase();
  const stateFilter=el("inventoryStateFilter").value;
  const spareFilter=el("inventorySpareFilter").value;
  const sort=el("inventorySort").value;

  const result=state.inventory.filter(item=>{
    const required=Number(item.required_quantity)||0;
    const owned=Number(item.owned_quantity)||0;
    const missing=Math.max(required-owned,0);

    const matchesSearch=[
      item.name,item.part_num,item.element_id,item.color_name
    ].join(" ").toLowerCase().includes(q);

    let matchesState=true;
    if(stateFilter==="missing")matchesState=missing>0;
    else if(stateFilter==="complete")matchesState=required>0&&owned>=required;
    else if(stateFilter==="partial")matchesState=owned>0&&owned<required;
    else if(stateFilter==="none")matchesState=owned===0;

    let matchesSpare=true;
    if(spareFilter==="regular")matchesSpare=!Number(item.is_spare);
    else if(spareFilter==="spare")matchesSpare=Boolean(Number(item.is_spare));

    const itemColor=clean(item.color_name)||"Ohne Farbe";
    const matchesColor=!state.inventorySelectedColors.size
      ||state.inventorySelectedColors.has(itemColor);
    return matchesSearch&&matchesState&&matchesSpare&&matchesColor;
  });

  result.sort((a,b)=>{
    const nameA=clean(a.name),nameB=clean(b.name);
    const partA=clean(a.part_num),partB=clean(b.part_num);
    const colorA=clean(a.color_name),colorB=clean(b.color_name);
    const requiredA=Number(a.required_quantity)||0,requiredB=Number(b.required_quantity)||0;
    const ownedA=Number(a.owned_quantity)||0,ownedB=Number(b.owned_quantity)||0;
    const missingA=Math.max(requiredA-ownedA,0),missingB=Math.max(requiredB-ownedB,0);

    if(sort==="name-desc")return nameB.localeCompare(nameA,undefined,{numeric:true});
    if(sort==="part-asc")return partA.localeCompare(partB,undefined,{numeric:true});
    if(sort==="part-desc")return partB.localeCompare(partA,undefined,{numeric:true});
    if(sort==="color-asc")return colorA.localeCompare(colorB,undefined,{numeric:true})||nameA.localeCompare(nameB);
    if(sort==="required-desc")return requiredB-requiredA||nameA.localeCompare(nameB);
    if(sort==="required-asc")return requiredA-requiredB||nameA.localeCompare(nameB);
    if(sort==="missing-desc")return missingB-missingA||nameA.localeCompare(nameB);
    if(sort==="missing-asc")return missingA-missingB||nameA.localeCompare(nameB);
    if(sort==="owned-desc")return ownedB-ownedA||nameA.localeCompare(nameB);
    return nameA.localeCompare(nameB,undefined,{numeric:true});
  });

  return result;
}

function renderInventory(){
  requestAnimationFrame(enhanceImages);
  const t=state.inventoryTotals;
  el("invPositions").textContent=t.positions||0;
  el("invRequired").textContent=t.required_total||0;
  el("invOwned").textContent=t.owned_total||0;
  el("invMissing").textContent=t.missing_total||0;
  const progress=Number(t.required_total)?Math.round(Number(t.owned_total)/Number(t.required_total)*100):0;
  el("inventoryProgress").style.width=progress+"%";
  const rows=filteredInventory();
  el("inventoryFilterInfo").textContent=`${rows.length} von ${state.inventory.length} Positionen sichtbar`;
  el("inventoryTable").innerHTML=rows.length?`<table><colgroup><col class="inventory-col-image"><col class="inventory-col-part"><col class="inventory-col-color"><col class="inventory-col-required"><col class="inventory-col-owned"><col class="inventory-col-missing"><col class="inventory-col-action"></colgroup><thead><tr><th>Bild</th><th>Teil</th><th>Farbe</th><th>Benötigt</th><th>Vorhanden</th><th>Fehlend</th><th>Aktion</th></tr></thead><tbody>${rows.map(item=>`<tr>
    <td><div class="inventory-part-img"><img src="${esc(item.image_url||"")}"></div></td>
    <td><strong>${esc(item.name)}</strong><div class="sub">${esc(item.part_num)}${item.element_id?" · Element "+esc(item.element_id):""}${item.is_spare?" · Ersatzteil":""}</div></td>
    <td>${esc(item.color_name||"")}</td>
    <td><strong class="inventory-quantity quantity-required">${item.required_quantity}</strong></td>
    <td><div class="owned-control"><input type="checkbox" data-action="inventory-check" data-id="${item.id}" ${Number(item.owned_quantity)>=Number(item.required_quantity)?"checked":""} title="Vollständig vorhanden"><input class="inventory-owned-input" type="number" min="0" max="${item.required_quantity}" value="${item.owned_quantity}" data-action="inventory-owned" data-id="${item.id}" aria-label="Vorhandene Menge von ${esc(item.name)}"></div></td>
    <td class="${Number(item.missing_quantity)===0?"missing-ok":"missing-open"}"><strong class="inventory-quantity quantity-missing">${item.missing_quantity}</strong></td>
    <td class="inventory-actions-cell"><button type="button" class="btn inventory-transfer-btn" data-action="inventory-add-missing" data-id="${item.id}" ${Number(item.missing_quantity)===0?"disabled":""}>Zur Fehlliste</button></td>
  </tr>`).join("")}</tbody></table>`:`<div class="empty">${state.inventory.length?"Keine Teile entsprechen den aktuellen Filtern.":"Noch keine Teileliste geladen. Klicke auf „Teileliste laden/aktualisieren“."}</div>`;
  renderInventoryMinifigures();
}

function renderInventoryMinifigures(){
  const figures=state.inventoryMinifigures||[];
  const total=figures.reduce((sum,figure)=>sum+Number(figure.quantity||1),0);
  el("inventoryMinifigureCount").textContent=`${total} ${total===1?"Figur":"Figuren"}`;
  el("inventoryMinifigures").innerHTML=figures.length?figures.map(figure=>{const figureParts=figure.parts||[],requiredParts=figureParts.reduce((sum,part)=>sum+Number(part.quantity||1),0),ownedParts=figureParts.reduce((sum,part)=>sum+Math.min(Number(part.owned_quantity||0),Number(part.quantity||1)),0);return`
    <details class="inventory-minifigure-card" open>
      <summary>
        <span class="inventory-minifigure-image">${figure.image_url?`<img src="${esc(figure.image_url)}" alt="${esc(figure.name)}">`:"♟"}</span>
        <span><strong>${esc(figure.name)}</strong><small>${esc(figure.fig_number)} · ${Number(figure.quantity||1)}× im Set · ${(figure.parts||[]).length} Teilepositionen</small></span>
        <span class="status">${ownedParts}/${requiredParts} Teile vorhanden</span>
      </summary>
      <div class="minifigure-parts-grid">${figureParts.length?figureParts.map(part=>{const required=Math.max(1,Number(part.quantity||1)),owned=Math.min(required,Math.max(0,Number(part.owned_quantity||0))),missing=Math.max(required-owned,0),present=missing===0;return`
        <article class="minifigure-part ${present?"is-present":"is-missing"}">
          <div class="inventory-part-img">${part.image_url?`<img src="${esc(part.image_url)}" alt="${esc(part.name)}">`:""}</div>
          <div><strong>${esc(part.name)}</strong><small>${esc(part.part_num)}${part.element_id?" · Element "+esc(part.element_id):""}</small><span>${esc(part.color_name||"Ohne Farbe")}${part.is_spare?" · Ersatzteil":""}</span></div>
          <div class="minifigure-part-status"><b>${required}× benötigt</b><label class="minifigure-owned-control"><span>Vorhanden</span><input type="number" min="0" max="${required}" value="${owned}" data-action="minifigure-part-owned" data-id="${part.id}" aria-label="Vorhandene Menge von ${esc(part.name)}"></label><small class="${missing?"quantity-open":"quantity-complete"}">${missing?`${missing} fehlt${missing===1?"":"en"}`:"Vollständig"}</small><div class="presence-toggle"><button type="button" data-action="minifigure-part-present" data-id="${part.id}" class="${present?"active":""}">Alle</button><button type="button" data-action="minifigure-part-missing" data-id="${part.id}" class="${owned===0?"active":""}">Keine</button></div></div>
        </article>`}).join(""):`<div class="empty">Für diese Minifigur sind noch keine Teile geladen. „Teileliste laden/aktualisieren“ lädt sie von Rebrickable.</div>`}</div>
    </details>`}).join(""):`<div class="empty">Dieses Set enthält keine Minifiguren oder die Daten wurden noch nicht von Rebrickable geladen.</div>`;
}

async function fetchInventory(){
  if(!state.inventorySetId)return;
  toast("Teileliste wird von Rebrickable geladen …");
  const result=await request("/api/set-inventory/fetch",{method:"POST",body:JSON.stringify({set_id:state.inventorySetId})});
  toast(`${result.imported} Set-Teile, ${result.minifigures_imported||0} Minifiguren und ${result.minifigure_parts_imported||0} Figuren-Teile verarbeitet.`);
  await loadInventory();
}

async function updateInventoryItem(id,ownedQuantity,complete=false){
  await request("/api/set-inventory/update",{method:"POST",body:JSON.stringify({id:Number(id),owned_quantity:Number(ownedQuantity)||0,complete})});
  await loadInventory();
}

async function updateMinifigurePart(id,ownedQuantity=null,present=null){
  const payload={id:Number(id)};
  if(ownedQuantity!==null)payload.owned_quantity=Number(ownedQuantity)||0;
  if(present!==null)payload.present=Boolean(present);
  await request("/api/minifigure-parts/update",{method:"POST",body:JSON.stringify(payload)});
  await loadInventory();
}

async function markAllInventory(complete){
  await request("/api/set-inventory/mark-all",{method:"POST",body:JSON.stringify({set_id:state.inventorySetId,complete})});
  toast(complete?"Alle Teile als vorhanden markiert.":"Alle Teile als fehlend markiert.");
  await loadInventory();
}

async function addInventoryMissing(inventoryId=null){
  if(!state.inventorySetId)return;
  const payload={set_id:state.inventorySetId};
  if(inventoryId)payload.inventory_id=Number(inventoryId);
  const result=await request("/api/set-inventory/add-missing",{
    method:"POST",
    body:JSON.stringify(payload)
  });
  if(result.processed===0){
    toast("Es gibt keine fehlenden Teile zum Übernehmen.");
  }else{
    const parts=[];
    if(result.added)parts.push(`${result.added} neu hinzugefügt`);
    if(result.merged)parts.push(`${result.merged} aktualisiert`);
    if(result.skipped)parts.push(`${result.skipped} übersprungen`);
    if(result.minifigure_processed)parts.push(`${result.minifigure_processed} Minifiguren-Teile berücksichtigt`);
    toast(parts.join(", ")||"Fehlteile wurden übernommen.");
  }
  await reloadData();
}

async function refreshAllSetInventories(button){
  const sets=[...state.sets];
  if(!sets.length)return toast("Es sind keine Sets zum Aktualisieren vorhanden.");
  if(!await askConfirm(
    `Teilelisten und Minifiguren für ${sets.length} Sets aktualisieren und danach alle fehlenden Teile übernehmen? Je nach Sammlungsgröße kann das einige Minuten dauern.`,
    {title:"Alle Set-Teilelisten aktualisieren",danger:false}
  ))return;
  const originalLabel=button.textContent;
  button.disabled=true;
  const totals={updated:0,failed:0,added:0,merged:0,minifigureParts:0};
  const failures=[];
  const deferBackup=state.authUser?.role==="admin";
  try{
    for(let index=0;index<sets.length;index++){
      const set=sets[index];
      button.textContent=`Set ${index+1}/${sets.length}: ${set.set_number}`;
      toast(`Aktualisiere ${index+1} von ${sets.length}: ${set.name}`);
      try{
        await request("/api/set-inventory/fetch",{
          method:"POST",
          body:JSON.stringify({set_id:Number(set.id),defer_backup:deferBackup})
        });
        const result=await request("/api/set-inventory/add-missing",{
          method:"POST",
          body:JSON.stringify({set_id:Number(set.id),defer_backup:deferBackup})
        });
        totals.updated++;
        totals.added+=Number(result.added||0);
        totals.merged+=Number(result.merged||0);
        totals.minifigureParts+=Number(result.minifigure_processed||0);
      }catch(error){
        totals.failed++;
        failures.push(`${set.set_number}: ${error.message}`);
      }
      if(index<sets.length-1)await new Promise(resolve=>setTimeout(resolve,300));
    }
    if(deferBackup&&totals.updated)await request("/api/backup",{method:"POST",body:"{}"});
    await reloadData();
    const summary=`${totals.updated}/${sets.length} Sets aktualisiert · ${totals.added} Fehlteile neu · ${totals.merged} aktualisiert · ${totals.minifigureParts} Minifiguren-Teile berücksichtigt`;
    toast(totals.failed?`${summary} · ${totals.failed} Fehler`:summary,totals.updated===0);
    if(failures.length)console.warn("Nicht aktualisierte Sets:",failures);
  }finally{
    button.disabled=false;
    button.textContent=originalLabel;
  }
}

async function saveApiKey(){
  const key=clean(el("rebrickableKey").value);
  await request("/api/settings",{method:"POST",body:JSON.stringify({settings:{rebrickable_api_key:key}})});
  state.settings.rebrickable_api_key=key;
  toast(key?"Rebrickable API-Key gespeichert.":"API-Key entfernt.");
}

function locationPath(id){
  const names=[],seen=new Set();let current=state.locations.find(x=>Number(x.id)===Number(id));
  while(current&&!seen.has(current.id)){seen.add(current.id);names.unshift(current.name);current=state.locations.find(x=>Number(x.id)===Number(current.parent_id))}
  return names.join(" → ")||"Nicht zugeordnet";
}
function renderLocationOptions(){
  const options=state.locations.map(x=>`<option value="${x.id}">${esc(locationPath(x.id))}</option>`).join("");
  if(el("whLocation"))el("whLocation").innerHTML=`<option value="">Nicht zugeordnet</option>${options}`;
  if(el("locationParent"))el("locationParent").innerHTML=`<option value="">Keiner</option>${options}`;
}
function renderWarehouse(){
  requestAnimationFrame(enhanceImages);
  renderLocationOptions();
  const q=clean(el("warehouseSearch")?.value).toLowerCase();
  const stock=state.warehouse.filter(x=>[x.name,x.element_id,x.design_id,x.color,locationPath(x.location_id)].join(" ").toLowerCase().includes(q));
  el("warehouseLocations").innerHTML=state.locations.map(x=>{const capacity=Number(x.capacity)||0,used=Number(x.used_capacity)||0,pct=capacity?Math.min(100,Math.round(used/capacity*100)):0;const url=`${location.origin}${location.pathname}?warehouse_location=${x.id}`;return`<article class="location-card">${x.photo_url?`<img class="location-photo" src="${esc(x.photo_url)}" alt="${esc(x.name)}">`:""}<div class="location-card-body"><div class="panel-head"><div><p class="eyebrow">${esc(x.location_type)}</p><h3>${esc(x.name)}</h3></div><div class="actions"><button class="icon-btn" data-action="edit-location" data-id="${x.id}">Bearbeiten</button><button class="icon-btn" data-action="delete-location" data-id="${x.id}">×</button></div></div><p class="sub">${esc(locationPath(x.parent_id))}${x.parent_id?" → ":""}${esc(x.name)}</p><div class="capacity"><i style="width:${pct}%"></i></div><p class="sub">${capacity?`${used} von ${capacity} Plätzen · ${pct}%`:`${x.item_quantity||0} Teile · unbegrenzt`}</p><div class="location-qr"><img src="/api/qr?text=${encodeURIComponent(url)}" alt="QR-Code für ${esc(x.name)}"><button class="btn" data-action="open-location-content" data-id="${x.id}">Inhalt öffnen</button></div></div></article>`}).join("")||`<div class="empty">Lege dein erstes Regal, eine Schublade oder Box an.</div>`;
  el("warehouseTable").innerHTML=stock.length?`<table><thead><tr><th>Teil</th><th>Farbe</th><th>Lagerort</th><th>Menge</th><th>Plätze</th><th></th></tr></thead><tbody>${stock.map(x=>`<tr><td><strong>${esc(x.name)}</strong><div class="sub">${esc(x.element_id)}</div></td><td>${esc(x.color||"–")}</td><td><strong>${esc(locationPath(x.location_id))}</strong></td><td>${x.quantity}</td><td>${x.slot_usage||1}</td><td><div class="actions"><button class="icon-btn" data-action="edit-warehouse" data-id="${x.id}">Bearbeiten</button><button class="icon-btn" data-action="delete-warehouse" data-id="${x.id}">×</button></div></td></tr>`).join("")}</tbody></table>`:`<div class="empty">Keine passenden Lagerteile gefunden.</div>`;
}
function renderOrders(){el("ordersTable").innerHTML=state.orders.length?`<table><thead><tr><th>Händler</th><th>Nummer</th><th>Status</th><th>Gesamt</th></tr></thead><tbody>${state.orders.map(x=>`<tr><td>${esc(x.supplier)}</td><td>${esc(x.order_number)}</td><td><span class="badge ${x.status}">${labelStatus(x.status)}</span></td><td>${Number(x.total).toFixed(2).replace(".",",")} €</td></tr>`).join("")}</tbody></table>`:`<div class="empty">Noch keine Bestellungen.</div>`}
function trashPartImage(item){
  const url=item.image_url||`https://www.lego.com/cdn/product-assets/element.img.lod5photo.192x192/${encodeURIComponent(item.element_id||"")}.jpg`;
  return proxiedImage(url);
}

function renderTrash(){
  const partCount=state.trash.parts.length;
  const setCount=state.trash.sets.length;
  el("emptyTrashButton").disabled=(partCount+setCount)===0;
  const parts=state.trash.parts.map(x=>`<div class="trash-item">
    <div class="trash-main">
      <div class="trash-thumb"><img class="click-image" data-action="zoom-image" data-src="${esc(trashPartImage(x))}" src="${esc(trashPartImage(x))}"></div>
      <div class="trash-copy"><strong>${esc(x.name)}</strong><span class="sub">Element ${esc(x.element_id||"")}${x.color?" · "+esc(x.color):""}</span><small>Gelöscht: ${esc(x.deleted_at||"")}</small></div>
    </div>
    <div class="trash-actions"><button class="btn" data-action="restore" data-kind="part" data-id="${x.id}">Wiederherstellen</button></div>
  </div>`).join("")||"<p class=sub>Keine gelöschten Fehlteile.</p>";

  const sets=state.trash.sets.map(x=>`<div class="trash-item">
    <div class="trash-main">
      <div class="trash-thumb"><img class="click-image" data-action="zoom-image" data-src="${esc(setImage(x))}" src="${esc(setImage(x))}"></div>
      <div class="trash-copy"><strong>${esc(x.name)}</strong><span class="sub">Set ${esc(x.set_number||"")}</span><small>Gelöscht: ${esc(x.deleted_at||"")}</small></div>
    </div>
    <div class="trash-actions"><button class="btn" data-action="restore" data-kind="set" data-id="${x.id}">Wiederherstellen</button></div>
  </div>`).join("")||"<p class=sub>Keine gelöschten Sets.</p>";

  el("trashContent").innerHTML=`<div class="trash-section"><div class="trash-heading"><h3>Fehlteile</h3><span class="badge">${partCount}</span></div>${parts}</div><div class="trash-section"><div class="trash-heading"><h3>Sets</h3><span class="badge">${setCount}</span></div>${sets}</div>`;
}

async function saveWarehouse(e){e.preventDefault();await request("/api/warehouse",{method:"POST",body:JSON.stringify({user_id:state.userId,element_id:clean(el("whElement").value),design_id:clean(el("whDesign").value),name:clean(el("whName").value),color:clean(el("whColor").value),quantity:Number(el("whQuantity").value)||0,location_id:Number(el("whLocation").value)||null,slot_usage:Number(el("whSlotUsage").value)||1,image_url:clean(el("whImage").value)})});closeModal("warehouseModal");toast("Lagerbestand gespeichert.");await reloadData()}
function openLocation(record=null){
  el("locationForm").reset();renderLocationOptions();
  el("locationId").value=record?.id||"";el("locationModalTitle").textContent=record?"Lagerort bearbeiten":"Lagerort hinzufügen";
  el("locationName").value=record?.name||"";el("locationType").value=record?.location_type||"Box";el("locationParent").value=record?.parent_id||"";
  el("locationCapacity").value=record?.capacity||0;el("locationPhoto").value=record?.photo_url||"";el("locationNotes").value=record?.notes||"";
  [...el("locationParent").options].forEach(option=>option.disabled=record&&Number(option.value)===Number(record.id));
  openModal("locationModal");
}
function openWarehouseItem(record=null){
  el("warehouseForm").reset();renderLocationOptions();
  el("whElement").value=record?.element_id||"";el("whDesign").value=record?.design_id||"";el("whName").value=record?.name||"";el("whColor").value=record?.color||"";el("whQuantity").value=record?.quantity||0;el("whLocation").value=record?.location_id||"";el("whSlotUsage").value=record?.slot_usage||1;el("whImage").value=record?.image_url||"";
  openModal("warehouseModal");
}
async function deleteWarehouse(kind,id,label){
  if(!await askConfirm(`${label} wirklich löschen?`,{title:"Lagerverwaltung",danger:true}))return;
  await request(`/api/${kind}/${id}`,{method:"DELETE"});toast("Gelöscht.");await reloadData();
}
async function saveLocation(e){e.preventDefault();await request("/api/warehouse-locations",{method:"POST",body:JSON.stringify({id:Number(el("locationId").value)||null,user_id:state.userId,name:clean(el("locationName").value),location_type:el("locationType").value,parent_id:Number(el("locationParent").value)||null,capacity:Number(el("locationCapacity").value)||0,photo_url:clean(el("locationPhoto").value),notes:clean(el("locationNotes").value)})});closeModal("locationModal");toast("Lagerort gespeichert.");await reloadData()}
async function openInstructions(number,name){
  el("instructionTitle").textContent=`${number} – ${name}`;el("instructionBody").innerHTML=`<div class="empty">Bauanleitungen werden geladen …</div>`;openModal("instructionModal");
  const data=await request(`/api/instructions?set_number=${encodeURIComponent(number)}`);
  el("instructionBody").innerHTML=data.instructions.length?data.instructions.map((x,i)=>`<section class="instruction-entry"><div class="panel-head"><div><strong>${esc(x.name||`Anleitung ${i+1}`)}</strong><small class="instruction-source">${esc(x.source||"Extern")}</small></div><a class="btn primary" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${x.source==="Rebrickable"?"Bei Rebrickable öffnen":"Bauanleitung öffnen"} ↗</a></div>${x.embeddable?`<iframe src="${esc(x.url)}" title="${esc(x.name||"Bauanleitung")}" loading="lazy"></iframe>`:`<div class="instruction-fallback"><strong>${x.source==="Rebrickable"?"Rebrickable-Anleitungen gefunden":"Alternative Anleitung"}</strong><p>${x.source==="Rebrickable"?"Öffne die Rebrickable-Seite, um alle dort hinterlegten PDF-Dateien für dieses Set auszuwählen. Rebrickable stellt diese Dateien nicht über seine öffentliche API bereit.":"Die offizielle LEGO-Seite ist als Alternative mit der Setnummer vorbereitet."}</p></div>`}</section>`).join(""):`<div class="empty">Für dieses Set wurde keine digitale Bauanleitung gefunden.</div>`;
}
async function scanLocation(){
  el("instructionTitle").textContent="Lagerort scannen";el("instructionBody").innerHTML=`<video id="qrVideo" class="qr-video" autoplay playsinline></video><p class="sub">Halte den QR-Code eines Lagerorts vor die Kamera.</p>`;openModal("instructionModal");
  if(!("BarcodeDetector" in window)||!navigator.mediaDevices?.getUserMedia){el("instructionBody").innerHTML=`<div class="empty">Dieser Browser unterstützt den Kamerascan nicht. Öffne den QR-Code mit der normalen Kamera-App deines Smartphones.</div>`;return}
  const video=el("qrVideo"),stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:"environment"}});video.srcObject=stream;const detector=new BarcodeDetector({formats:["qr_code"]});
  const timer=setInterval(async()=>{if(modalIsClosed("instructionModal")){clearInterval(timer);stream.getTracks().forEach(x=>x.stop());return}for(const code of await detector.detect(video)){const url=new URL(code.rawValue,location.href),id=Number(url.searchParams.get("warehouse_location"));if(state.locations.some(x=>Number(x.id)===id)){clearInterval(timer);stream.getTracks().forEach(x=>x.stop());closeModal("instructionModal");setView("warehouse");el("warehouseSearch").value=locationPath(id);renderWarehouse();toast("Lagerort geöffnet.");return}}},500);
}
function modalIsClosed(id){return el(id).classList.contains("hidden")}
async function saveOrder(e){e.preventDefault();await request("/api/orders",{method:"POST",body:JSON.stringify({id:Number(el("orderId").value)||null,user_id:state.userId,supplier:clean(el("orderSupplier").value),order_number:clean(el("orderNumber").value),status:el("orderStatus").value,total:Number(el("orderTotal").value)||0,notes:clean(el("orderNotes").value)})});closeModal("orderModal");toast("Bestellung gespeichert.");await reloadData()}
async function cycleStatus(id){const p=state.parts.find(x=>x.id===id);const next=PART_STATUSES[(PART_STATUSES.indexOf(p.status)+1)%PART_STATUSES.length];await request("/api/parts",{method:"POST",body:JSON.stringify({...p,user_id:state.userId,id:p.id,set_id:p.set_id,element_id:p.element_id,name:p.name,status:next})});toast("Status geändert.");await reloadData()}
async function setPartPresence(id,isPresent){
  const part=state.parts.find(item=>Number(item.id)===Number(id));
  return setPartOwned(id,isPresent?Math.max(1,Number(part?.quantity)||1):0);
}
async function setPartOwned(id,ownedQuantity){
  const part=state.parts.find(item=>Number(item.id)===Number(id));
  const required=Math.max(1,Number(part?.quantity)||1);
  const owned=Math.max(0,Math.min(required,Number(ownedQuantity)||0));
  await request("/api/parts/presence",{method:"POST",body:JSON.stringify({
    id:Number(id),
    owned_quantity:owned,
  })});
  if(part){part.owned_quantity=owned;part.is_present=owned>=required?1:0}
  toast(`${owned} von ${required} Teilen als vorhanden gespeichert.`);
  await reloadData();
}
async function setUnassignedFound(ids,quantity){
  const normalizedIds=ids.map(Number).filter(Boolean);
  const normalizedQuantity=Math.max(0,Number(quantity)||0);
  await request("/api/parts/unassigned-found",{method:"POST",body:JSON.stringify({ids:normalizedIds,quantity:normalizedQuantity})});
  toast(`${normalizedQuantity} gefundene Teile unzugeordnet gespeichert.`);
  await refreshPartsView();
}
async function cycleGroupStatus(ids,currentStatus){
  const order=PART_STATUSES;
  const next=order[(order.indexOf(currentStatus)+1)%order.length];
  await request("/api/bulk-parts",{method:"POST",body:JSON.stringify({ids,action:next})});
  toast(`${ids.length} Einträge auf „${labelStatus(next)}“ gesetzt.`);
  await reloadData();
}
async function setGroupStatus(ids,status){
  if(!PART_STATUSES.includes(status))throw new Error("Ungültiger Status.");
  await request("/api/bulk-parts",{method:"POST",body:JSON.stringify({ids,action:status})});
  toast(`${ids.length} Einträge auf „${labelStatus(status)}“ gesetzt.`);
  await reloadData();
}
async function deletePartGroup(ids){
  if(!await askConfirm(`${ids.length>1?ids.length+" gruppierte Einträge":"Diesen Eintrag"} in den Papierkorb verschieben?`,{title:"Fehlteil löschen",danger:true}))return;
  await request("/api/bulk-parts",{method:"POST",body:JSON.stringify({ids,action:"trash"})});
  ids.forEach(id=>state.selectedParts.delete(id));
  toast(ids.length>1?"Gruppierte Fehlteile verschoben.":"Fehlteil verschoben.");
  await reloadData();
}
function openPart(part=null){
  el("partForm").reset();
  let deleteButton=el("partDeleteButton");
  if(!deleteButton){
    el("partForm").querySelector(".dialog-actions").insertAdjacentHTML("afterbegin",'<button type="button" id="partDeleteButton" class="btn danger-btn delete-current-part" data-action="delete-open-part">Löschen</button>');
    deleteButton=el("partDeleteButton");
  }
  deleteButton.classList.toggle("hidden",!part);
  deleteButton.dataset.id=part?.id||"";
  el("partId").value=part?.id||"";
  el("partModalTitle").textContent=part?"Fehlteil bearbeiten":"Fehlteil hinzufügen";
  el("partSet").value=part?.set_id||"";
  el("elementId").value=part?.element_id||"";
  el("designId").value=part?.design_id||"";
  el("partName").value=part?.name||"";
  el("partColor").value=part?.color||"";
  el("partQuantity").value=part?.quantity||1;
  el("partStatus").value=part?.status||"missing";
  el("partPriority").value=part?.priority||"normal";
  el("partPrice").value=part?.unit_price||0;
  el("partSupplier").value=part?.supplier||"";
  el("partNotes").value=part?.notes||"";
  openModal("partModal");
}

function openSet(set=null){
  el("setForm").reset();
  el("setId").value=set?.id||"";
  el("setModalTitle").textContent=set?"Set bearbeiten":"Set hinzufügen";
  el("setNumber").value=set?.set_number||"";
  el("setName").value=set?.name||"";
  el("setTheme").value=set?.theme||"";
  el("setYear").value=set?.year||"";
  el("setTotalParts").value=set?.total_parts||0;
  el("setImage").value=set?.image_url||"";
  el("setFavorite").checked=Boolean(set?.favorite);el("setPurchase").value=set?.purchase_price||0;el("setValue").value=set?.current_value||0;
  openModal("setModal");
}

function openCompleteSet(){
  el("completeSetForm").reset();
  el("completeSetBuildStatus").value="zerlegt vollständig";
  el("completeSetCondition").value="gebraucht";
  openModal("completeSetModal");
  el("completeSetNumber").focus();
}

async function lookupCompleteSet(){
  const number=clean(el("completeSetNumber").value);
  if(!number)throw new Error("Bitte zuerst eine Setnummer eingeben.");
  const result=await request(`/api/lookup/set?number=${encodeURIComponent(number)}`);
  const set=result.set;
  el("completeSetNumber").value=set.set_number;
  el("completeSetName").value=set.name;
  el("completeSetTheme").value=set.theme||"";
  el("completeSetYear").value=set.year||"";
  el("completeSetTotalParts").value=set.total_parts||0;
  el("completeSetImage").value=set.image_url||"";
  toast("Setdaten geladen.");
}

async function saveCompleteSet(event){
  event.preventDefault();
  try{
    const payload={
      user_id:state.userId,
      set_number:clean(el("completeSetNumber").value),
      name:clean(el("completeSetName").value),
      theme:clean(el("completeSetTheme").value),
      year:Number(el("completeSetYear").value)||null,
      total_parts:Number(el("completeSetTotalParts").value)||0,
      image_url:clean(el("completeSetImage").value),
      build_status:el("completeSetBuildStatus").value,
      condition:el("completeSetCondition").value,
      purchase_price:Number(el("completeSetPurchase").value)||0,
      current_value:Number(el("completeSetValue").value)||0,
      favorite:el("completeSetFavorite").checked,
    };
    await request("/api/sets/complete",{method:"POST",body:JSON.stringify(payload)});
    closeModal("completeSetModal");
    toast("Vollständiges Set und Set-Exemplar wurden angelegt.");
    await reloadData();
  }catch(error){toast(error.message,true)}
}

function openPurchasedSet(){
  el("purchasedSetForm").reset();
  el("purchasedSetBuildStatus").value="ungeöffnet";
  el("purchasedSetCondition").value="neu";
  el("purchasedSetDate").value=new Date().toISOString().slice(0,10);
  openModal("purchasedSetModal");
  el("purchasedSetNumber").focus();
}

async function lookupPurchasedSet(){
  const number=clean(el("purchasedSetNumber").value);
  if(!number)throw new Error("Bitte zuerst eine Setnummer eingeben.");
  const result=await request(`/api/lookup/set?number=${encodeURIComponent(number)}`);
  const set=result.set;
  el("purchasedSetNumber").value=set.set_number;
  el("purchasedSetName").value=set.name;
  el("purchasedSetTheme").value=set.theme||"";
  el("purchasedSetYear").value=set.year||"";
  el("purchasedSetTotalParts").value=set.total_parts||0;
  el("purchasedSetImage").value=set.image_url||"";
  toast("Setdaten wurden geladen.");
}

async function savePurchasedSet(event){
  event.preventDefault();
  const submit=event.submitter||event.target.querySelector('button[type="submit"]');
  const original=submit?.textContent||"Set und Ersatzteile übernehmen";
  if(submit){submit.disabled=true;submit.textContent="Set wird verarbeitet …"}
  try{
    const created=await request("/api/sets/complete",{method:"POST",body:JSON.stringify({
      user_id:state.userId,
      set_number:clean(el("purchasedSetNumber").value),
      name:clean(el("purchasedSetName").value),
      theme:clean(el("purchasedSetTheme").value),
      year:Number(el("purchasedSetYear").value)||null,
      total_parts:Number(el("purchasedSetTotalParts").value)||0,
      image_url:clean(el("purchasedSetImage").value),
      build_status:el("purchasedSetBuildStatus").value,
      condition:el("purchasedSetCondition").value,
      purchase_date:el("purchasedSetDate").value||null,
      purchase_price:Number(el("purchasedSetPurchase").value)||0,
      current_value:Number(el("purchasedSetValue").value)||0,
      favorite:el("purchasedSetFavorite").checked
    })});
    if(submit)submit.textContent="Teileliste wird geladen …";
    await request("/api/set-inventory/fetch",{method:"POST",body:JSON.stringify({set_id:created.id})});
    await request("/api/set-inventory/mark-all",{method:"POST",body:JSON.stringify({set_id:created.id,complete:true})});
    if(submit)submit.textContent="Ersatzteile werden eingelagert …";
    const result=await request("/api/set-inventory/import-spares",{method:"POST",body:JSON.stringify({set_id:created.id,copy_id:created.copy_id})});
    closeModal("purchasedSetModal");
    await reloadData();
    if(result.no_spares_reported){
      toast(`Set gespeichert. ${result.message}`,true);
    }else if(result.already_imported){
      toast(`Set gespeichert · Die ${result.quantity} Ersatzteile waren bereits eingelagert.`);
    }else{
      toast(`Set gespeichert · ${result.quantity} Ersatzteile auf ${result.positions} Positionen eingelagert.`);
    }
  }finally{
    if(submit?.isConnected){submit.disabled=false;submit.textContent=original}
  }
}

async function syncSetSpares(button){
  const setId=Number(button.dataset.id);
  const original=button.textContent;
  button.disabled=true;
  try{
    button.textContent="Teileliste wird geprüft …";
    await request("/api/set-inventory/fetch",{method:"POST",body:JSON.stringify({set_id:setId})});
    button.textContent="Ersatzteile werden übernommen …";
    const result=await request("/api/set-inventory/import-spares",{method:"POST",body:JSON.stringify({set_id:setId})});
    await reloadData();
    if(result.no_spares_reported){
      toast(result.message,true);
    }else if(result.already_imported){
      toast(`${result.quantity} Ersatzteile dieses Set-Exemplars sind bereits im Teileinventar.`);
    }else{
      toast(`${result.quantity} Ersatzteile auf ${result.positions} Positionen eingelagert.`);
    }
  }finally{
    if(button.isConnected){button.disabled=false;button.textContent=original}
  }
}

async function savePart(event){
  event.preventDefault();
  try{
    const payload={id:Number(el("partId").value)||null,user_id:state.userId,set_id:Number(el("partSet").value)||null,element_id:clean(el("elementId").value),design_id:clean(el("designId").value),name:clean(el("partName").value),color:clean(el("partColor").value),quantity:Number(el("partQuantity").value)||1,status:el("partStatus").value,priority:el("partPriority").value,unit_price:Number(el("partPrice").value)||0,supplier:clean(el("partSupplier").value),notes:clean(el("partNotes").value),history_note:clean(el("historyNote").value)};
    await request("/api/parts",{method:"POST",body:JSON.stringify(payload)});
    closeModal("partModal");toast("Fehlteil gespeichert.");await reloadData();
  }catch(error){toast(error.message,true)}
}

async function saveSet(event){
  event.preventDefault();
  try{
    const payload={id:Number(el("setId").value)||null,user_id:state.userId,set_number:clean(el("setNumber").value),name:clean(el("setName").value),theme:clean(el("setTheme").value),year:Number(el("setYear").value)||null,total_parts:Number(el("setTotalParts").value)||0,favorite:el("setFavorite").checked,image_url:clean(el("setImage").value),purchase_price:Number(el("setPurchase").value)||0,current_value:Number(el("setValue").value)||0};
    await request("/api/sets",{method:"POST",body:JSON.stringify(payload)});
    closeModal("setModal");toast("Set gespeichert.");await reloadData();
  }catch(error){toast(error.message,true)}
}

async function saveUser(event){
  event.preventDefault();
  try{
    const name=clean(el("userName").value);
    const email=clean(el("userEmail").value);
    const password=el("userStartPassword").value;
    await request("/api/users",{method:"POST",body:JSON.stringify({name,email,password})});
    closeModal("userModal");toast("Benutzer erstellt. Das Startpasswort muss beim ersten Login geändert werden.");await bootstrap();
  }catch(error){toast(error.message,true)}
}

async function toggleTheme(){
  const previous=document.documentElement.classList.contains("light")?"light":"dark";
  const next=document.documentElement.classList.contains("light")?"dark":"light";
  document.documentElement.classList.toggle("light",next==="light");
  try{
    await request("/api/settings",{method:"POST",body:JSON.stringify({settings:{theme:next}})});
    state.settings.theme=next;
    toast(next==="light"?"Heller Modus aktiviert.":"Dunkler Modus aktiviert.");
  }catch(error){
    document.documentElement.classList.toggle("light",previous==="light");
    throw error;
  }
}

async function createBackup(){
  const result=await request("/api/backup",{method:"POST",body:"{}"});
  if(typeof collectionWorkshop!=="undefined"){
    await collectionWorkshop.ensureLoaded();
    collectionWorkshop.data.lastBackup=new Date().toISOString();
    await collectionWorkshop.persist(false);
  }
  sessionStorage.setItem("brickBackupReminderShown","1");
  toast(`Backup erstellt. Insgesamt ${result.count} Sicherungen.`);
}

async function uploadBackup(file){
  if(!file)return;
  if(!file.name.toLowerCase().endsWith(".db.enc")){
    throw new Error("Bitte eine verschlüsselte BrickMissing-Sicherung (.db.enc) auswählen.");
  }
  const result=await request("/api/backup/upload",{
    method:"POST",
    headers:{
      "Content-Type":"application/octet-stream",
      "X-CSRF-Token":state.authUser?.csrf_token||""
    },
    body:file
  });
  if(typeof collectionWorkshop!=="undefined"){
    await collectionWorkshop.ensureLoaded();
    collectionWorkshop.data.lastBackup=new Date().toISOString();
    await collectionWorkshop.persist(false);
  }
  sessionStorage.setItem("brickBackupReminderShown","1");
  toast(`Backup ${result.backup.name} wurde geprüft und hochgeladen.`);
}

async function clearCache(){
  const result=await request("/api/cache/clear",{method:"POST",body:"{}"});
  toast(`${result.removed} Cache-Dateien gelöscht.`);
}

async function switchUser(){
  state.userId=Number(el("userSelect").value);
  loadPartsColorSelection();
  await request("/api/settings",{method:"POST",body:JSON.stringify({settings:{current_user:state.userId}})});
  toast("Benutzer gewechselt.");await reloadData();
  if(typeof collectionWorkshop!=="undefined"&&el("view-workshop").classList.contains("active")){
    await collectionWorkshop.ensureLoaded();collectionWorkshop.render();
  }
}

async function deleteCurrentUser(){
  if(!confirm("Aktiven Benutzer und alle zugehörigen Daten löschen?"))return;
  try{
    await request(`/api/users/${state.userId}`,{method:"DELETE"});
    toast("Benutzer gelöscht.");await bootstrap();
  }catch(error){toast(error.message,true)}
}

async function showHistory(id){
  const data=await request(`/api/history?part_id=${id}`);
  el("historyList").innerHTML=data.history.map(h=>`<div style="padding:11px;border-bottom:1px solid var(--line)"><strong>${labelStatus(h.status)}</strong><div class="sub">${esc(h.created_at)}</div><p>${esc(h.note||"")}</p></div>`).join("")||`<div class="empty">Kein Verlauf vorhanden.</div>`;
  openModal("historyModal");
}

function download(url){const a=document.createElement("a");a.href=url;a.click()}

async function importJson(file){
  try{
    const data=JSON.parse(await file.text());
    await request("/api/import",{method:"POST",body:JSON.stringify({user_id:state.userId,data})});
    toast("JSON importiert.");await reloadData();
  }catch(error){toast(error.message,true)}
}

async function quit(){
  if(!confirm("BrickMissing wirklich beenden?"))return;
  try{await request("/api/backup",{method:"POST",body:"{}"})}catch{}
  try{await request("/api/shutdown",{method:"POST",body:"{}"})}catch{}
  document.body.innerHTML=`<div style="display:grid;place-items:center;min-height:100vh;background:#07101d;color:white;font-family:Segoe UI,system-ui"><div style="text-align:center"><h1>BrickMissing wurde beendet</h1><p>Dieses Fenster kann geschlossen werden.</p></div></div>`;
}

document.addEventListener("click",async event=>{
  const button=event.target.closest("[data-action]");
  if(!button)return;
  const action=button.dataset.action;
  try{
    if(action==="open-user")openModal("userModal");
    else if(action==="reset-note")resetNoteEditor();
    else if(action==="edit-note")editNote(button.dataset.id);
    else if(action==="delete-note")await deleteNote(button.dataset.id);
    else if(action==="open-purchased-set")openPurchasedSet();
    else if(action==="open-complete-set")openCompleteSet();
    else if(action==="open-set")openSet();
    else if(action==="open-part")openPart();
    else if(action==="open-inventory")await openInventory(Number(button.dataset.id));
    else if(action==="sync-set-spares")await syncSetSpares(button);
    else if(action==="open-instructions")await openInstructions(button.dataset.number,button.dataset.name);
    else if(action==="open-location")openLocation();
    else if(action==="edit-location")openLocation(state.locations.find(x=>Number(x.id)===Number(button.dataset.id)));
    else if(action==="open-location-content"){setView("warehouse");el("warehouseSearch").value=locationPath(button.dataset.id);renderWarehouse()}
    else if(action==="scan-location")await scanLocation();
    else if(action==="edit-warehouse")openWarehouseItem(state.warehouse.find(x=>Number(x.id)===Number(button.dataset.id)));
    else if(action==="delete-warehouse")await deleteWarehouse("warehouse",button.dataset.id,"Lagerteil");
    else if(action==="delete-location")await deleteWarehouse("warehouse-locations",button.dataset.id,"Lagerort");
    else if(action==="fetch-inventory")await fetchInventory();
    else if(action==="inventory-all-owned")await markAllInventory(true);
    else if(action==="inventory-all-missing")await markAllInventory(false);
    else if(action==="inventory-add-all-missing")await addInventoryMissing();
    else if(action==="inventory-add-missing")await addInventoryMissing(button.dataset.id);
    else if(action==="inventory-colors-clear"){state.inventorySelectedColors.clear();renderInventoryColorFilter();renderInventory();el("inventoryColorFilter").open=false}
    else if(action==="parts-colors-clear"){state.partsSelectedColors.clear();savePartsColorSelection();partsPage=1;renderPartsColorFilter();renderParts();el("colorFilter").open=false}
    else if(action==="refresh-all-set-inventories")await refreshAllSetInventories(button);
    else if(action==="refresh-parts"){
      const original=button.textContent;
      button.disabled=true;button.textContent="↻ Wird aktualisiert …";
      try{const count=await refreshPartsView();toast(`Fehlteile aktualisiert · ${count} Einträge geladen.`)}
      finally{button.disabled=false;button.textContent=original}
    }
    else if(action==="inventory-check")await updateInventoryItem(button.dataset.id,0,button.checked);
    else if(action==="minifigure-part-present")await updateMinifigurePart(button.dataset.id,null,true);
    else if(action==="minifigure-part-missing")await updateMinifigurePart(button.dataset.id,null,false);
    else if(action==="save-api-key")await saveApiKey();
    else if(action==="close-modal")closeModal(button.dataset.modal);
    else if(action==="toggle-theme")await toggleTheme();
    else if(action==="zoom-image"){el("zoomImage").src=button.dataset.src;openModal("imageModal")}
    else if(action==="cycle-status")await cycleStatus(Number(button.dataset.id));
    else if(action==="cycle-group-status")await cycleGroupStatus(button.dataset.ids.split(",").map(Number),button.dataset.status);
    else if(action==="bulk-status")await bulkParts(button.dataset.status);
    else if(action==="bulk-trash")await bulkParts("trash");
    else if(action==="empty-trash")await emptyTrash();
    else if(action==="restore"){await request("/api/restore",{method:"POST",body:JSON.stringify({kind:button.dataset.kind,id:Number(button.dataset.id)})});toast("Wiederhergestellt.");await reloadData()}
    else if(action==="lookup-set"){const r=await request(`/api/lookup/set?number=${encodeURIComponent(clean(el("setNumber").value))}`);const s=r.set;el("setNumber").value=s.set_number;el("setName").value=s.name;el("setYear").value=s.year||"";el("setTotalParts").value=s.total_parts||0;el("setImage").value=s.image_url||"";toast("Setdaten geladen.")}
    else if(action==="lookup-complete-set")await lookupCompleteSet();
    else if(action==="lookup-purchased-set")await lookupPurchasedSet();
    else if(action==="backup")await createBackup();
    else if(action==="clear-cache")await clearCache();
    else if(action==="delete-user")await deleteCurrentUser();
    else if(action==="export-json")download(`/api/export/json?user_id=${state.userId}`);
    else if(action==="export-csv")download(`/api/export/csv?user_id=${state.userId}`);
    else if(action==="quit")await quit();
    else if(action==="edit-part")openPart(state.parts.find(p=>p.id===Number(button.dataset.id)));
    else if(action==="delete-part")await deletePart(Number(button.dataset.id));
    else if(action==="delete-open-part")await deleteOpenPart(Number(button.dataset.id));
    else if(action==="delete-part-group")await deletePartGroup(button.dataset.ids.split(",").map(Number));
    else if(action==="history-part")await showHistory(Number(button.dataset.id));
    else if(action==="parts-page"){partsPage=Number(button.dataset.page)||1;renderParts();el("partsTable").scrollIntoView({behavior:"smooth",block:"start"})}
    else if(action==="edit-set")openSet(state.sets.find(s=>s.id===Number(button.dataset.id)));
    else if(action==="delete-set")await deleteSet(Number(button.dataset.id));
    else if(action==="add-part-to-set"){openPart();el("partSet").value=button.dataset.id}
  }catch(error){toast(error.message,true)}
});

document.addEventListener("change",async event=>{
  const control=event.target.closest('input[data-action="part-presence"],input[data-action="part-owned"],input[data-action="unassigned-found"]');
  if(!control)return;
  control.disabled=true;
  try{
    if(control.dataset.action==="unassigned-found")await setUnassignedFound(control.dataset.ids.split(","),control.value);
    else if(control.dataset.action==="part-owned")await setPartOwned(control.dataset.id,control.value);
    else await setPartPresence(control.dataset.id,control.checked);
  }catch(error){
    if(control.type==="checkbox")control.checked=!control.checked;
    control.disabled=false;
    toast(error.message,true);
  }
});

document.addEventListener("click",event=>{
  const nav=event.target.closest("[data-view]");
  if(nav)setView(nav.dataset.view);
});

el("partForm").addEventListener("submit",savePart);
el("setForm").addEventListener("submit",saveSet);
el("completeSetForm").addEventListener("submit",saveCompleteSet);
el("purchasedSetForm").addEventListener("submit",event=>savePurchasedSet(event).catch(error=>toast(error.message,true)));
el("locationForm").addEventListener("submit",saveLocation);
el("userForm").addEventListener("submit",saveUser);el("warehouseForm").addEventListener("submit",saveWarehouse);el("orderForm").addEventListener("submit",saveOrder);
el("noteForm").addEventListener("submit",event=>saveNote(event).catch(error=>toast(error.message,true)));el("noteSearch").addEventListener("input",renderNotes);
el("userSelect").addEventListener("change",switchUser);
const resetPartsPage=()=>{partsPage=1;renderParts()};
el("searchInput").addEventListener("input",resetPartsPage);
el("statusFilter").addEventListener("change",resetPartsPage);
el("sortSelect").addEventListener("change",resetPartsPage);el("shapeFilter").addEventListener("input",resetPartsPage);el("partSetFilter").addEventListener("change",resetPartsPage);el("partTypeFilter").addEventListener("change",resetPartsPage);el("rarityFilter").addEventListener("change",resetPartsPage);el("setSearch").addEventListener("input",renderSets);el("setFilter").addEventListener("change",renderSets);el("setYearFilter").addEventListener("change",renderSets);el("setSort").addEventListener("change",renderSets);el("warehouseSearch").addEventListener("input",renderWarehouse);
el("importInput").addEventListener("change",event=>{if(event.target.files[0])importJson(event.target.files[0]);event.target.value=""});
el("backupUploadInput").addEventListener("change",async event=>{
  const file=event.target.files[0];
  try{if(file)await uploadBackup(file)}catch(error){toast(error.message,true)}
  event.target.value="";
});

el("inventorySearch").addEventListener("input",renderInventory);
el("inventoryStateFilter").addEventListener("change",renderInventory);
el("inventorySpareFilter").addEventListener("change",renderInventory);
el("inventorySort").addEventListener("change",renderInventory);
document.addEventListener("change",event=>{
  const statusSelect=event.target.closest("[data-part-status-ids]");
  if(statusSelect){
    statusSelect.disabled=true;
    setGroupStatus(statusSelect.dataset.partStatusIds.split(",").map(Number),statusSelect.value).catch(error=>{statusSelect.disabled=false;toast(error.message,true)});
    return;
  }
  const input=event.target.closest("[data-inventory-color]");
  if(input){input.checked?state.inventorySelectedColors.add(input.dataset.inventoryColor):state.inventorySelectedColors.delete(input.dataset.inventoryColor);renderInventoryColorFilter();renderInventory();return}
  const partColor=event.target.closest("[data-parts-color]");
  if(!partColor)return;
  partColor.checked?state.partsSelectedColors.add(partColor.dataset.partsColor):state.partsSelectedColors.delete(partColor.dataset.partsColor);
  savePartsColorSelection();partsPage=1;updatePartsColorSummary();renderParts();
});
document.addEventListener("change",async event=>{
  const input=event.target.closest('[data-action="inventory-owned"],[data-action="minifigure-part-owned"]');
  if(!input)return;
  try{
    if(input.dataset.action==="minifigure-part-owned")await updateMinifigurePart(input.dataset.id,input.value,null);
    else await updateInventoryItem(input.dataset.id,input.value,false);
  }
  catch(error){toast(error.message,true)}
});

document.addEventListener("change",e=>{
  if(e.target.id==="selectAllMissingParts"){
    toggleAllVisibleParts(e.target.checked);
    return;
  }
  const group=e.target.closest("[data-part-ids]");
  if(group){
    const ids=group.dataset.partIds.split(",").map(Number);
    ids.forEach(id=>group.checked?state.selectedParts.add(id):state.selectedParts.delete(id));
    updateBulkSelectionUi();
    return;
  }
  const c=e.target.closest("[data-part-select]");
  if(c){
    const id=Number(c.dataset.partSelect);
    c.checked?state.selectedParts.add(id):state.selectedParts.delete(id);
    updateBulkSelectionUi();
  }
});
document.addEventListener("keydown",e=>{if(e.ctrlKey&&e.key.toLowerCase()==="n"){e.preventDefault();openPart()}if(e.ctrlKey&&e.key.toLowerCase()==="s"){e.preventDefault();createBackup()}if(e.key==="Delete"&&state.selectedParts.size){bulkParts("trash")}});document.addEventListener("dragover",e=>e.preventDefault());document.addEventListener("drop",e=>{e.preventDefault();const f=e.dataTransfer.files[0];if(f&&f.name.toLowerCase().endsWith(".json"))importJson(f)});
window.addEventListener("error",event=>toast("JavaScript-Fehler: "+event.message,true));
window.addEventListener("unhandledrejection",event=>toast("Fehler: "+(event.reason?.message||event.reason),true));

function applyAppearance(){
  const theme=state.settings.theme==="light"?"light":"dark";
  const light=theme==="light";
  document.documentElement.classList.toggle("light",light);
  document.documentElement.classList.toggle("font-small",state.settings.font_size==="small");
  document.documentElement.classList.toggle("font-large",state.settings.font_size==="large");
  document.body.classList.toggle("density-compact",state.settings.density==="compact");
  el("app").classList.toggle("sidebar-collapsed",state.settings.sidebar_collapsed==="true");
  syncSidebarButton();
  if(el("themePreference"))el("themePreference").value=theme;
  if(el("fontSizePreference"))el("fontSizePreference").value=state.settings.font_size||"normal";
  if(el("densityPreference"))el("densityPreference").value=state.settings.density||"comfortable";
  if(el("dashboardRecentPreference"))el("dashboardRecentPreference").checked=state.settings.dashboard_recent!=="false";
}

function syncSidebarButton(){
  const collapsed=el("app").classList.contains("sidebar-collapsed");
  const button=document.querySelector('[data-action="toggle-sidebar"]');
  const text=collapsed?"Seitenleiste ausklappen":"Seitenleiste einklappen";
  button?.setAttribute("aria-expanded",String(!collapsed));
  button?.setAttribute("aria-label",text);
  button?.setAttribute("title",text);
  const label=button?.querySelector("span");
  if(label)label.textContent=text;
}

async function savePreferences(settings){
  await request("/api/settings",{method:"POST",body:JSON.stringify({settings})});
  Object.assign(state.settings,settings);applyAppearance();
}
async function saveAppearance(){await savePreferences({theme:el("themePreference").value,font_size:el("fontSizePreference").value,density:el("densityPreference").value,dashboard_recent:String(el("dashboardRecentPreference").checked)});toast("Darstellung gespeichert.")}
async function toggleSidebar(){
  const app=el("app");
  const collapsed=!app.classList.contains("sidebar-collapsed");
  app.classList.toggle("sidebar-collapsed",collapsed);
  syncSidebarButton();
  try{
    await savePreferences({sidebar_collapsed:String(collapsed)});
  }catch(error){
    app.classList.toggle("sidebar-collapsed",!collapsed);
    syncSidebarButton();
    throw error;
  }
}

let confirmResolver=null,confirmReturnsInput=false;
function askConfirm(message,{title="Aktion bestätigen",danger=true,password=false}={}){
  confirmReturnsInput=false;
  el("confirmTitle").textContent=title;el("confirmMessage").textContent=message;
  el("confirmPasswordWrap").classList.toggle("hidden",!password);el("confirmPassword").value="";
  el("confirmAccept").classList.toggle("danger-btn",danger);openModal("confirmModal");
  return new Promise(resolve=>{confirmResolver=resolve});
}
function askInput(message,{title="Eingabe erforderlich",type="text",label="Wert"}={}){confirmReturnsInput=true;el("confirmTitle").textContent=title;el("confirmMessage").textContent=message;el("confirmPasswordWrap").classList.remove("hidden");el("confirmPasswordWrap").childNodes[0].textContent=label;el("confirmPassword").type=type;el("confirmPassword").value="";el("confirmAccept").classList.remove("danger-btn");openModal("confirmModal");requestAnimationFrame(()=>el("confirmPassword").focus());return new Promise(resolve=>{confirmResolver=resolve})}
function resolveConfirm(value){const result=value?(confirmReturnsInput?clean(el("confirmPassword").value):true):false;closeModal("confirmModal");const resolver=confirmResolver;confirmResolver=null;confirmReturnsInput=false;resolver?.(result)}

function commandItems(){
  const items=[
    {type:"Aktion",title:"Fehlteil hinzufügen",detail:"Neuen fehlenden Stein erfassen",action:"open-part"},
    {type:"Aktion",title:"Set hinzufügen",detail:"Neues LEGO-Set anlegen",action:"open-set"},
    {type:"Aktion",title:"Backup erstellen",detail:"Verschlüsselte Sicherung erstellen",action:"backup"},
    {type:"Navigation",title:"Dashboard",detail:"Übersicht öffnen",view:"dashboard"},
    {type:"Navigation",title:"Einstellungen",detail:"Persönliche Einstellungen öffnen",view:"settings"},
    ...state.sets.map(x=>({type:"Set",title:x.name,detail:x.set_number,view:"sets",search:x.name+" "+x.set_number})),
    ...state.parts.map(x=>({type:"Fehlteil",title:x.name,detail:`Element ${x.element_id} · ${x.color||"ohne Farbe"}`,view:"parts",search:[x.name,x.element_id,x.color,x.set_name].join(" ")})),
    ...state.warehouse.map(x=>({type:"Lager",title:x.name,detail:`${x.quantity} Stück · ${x.color||"ohne Farbe"}`,view:"warehouse",search:[x.name,x.element_id,x.color].join(" ")})),
    ...state.orders.map(x=>({type:"Bestellung",title:x.supplier,detail:x.order_number||labelStatus(x.status),view:"orders",search:[x.supplier,x.order_number,x.status].join(" ")}))
  ];
  return items;
}
function renderCommands(){
  const query=clean(el("commandInput").value).toLowerCase();
  const items=commandItems().filter(x=>!query||`${x.title} ${x.detail} ${x.search||""}`.toLowerCase().includes(query)).slice(0,40);
  let group="";
  el("commandResults").innerHTML=items.map((item,index)=>{const heading=item.type!==group?`<div class="command-group">${esc(group=item.type)}</div>`:"";return`${heading}<button type="button" class="command-item ${index===0?"active":""}" data-command-index="${index}"><div><strong>${esc(item.title)}</strong><small>${esc(item.detail)}</small></div></button>`}).join("")||'<div class="empty">Keine Ergebnisse gefunden.</div>';
  el("commandResults")._items=items;
}
function openCommand(){openModal("commandModal");el("commandInput").value="";renderCommands();requestAnimationFrame(()=>el("commandInput").focus())}
async function runCommand(index){const item=el("commandResults")._items?.[index];if(!item)return;closeModal("commandModal");if(item.view)setView(item.view);if(item.action)document.querySelector(`[data-action="${item.action}"]`)?.click()}

function renderAdminUsers(){
  if(state.authUser?.role!=="admin")return;
  const query=clean(el("adminUserSearch").value).toLowerCase(),filter=el("adminUserFilter").value;
  const users=state.users.filter(user=>(user.name+" "+(user.email||"")).toLowerCase().includes(query)&&(filter==="all"||(filter==="active"&&!user.disabled&&!user.deleted_at)||(filter==="disabled"&&user.disabled&&!user.deleted_at)||(filter==="deleted"&&user.deleted_at)));
  el("adminUserSummary").textContent=`${users.length} von ${state.users.length} Konten angezeigt.`;
  el("adminUsers").innerHTML=users.map(user=>{const own=Number(user.id)===Number(state.authUser.id),deleted=Boolean(user.deleted_at),disabled=Boolean(user.disabled);return`<article class="admin-user"><div class="admin-user-main"><div class="admin-avatar">${esc(user.name).slice(0,1).toUpperCase()}</div><div><div class="admin-user-name">${esc(user.name)}${user.role==="admin"?'<span class="role-badge">Admin</span>':""}</div><div class="sub">${esc(user.email||"Keine E-Mail")} · Letzte Anmeldung: ${esc(user.last_login||"nie")}</div></div></div><div class="admin-user-actions">${deleted?`<button class="btn" data-action="manage-user-restore" data-id="${user.id}">Wiederherstellen</button>`:`<button class="btn" data-action="manage-user-open" data-id="${user.id}" ${disabled?"disabled":""}>Sammlung öffnen</button>${user.role!=="admin"?`<button class="btn" data-action="manage-user-email" data-id="${user.id}">E-Mail ändern</button>`:""}<button class="btn" data-action="manage-user-toggle" data-id="${user.id}" ${own?"disabled":""}>${disabled?"Aktivieren":"Deaktivieren"}</button><button class="btn" data-action="manage-user-reset" data-id="${user.id}" ${own?"disabled":""}>Passwort zurücksetzen</button><button class="btn danger-btn" data-action="manage-user-delete" data-id="${user.id}" ${own?"disabled":""}>Löschen</button>`}</div></article>`}).join("")||'<div class="empty">Keine Konten gefunden.</div>';
}
async function loadAudit(){const data=await request("/api/admin/audit");state.audit=data.audit||[];el("auditTable").innerHTML=state.audit.length?`<table><thead><tr><th>Zeit</th><th>Aktion</th><th>Admin</th><th>Ziel</th><th>Details</th></tr></thead><tbody>${state.audit.map(x=>`<tr><td>${esc(x.created_at)}</td><td>${esc(x.action)}</td><td>${esc(x.actor_name||"System")}</td><td>${esc(x.target_name||"–")}</td><td>${esc(x.details||"")}</td></tr>`).join("")}</tbody></table>`:'<div class="empty">Keine Protokolleinträge.</div>'}
async function loadMariaAdmin(){const data=await request("/api/admin/database"),p=data.profile||{};el("databaseEngine").value=p.engine||"sqlite";el("mariaHost").value=p.host||"";el("mariaPort").value=p.port||3306;el("mariaDatabase").value=p.database||"";el("mariaUser").value=p.user||"";el("mariaPassword").value="";el("mariaSsl").checked=p.ssl!==false;el("mariaStatus").textContent=p.engine==="mariadb"?"MariaDB aktiv":"SQLite aktiv";updateDatabaseEngineUi();renderMariaTables(data.tables||[])}
function renderMariaTables(tables){el("mariaTables").innerHTML=tables.length?`<table><thead><tr><th>Tabelle</th><th>Engine</th><th>Zeilen</th></tr></thead><tbody>${tables.map(t=>`<tr><td>${esc(t.TABLE_NAME||t.table_name)}</td><td>${esc(t.ENGINE||t.engine)}</td><td>${Number(t.TABLE_ROWS??t.table_rows??0)}</td></tr>`).join("")}</tbody></table>`:""}
function updateDatabaseEngineUi(){const maria=el("databaseEngine").value==="mariadb";el("mariaFields").classList.toggle("hidden",!maria);document.querySelectorAll('[data-action="test-mariadb"],[data-action="sync-mariadb"]').forEach(x=>x.classList.toggle("hidden",!maria))}
function mariaPayload(){return{engine:el("databaseEngine").value,host:clean(el("mariaHost").value),port:Number(el("mariaPort").value)||3306,database:clean(el("mariaDatabase").value),user:clean(el("mariaUser").value),password:el("mariaPassword").value,ssl:el("mariaSsl").checked}}
async function saveMaria(event){event.preventDefault();const result=await request("/api/admin/database/save",{method:"POST",body:JSON.stringify(mariaPayload())});if(result.engine==="sqlite"){toast("SQLite wurde aktiviert. Die Datenbankauswahl wurde gespeichert.")}else{const sync=result.sync||{};toast(`MariaDB wurde aktiviert · ${Number(sync.tables||0)} Tabellen und ${Number(sync.rows||0)} Datensätze übernommen.`)}await loadMariaAdmin()}

async function loadEmailAdmin(){const data=await request("/api/admin/email"),c=data.config||{};el("emailMode").value=c.mode||"smtp";el("smtpHost").value=c.host||"";el("smtpPort").value=c.port||587;el("smtpSender").value=c.sender||"";el("resendSenderName").value=c.sender_name||"BrickMissing";el("smtpUsername").value=c.username||"";el("smtpSecurity").value=c.security||"starttls";el("smtpPassword").value="";el("resendApiKey").value="";el("resendKeyStatus").value=c.api_key_configured?"Verschlüsselt gespeichert":"Noch nicht gespeichert";el("smtpEnabled").checked=c.enabled!==false;el("smtpTestRecipient").value=c.sender||"";el("smtpStatus").textContent=c.configured?(c.enabled?`${c.mode==="resend"?"Resend":"SMTP"} aktiv`:"Deaktiviert"):"Nicht konfiguriert";updateEmailModeUi()}
async function loadPricingAdmin(){const data=await request("/api/admin/pricing"),c=data.config||{};el("bricksetApiKey").value="";el("pricingStatus").textContent=c.brickset_configured?"LEGO + Brickset":"LEGO Pick a Brick";el("pricingResult").textContent=c.brickset_configured?"Kostenlose Teile- und Setpreisquellen sind aktiv.":"Teilepreise funktionieren ohne Schlüssel. Für Setpreise kann optional ein kostenloser Brickset-Schlüssel hinterlegt werden."}
function pricingPayload(){return{brickset_api_key:el("bricksetApiKey").value}}
async function savePricing(event){event.preventDefault();await request("/api/admin/pricing/save",{method:"POST",body:JSON.stringify({config:pricingPayload()})});toast("Kostenlose Preisquellen wurden gespeichert.");await loadPricingAdmin()}
async function testPricing(){el("pricingResult").textContent="Preisquellen werden geprüft …";const data=await request("/api/admin/pricing/test",{method:"POST",body:"{}"});el("pricingResult").textContent=Object.entries(data.result).map(([source,x])=>`${source}: ${Number(x.value||0).toFixed(2)} ${x.currency||"EUR"}`).join(" · ");toast("Preisquellen funktionieren.")}
async function syncPrices(){el("pricingResult").textContent="Marktpreise werden geladen. Das kann einige Minuten dauern …";const data=await request("/api/admin/pricing/sync",{method:"POST",body:JSON.stringify({user_id:state.userId})});el("pricingResult").textContent=`${data.updated_sets} Sets und ${data.updated_parts} unterschiedliche Teile aktualisiert${data.errors?` · ${data.errors} ohne Preis`:""}. ${data.messages?.join(" | ")||""}`;await reloadData();toast("Marktpreise wurden aktualisiert.")}
function updateEmailModeUi(){const mode=el("emailMode").value,isSmtp=mode==="smtp",isResend=mode==="resend",active=mode!=="disabled";el("emailConfigFields").hidden=!active;el("smtpFields").hidden=!isSmtp;el("resendFields").hidden=!isResend;el("resendNameField").hidden=!isResend;el("smtpAutoButton").hidden=!isSmtp;el("emailTestButton").hidden=!active;el("emailModeHint").hidden=!active;el("smtpStatus").hidden=!active;el("smtpHost").required=isSmtp;el("smtpPort").required=isSmtp;el("smtpSender").required=active}
function emailPayload(){return{mode:el("emailMode").value,host:clean(el("smtpHost").value),port:Number(el("smtpPort").value)||587,sender:clean(el("smtpSender").value),sender_name:clean(el("resendSenderName").value),username:clean(el("smtpUsername").value),password:el("smtpPassword").value,api_key:el("resendApiKey").value,security:el("smtpSecurity").value,enabled:el("smtpEnabled").checked}}
async function saveEmail(event){event.preventDefault();await request("/api/admin/email/save",{method:"POST",body:JSON.stringify(emailPayload())});toast("E-Mail-Konfiguration verschlüsselt gespeichert.");await loadEmailAdmin()}

async function logout(){await request("/api/auth/logout",{method:"POST",body:"{}"});location.reload()}
async function changePassword(event){event.preventDefault();const next=el("newPassword").value;if(next!==el("confirmNewPassword").value)throw new Error("Die neuen Passwörter stimmen nicht überein.");await request("/api/auth/password",{method:"POST",body:JSON.stringify({current_password:el("currentPassword").value,new_password:next})});event.target.reset();updatePasswordStrength();toast("Passwort geändert.")}
function updatePasswordStrength(){const value=el("newPassword").value,rules={length:value.length>=8,upper:/[A-ZÄÖÜ]/.test(value),lower:/[a-zäöüß]/.test(value),number:/\\d/.test(value)};Object.entries(rules).forEach(([key,valid])=>document.querySelector(`[data-rule="${key}"]`)?.classList.toggle("valid",valid));const score=Object.values(rules).filter(Boolean).length;el("passwordMeter").style.width=`${score*25}%`;el("passwordMeter").style.background=score<2?"var(--red)":score<4?"var(--yellow)":"var(--green)";el("passwordForm").querySelector("button[type=submit]").disabled=score<4||value!==el("confirmNewPassword").value}

function renderMobileCards(){
  const configs=[["partsTable",state.parts,x=>`<strong>${esc(x.name)}</strong><div class="mobile-card-row"><span>Element</span><span>${esc(x.element_id)}</span></div><div class="mobile-card-row"><span>Status</span><span>${labelStatus(x.status)}</span></div>`],["warehouseTable",state.warehouse,x=>`<strong>${esc(x.name)}</strong><div class="mobile-card-row"><span>Farbe</span><span>${esc(x.color||"–")}</span></div><div class="mobile-card-row"><span>Menge</span><span>${x.quantity}</span></div>`],["ordersTable",state.orders,x=>`<strong>${esc(x.supplier)}</strong><div class="mobile-card-row"><span>Status</span><span>${labelStatus(x.status)}</span></div><div class="mobile-card-row"><span>Gesamt</span><span>${Number(x.total).toFixed(2)} €</span></div>`]];
  for(const [id,items,template] of configs){const host=el(id);let cards=host.querySelector(".mobile-cards");if(!cards){cards=document.createElement("div");cards.className="mobile-cards";host.append(cards)}cards.innerHTML=items.map(x=>`<article class="mobile-card">${template(x)}</article>`).join("")}
}
const originalRenderAll=renderAll;renderAll=function(){originalRenderAll();renderMobileCards();renderFilterChips();enhanceImages();enhanceEmptyStates()}
function renderFilterChips(){document.querySelectorAll(".filter-chips").forEach(x=>x.remove());const chips=[];if(el("searchInput").value)chips.push(["searchInput",`Suche: ${el("searchInput").value}`]);if(el("statusFilter").value!=="all")chips.push(["statusFilter",labelStatus(el("statusFilter").value)]);if(!chips.length)return;const bar=document.createElement("div");bar.className="filter-chips";bar.innerHTML=chips.map(([id,label])=>`<span class="filter-chip">${esc(label)}<button type="button" data-clear-filter="${id}" aria-label="Filter entfernen">×</button></span>`).join("")+'<button type="button" class="btn" data-clear-filter="all">Alle zurücksetzen</button>';el("partsTable").before(bar)}
function enhanceImages(){
  document.querySelectorAll("img").forEach(img=>{
    const source=clean(img.getAttribute("src"));
    if(/^https:\/\//i.test(source)){
      img.dataset.originalSrc=source;
      img.src=proxiedImage(source);
    }
    if(img.dataset.imageEnhanced)return;
    img.dataset.imageEnhanced="1";
    img.parentElement?.classList.add("image-loading");
    img.addEventListener("load",()=>{
      img.style.display="";
      img.parentElement?.classList.remove("image-loading","image-error");
    });
    img.addEventListener("error",()=>{
      img.parentElement?.classList.remove("image-loading");
      img.parentElement?.classList.add("image-error");
      imageFailed(img,img.alt||"Bild");
    });
  });
}
function enhanceEmptyStates(){document.querySelectorAll(".empty").forEach(node=>{if(node.querySelector(".btn"))return;const text=node.textContent||"";let action=text.includes("Set")?"open-set":text.includes("Fehlteil")?"open-part":null;if(action)node.insertAdjacentHTML("beforeend",`<button type="button" class="btn primary" data-action="${action}">Ersten Eintrag hinzufügen</button>`)})}
function markUnknownMarketPrices(){
  document.querySelectorAll(".set-price-row>div:nth-child(2) strong,#partsTable tbody tr td:nth-child(7)").forEach(node=>{
    if(/^\s*0([,.]00)?\s*€\s*$/.test(node.textContent||""))node.textContent="Noch nicht ermittelt";
  });
}
new MutationObserver(markUnknownMarketPrices).observe(document.body,{childList:true,subtree:true});

let authMode="login",adminExists=false;
function setAuthMode(mode){authMode=mode;document.querySelectorAll("[data-auth-tab]").forEach(b=>b.classList.toggle("primary",b.dataset.authTab===mode));const registration=mode==="register",firstAdmin=registration&&!adminExists;el("authConfirmWrap").classList.toggle("hidden",!registration);el("authEmailWrap").classList.toggle("hidden",!registration||firstAdmin);el("authEmail").required=registration&&!firstAdmin;el("authNameLabel").textContent=registration?"Benutzername":"Benutzername oder E-Mail-Adresse";el("authTitle").textContent=firstAdmin?"Erstes Administratorkonto erstellen":registration?"Konto erstellen":"Willkommen zurück";el("authSubmit").textContent=firstAdmin?"Administrator erstellen":registration?"Registrieren":"Anmelden";el("authError").textContent=""}
async function initialize(){const status=await request("/api/auth/status");adminExists=status.admin_exists;if(status.authenticated){el("authPage").classList.add("hidden");el("app").classList.remove("hidden");await bootstrap()}else setAuthMode("login")}

document.querySelectorAll("[data-auth-tab]").forEach(button=>button.addEventListener("click",()=>setAuthMode(button.dataset.authTab)));
el("authForm").addEventListener("submit",async event=>{event.preventDefault();el("authError").textContent="";const name=clean(el("authName").value),email=clean(el("authEmail").value),password=el("authPassword").value;if(authMode==="register"&&password!==el("authConfirm").value){el("authError").textContent="Die Passwörter stimmen nicht überein.";return}try{const url=authMode==="register"?"/api/auth/register":"/api/auth/login",payload=authMode==="register"?{name,email,password}:{identifier:name,password};await request(url,{method:"POST",body:JSON.stringify(payload)});el("authPage").classList.add("hidden");el("app").classList.remove("hidden");await bootstrap()}catch(error){el("authError").textContent=error.message}});
el("passwordForm").addEventListener("submit",event=>changePassword(event).catch(error=>toast(error.message,true)));
el("newPassword").addEventListener("input",updatePasswordStrength);el("confirmNewPassword").addEventListener("input",updatePasswordStrength);
el("mariaForm").addEventListener("submit",event=>saveMaria(event).catch(error=>toast(error.message,true)));el("databaseEngine").addEventListener("change",updateDatabaseEngineUi);
el("smtpForm").addEventListener("submit",event=>saveEmail(event).catch(error=>toast(error.message,true)));el("emailMode").addEventListener("change",updateEmailModeUi);
el("pricingForm").addEventListener("submit",event=>savePricing(event).catch(error=>toast(error.message,true)));
el("adminUserSearch").addEventListener("input",renderAdminUsers);el("adminUserFilter").addEventListener("change",renderAdminUsers);
el("commandInput").addEventListener("input",renderCommands);
document.addEventListener("click",async event=>{
  const clear=event.target.closest("[data-clear-filter]");if(clear){if(clear.dataset.clearFilter==="all"){el("searchInput").value="";el("statusFilter").value="all"}else{const input=el(clear.dataset.clearFilter);input.value=input.tagName==="SELECT"?"all":""}renderParts();renderFilterChips();return}
  const command=event.target.closest("[data-command-index]");if(command){await runCommand(Number(command.dataset.commandIndex));return}
  const button=event.target.closest("[data-action]");if(!button)return;
  try{const action=button.dataset.action;
    if(action==="open-command")openCommand();else if(action==="toggle-sidebar")await toggleSidebar();else if(action==="save-appearance")await saveAppearance();else if(action==="logout")await logout();
    else if(action==="confirm-cancel")resolveConfirm(false);else if(action==="confirm-accept")resolveConfirm(true);
    else if(action==="refresh-audit")await loadAudit();else if(action==="test-mariadb"){const result=await request("/api/admin/database/test",{method:"POST",body:JSON.stringify(mariaPayload())});toast(result.writable?`MariaDB ${result.version||""} ist erreichbar und beschreibbar.`:result.message,!result.writable)}else if(action==="sync-mariadb"){const result=await request("/api/admin/database/sync",{method:"POST",body:"{}"});toast(`MariaDB synchronisiert · ${Number(result.tables||0)} Tabellen und ${Number(result.rows||0)} Datensätze übernommen.`);await loadMariaAdmin()}
    else if(action==="test-smtp"){await request("/api/admin/email/test",{method:"POST",body:JSON.stringify({recipient:clean(el("smtpTestRecipient").value)})});toast("Testmail versendet.")}
    else if(action==="test-pricing")await testPricing()
    else if(action==="sync-prices")await syncPrices()
    else if(action==="manage-user-open"){state.userId=Number(button.dataset.id);await request("/api/settings",{method:"POST",body:JSON.stringify({settings:{current_user:state.userId}})});await reloadData();toast("Sammlung geöffnet.")}
    else if(action==="manage-user-toggle"){await manageUser("toggle",button.dataset.id)}
    else if(action==="manage-user-restore"){await manageUser("restore",button.dataset.id)}
    else if(action==="manage-user-reset"){const password=await askInput("Temporäres Passwort mit mindestens 8 Zeichen eingeben.",{title:"Passwort zurücksetzen",type:"password",label:"Temporäres Passwort"});if(password)await manageUser("reset-password",button.dataset.id,{password})}
    else if(action==="manage-user-email"){const email=await askInput("Neue E-Mail-Adresse eingeben.",{title:"E-Mail-Adresse ändern",type:"email",label:"E-Mail-Adresse"});if(email)await manageUser("email",button.dataset.id,{email})}
    else if(action==="manage-user-delete"){if(await askConfirm("Benutzerkonto wirklich löschen?",{title:"Benutzer löschen"})){await request(`/api/users/${button.dataset.id}`,{method:"DELETE"});await bootstrap()}}
    else if(action==="open-warehouse"){el("warehouseForm").reset();openModal("warehouseModal")}
    else if(action==="open-order"){el("orderForm").reset();el("orderId").value="";openModal("orderModal")}
    else if(action==="test-api-key"){await request("/api/settings/test-key",{method:"POST",body:JSON.stringify({api_key:clean(el("rebrickableKey").value)})});toast("API-Key funktioniert.")}
    else if(action==="remove-api-key"){if(await askConfirm("Eigenen Rebrickable API-Key entfernen?",{title:"API-Key entfernen"})){await request("/api/settings",{method:"POST",body:JSON.stringify({settings:{rebrickable_api_key:""}})});state.settings.rebrickable_api_key_configured=false;el("apiKeyStatus").textContent="Für dein Konto ist noch kein API-Key gespeichert.";toast("API-Key entfernt.")}}
  }catch(error){toast(error.message,true)}
});
async function manageUser(action,id,extra={}){
  const payload={user_id:Number(id),...extra};
  if(payload.password){payload.temporary_password=payload.password;delete payload.password}
  await request(`/api/users/${action}`,{method:"POST",body:JSON.stringify(payload)});
  toast("Benutzerkonto aktualisiert.");
  await bootstrap()
}
async function deletePart(id){if(!await askConfirm("Fehlteil in den Papierkorb verschieben?",{title:"Fehlteil löschen"}))return;await request(`/api/parts/${id}`,{method:"DELETE"});toast("Fehlteil verschoben.");await reloadData()}
async function deleteOpenPart(id){if(!id)return;if(!await askConfirm("Diesen Fehlteil-Eintrag wirklich in den Papierkorb verschieben?",{title:"Fehlteil löschen",danger:true}))return;await request(`/api/parts/${id}`,{method:"DELETE"});closeModal("partModal");toast("Fehlteil wurde in den Papierkorb verschoben.");await reloadData()}
async function deleteSet(id){if(!await askConfirm("Set in den Papierkorb verschieben? Zugeordnete Fehlteile bleiben erhalten.",{title:"Set löschen"}))return;await request(`/api/sets/${id}`,{method:"DELETE"});toast("Set verschoben.");await reloadData()}
async function emptyTrash(){const total=state.trash.parts.length+state.trash.sets.length;if(!total)return toast("Der Papierkorb ist leer.");if(!await askConfirm(`${state.trash.parts.length} Fehlteile und ${state.trash.sets.length} Sets endgültig löschen?`,{title:"Papierkorb endgültig leeren"}))return;const result=await request("/api/trash/empty",{method:"POST",body:JSON.stringify({user_id:state.userId})});toast(`${result.deleted_parts} Fehlteile und ${result.deleted_sets} Sets gelöscht.`);await reloadData()}
async function bulkParts(action){const ids=[...state.selectedParts];if(!ids.length)return;if(!await askConfirm(`${ids.length} ausgewählte Einträge bearbeiten?`,{title:"Mehrfachaktion bestätigen",danger:action==="trash"}))return;await request("/api/bulk-parts",{method:"POST",body:JSON.stringify({ids,action})});state.selectedParts.clear();toast("Mehrfachaktion ausgeführt.");await reloadData()}
document.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){event.preventDefault();openCommand()}if(event.key==="Escape"&&!el("commandModal").classList.contains("hidden"))closeModal("commandModal")});
window.addEventListener("beforeunload",event=>{if(state.dirtyForms.size){event.preventDefault();event.returnValue=""}});
document.querySelectorAll("form").forEach(form=>{form.addEventListener("input",()=>{state.dirtyForms.add(form.id);const submit=form.querySelector('button[type="submit"],button:not([type])');if(submit)submit.disabled=!form.checkValidity()});form.addEventListener("submit",()=>state.dirtyForms.delete(form.id));form.addEventListener("reset",()=>state.dirtyForms.delete(form.id))});

async function registerServiceWorker(){
  if(!("serviceWorker" in navigator))return;
  const registration=await navigator.serviceWorker.register("/service-worker.js",{scope:"/"});
  registration.addEventListener("updatefound",()=>{
    const worker=registration.installing;
    worker?.addEventListener("statechange",()=>{
      if(worker.state==="installed"&&navigator.serviceWorker.controller){
        toast("Eine neue BrickMissing-Version ist bereit. Die Seite wird aktualisiert.");
        setTimeout(()=>location.reload(),900);
      }
    });
  });
}

registerServiceWorker().catch(error=>console.warn("Service Worker:",error));
initialize().catch(error=>{el("authError").textContent=error.message;toast(error.message,true)});
