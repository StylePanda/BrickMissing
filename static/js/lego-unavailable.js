(() => {
  const filters = document.querySelector("[data-lego-analysis-filters]");
  const results = document.querySelector("[data-lego-analysis-results]");
  if (!filters || !results) return;

  const rows = [...results.querySelectorAll("[data-match-state]")];
  const buttons = [...filters.querySelectorAll("[data-match-filter]")];
  const search = filters.querySelector("[data-match-search]");
  const count = filters.querySelector("[data-match-count]");
  const empty = document.querySelector("[data-no-analysis-results]");
  let status = "all";

  const apply = () => {
    const query = search.value.trim().toLocaleLowerCase("de");
    let visible = 0;
    rows.forEach((row) => {
      const statusMatches = status === "all" || row.dataset.matchState === status;
      const searchMatches = !query || row.dataset.searchText.toLocaleLowerCase("de").includes(query);
      row.hidden = !(statusMatches && searchMatches);
      if (!row.hidden) visible += 1;
    });
    count.textContent = `${visible} ${visible === 1 ? "Eintrag" : "Einträge"} sichtbar`;
    empty.hidden = visible !== 0;
  };

  buttons.forEach((button) => button.addEventListener("click", () => {
    status = button.dataset.matchFilter;
    buttons.forEach((candidate) => candidate.setAttribute("aria-pressed", String(candidate === button)));
    apply();
  }));
  search.addEventListener("input", apply);
})();
