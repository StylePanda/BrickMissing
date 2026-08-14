"use strict";

const el = id => document.getElementById(id);
const clean = value => String(value ?? "").trim();
const esc = value => clean(value).replace(
  /[&<>"']/g,
  character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]
);

function setBusy(active){
  document.body.setAttribute("aria-busy", String(Boolean(active)));
  el("loadingBar")?.classList.toggle("active", Boolean(active));
}
