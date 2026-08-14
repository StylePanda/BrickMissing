(() => {
  const studio = document.querySelector("[data-label-studio]");
  if (!studio) return;
  const form = studio.querySelector("[data-label-form]");
  let timer;
  async function refresh() {
    const url = `${form.action || window.location.pathname}?${new URLSearchParams(new FormData(form))}`;
    const response = await fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
    if (!response.ok) return;
    const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
    const preview = documentCopy.querySelector("[data-label-preview]");
    if (preview) studio.querySelector("[data-label-preview]").replaceWith(preview);
    window.history.replaceState({}, "", url);
  }
  function schedule() { window.clearTimeout(timer); timer = window.setTimeout(refresh, 180); }
  form.addEventListener("change", schedule);
  form.querySelector("[data-label-search]")?.addEventListener("input", schedule);
  document.querySelector("[data-label-select-all]")?.addEventListener("click", () => {
    form.querySelectorAll('input[name="item"]').forEach((item) => { item.checked = true; }); refresh();
  });
  form.querySelector("[data-label-select-none]")?.addEventListener("click", () => {
    form.querySelectorAll('input[name="item"]').forEach((item) => { item.checked = false; }); refresh();
  });
})();
