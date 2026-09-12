import {spawn} from "node:child_process";
import {mkdir, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";

const [baseUrl, browserPath, routesJson, artifactDirectory] = process.argv.slice(2);
if (!baseUrl || !browserPath || !routesJson) {
  throw new Error("Usage: responsive_ui_audit.mjs BASE_URL BROWSER_PATH ROUTES_JSON [ARTIFACT_DIR]");
}

const routes = JSON.parse(routesJson);
const username = process.env.BRICKMISSING_AUDIT_USERNAME;
const password = process.env.BRICKMISSING_AUDIT_PASSWORD;
if (!username || !password) throw new Error("Audit credentials are required.");

const port = 12000 + Math.floor(Math.random() * 7000);
const profile = join(tmpdir(), `brickmissing-edge-${process.pid}-${Date.now()}`);
const browser = spawn(browserPath, [
  "--headless=new",
  "--disable-gpu",
  "--no-sandbox",
  "--no-first-run",
  "--disable-extensions",
  "--remote-allow-origins=*",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], {stdio: "ignore"});

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const endpoint = `http://127.0.0.1:${port}`;

async function requestJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${url}`);
  return response.json();
}

async function waitForDebugger() {
  let lastError;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      return await requestJson(`${endpoint}/json/version`);
    } catch (error) {
      lastError = error;
      await delay(100);
    }
  }
  throw new Error(`Viewport ${width}x${height} failed after retry: ${lastError.message}`);
}

class CdpClient {
  constructor(url) {
    this.sequence = 0;
    this.pending = new Map();
    this.sessionId = undefined;
    this.socket = new WebSocket(url);
    this.socket.binaryType = "arraybuffer";
    this.ready = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error(`CDP WebSocket did not open: ${url}`)), 5000);
      this.socket.addEventListener("open", () => { clearTimeout(timeout); resolve(); }, {once: true});
      this.socket.addEventListener("error", (event) => { clearTimeout(timeout); reject(event.error || new Error(`CDP WebSocket failed: ${url}`)); }, {once: true});
    });
    this.socket.addEventListener("message", ({data}) => {
      let payload;
      try {
        payload = typeof data === "string" ? data : Buffer.from(data).toString("utf8");
      } catch (error) {
        process.stderr.write(`Unable to decode CDP message (${data?.constructor?.name}): ${error}\n`);
        return;
      }
      let message = JSON.parse(payload);
      if (message.method === "Target.receivedMessageFromTarget" && message.params?.message) {
        message = JSON.parse(message.params.message);
      }
      if (process.env.BRICKMISSING_AUDIT_DEBUG === "1") process.stderr.write(`CDP ${payload.slice(0, 500)}\n`);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    });
  }

  async send(method, params = {}, sessionId = this.sessionId) {
    await this.ready;
    if (sessionId) {
      const innerId = ++this.sequence;
      const innerResponse = this.createResponse(innerId, method);
      await this.send("Target.sendMessageToTarget", {
        sessionId,
        message: JSON.stringify({id: innerId, method, params}),
      }, null);
      return innerResponse;
    }
    const id = ++this.sequence;
    const response = this.createResponse(id, method);
    this.socket.send(JSON.stringify({id, method, params}));
    return response;
  }

  createResponse(id, method) {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, 10000);
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timeout); resolve(value); },
        reject: (error) => { clearTimeout(timeout); reject(error); },
      });
    });
  }

  close() {
    this.socket.close();
  }
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Browser evaluation failed");
  return result.result.value;
}

async function waitForReady(client) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const state = await evaluate(client, "document.readyState");
    if (state === "complete") {
      await delay(120);
      return;
    }
    await delay(50);
  }
  throw new Error("Page did not finish loading.");
}

async function navigate(client, path) {
  await client.send("Page.navigate", {url: new URL(path, baseUrl).href});
  await waitForReady(client);
}

async function setViewport(client, width, height) {
  await client.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width < 768,
    screenWidth: width,
    screenHeight: height,
  });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function auditOverflow(client, routeName, width) {
  const dimensions = await evaluate(client, `(() => ({
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
    tableContainers: [...document.querySelectorAll(".table-wrap")].map((node) => ({
      left: node.getBoundingClientRect().left,
      right: node.getBoundingClientRect().right,
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
      overflowX: getComputedStyle(node).overflowX
    })),
    images: [...document.images].map((node) => ({
      left: node.getBoundingClientRect().left,
      right: node.getBoundingClientRect().right,
      objectFit: getComputedStyle(node).objectFit
    }))
  }))()`);
  assert(dimensions.documentWidth <= width + 1, `${routeName} overflows at ${width}px: document ${dimensions.documentWidth}px`);
  assert(dimensions.bodyWidth <= width + 1, `${routeName} overflows at ${width}px: body ${dimensions.bodyWidth}px`);
  for (const table of dimensions.tableContainers) {
    assert(table.left >= -1 && table.right <= width + 1, `${routeName} table container escapes at ${width}px`);
    assert(["auto", "scroll"].includes(table.overflowX), `${routeName} table is not scroll-contained`);
  }
  for (const image of dimensions.images) {
    assert(image.left >= -1 && image.right <= width + 1, `${routeName} image escapes at ${width}px`);
  }
}

async function auditMissingParts(client, width) {
  const result = await evaluate(client, `(() => {
    const cards = [...document.querySelectorAll("[data-missing-card]")];
    const rect = (node) => {
      const value = node?.getBoundingClientRect();
      return value && {left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height};
    };
    const within = (child, parent) => !child || !parent || (
      child.left >= parent.left - 1 && child.right <= parent.right + 1
      && child.top >= parent.top - 1 && child.bottom <= parent.bottom + 1
    );
    return {
      cardCount: cards.length,
      hasLegacyTable: Boolean(document.querySelector(".missing-worktable, .missing-card-list table")),
      cards: cards.map((card) => ({
        rect: rect(card),
        columns: getComputedStyle(card).gridTemplateColumns.split(" ").filter(Boolean).length,
        allocationCount: card.querySelectorAll(".allocation-row").length,
        allocationRects: [...card.querySelectorAll(".allocation-row")].map((allocation) => {
          const allocationRect = rect(allocation);
          const controlsNode = allocation.querySelector(".allocation-controls");
          const controls = [...allocation.querySelectorAll("input:not([type=hidden]), select, button, a")].map((control) => ({
            tag: control.tagName,
            text: control.textContent.trim(),
            rect: rect(control),
          }));
          return {allocationRect, controlsRect: rect(controlsNode), controlsColumns: controlsNode ? getComputedStyle(controlsNode).gridTemplateColumns : "", controls, controlsFit: controls.every((control) => within(control.rect, allocationRect))};
        }),
        imageFits: [...card.querySelectorAll(".missing-card-image img, .allocation-thumb img")]
          .filter((image) => !image.hidden && image.getBoundingClientRect().width)
          .every((image) => getComputedStyle(image).objectFit === "contain" && within(rect(image), rect(image.parentElement))),
        progressRect: rect(card.querySelector("progress")),
        totalRect: rect(card.querySelector(".missing-card-total")),
        progressFits: within(rect(card.querySelector("progress")), rect(card.querySelector(".missing-card-total"))),
        stateVisible: Boolean(card.querySelector(".missing-card-state")?.getBoundingClientRect().height),
      })),
      filterPanel: rect(document.querySelector(".missing-filter-panel")),
      filterForm: rect(document.querySelector(".missing-filters")),
      filterActions: rect(document.querySelector(".missing-filter-actions")),
      resultsRegion: rect(document.querySelector(".missing-results-head")),
      resultsHeading: rect(document.querySelector(".missing-results-head h2")),
      resultsHead: document.querySelector(".missing-results-head h2")?.textContent || "",
      removedUi: [".missing-view-tools", ".save-view-details", ".save-view-form", ".saved-views", ".missing-view-label"].some((selector) => document.querySelector(selector)),
      removedText: ["Aktuelle Ansicht speichern", "Gespeicherte Ansichten", "Noch keine gespeicherten Ansichten", "Kartenansicht"].some((label) => document.body.textContent.includes(label)),
      orphanedAria: [...document.querySelectorAll("[aria-controls], [aria-labelledby]")].flatMap((node) => {
        const attribute = node.getAttribute("aria-controls") || node.getAttribute("aria-labelledby");
        return attribute.split(/\\s+/).filter((id) => !document.getElementById(id)).map((id) => ({element: node.outerHTML.slice(0, 180), id}));
      }),
    };
  })()`);
  assert(result.cardCount > 0, "Missing-parts cards are absent");
  assert(!result.hasLegacyTable, "Missing-parts view still renders the legacy table");
  assert(result.resultsHead.includes("Fehlteile"), "Missing-parts result heading lacks its label");
  assert(!result.removedUi && !result.removedText, `Removed missing-parts UI remains at ${width}px`);
  assert(!result.orphanedAria.length, `Missing-parts page has orphaned ARIA references at ${width}px: ${JSON.stringify(result.orphanedAria)}`);
  assert(result.filterPanel.left >= -1 && result.filterPanel.right <= width + 1, `Missing-parts filters escape at ${width}px`);
  assert(result.filterActions.bottom <= result.filterForm.bottom + 1 && result.filterForm.bottom <= result.filterPanel.bottom + 1, `Missing-parts filters have empty trailing space at ${width}px`);
  assert(result.filterPanel.bottom - result.filterActions.bottom <= 48, `Missing-parts filter panel keeps excessive space after its actions at ${width}px`);
  assert(result.filterPanel.bottom <= result.resultsRegion.top && result.resultsRegion.top - result.filterPanel.bottom <= 96, `Missing-parts results are too far from filters at ${width}px`);
  assert(Math.abs(result.resultsHeading.left - result.resultsRegion.left) <= 1, `Missing-parts result heading is not left aligned at ${width}px`);
  assert(result.cards[0]?.rect.top >= result.resultsRegion.bottom && result.cards[0]?.rect.top - result.resultsRegion.bottom <= 96, `Missing-parts cards are too far from heading at ${width}px`);
  assert(result.cards.some(({allocationCount}) => allocationCount >= 3), "Multiple set allocations are not grouped in one card");
  for (let index = 0; index < result.cards.length; index += 1) {
    const card = result.cards[index];
    assert(card.rect.left >= -1 && card.rect.right <= width + 1, `Missing-parts card escapes at ${width}px`);
    assert(card.allocationRects.every(({controlsFit}) => controlsFit), `Allocation controls are clipped at ${width}px: ${JSON.stringify(card.allocationRects)}`);
    assert(card.imageFits, `Missing-parts image is cropped or distorted at ${width}px`);
    assert(card.progressFits, `Missing-parts progress leaves its section at ${width}px: ${JSON.stringify({progress: card.progressRect, total: card.totalRect})}`);
    assert(card.stateVisible, `Missing-parts status/cost area is hidden at ${width}px`);
    const expectedColumns = width <= 900 ? 1 : width <= 1200 ? 2 : 4;
    assert(card.columns === expectedColumns, `Missing-parts card has ${card.columns} columns instead of ${expectedColumns} at ${width}px`);
    for (let otherIndex = index + 1; otherIndex < result.cards.length; otherIndex += 1) {
      const other = result.cards[otherIndex].rect;
      const overlaps = card.rect.left < other.right && card.rect.right > other.left
        && card.rect.top < other.bottom && card.rect.bottom > other.top;
      assert(!overlaps, `Missing-parts cards overlap at ${width}px`);
    }
  }
}

async function auditMinifigures(client, width) {
  const initial = await evaluate(client, `(() => {
    const rect = (node) => { const box = node.getBoundingClientRect(); return {left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height}; };
    const sets = [...document.querySelectorAll("[data-set-group]")];
    const figures = [...sets[0].querySelectorAll("[data-minifigure]")];
    const secondClosed = !sets[1].open;
    sets[1].open = true;
    const singleCard = rect(sets[1].querySelector(".minifigure-card"));
    const singleGrid = rect(sets[1].querySelector(".minifigure-grid"));
    sets[1].open = false;
    const kpis = [...document.querySelectorAll(".minifigure-kpi")].map(rect);
    const filters = [...document.querySelectorAll(".minifigure-filters > label")].map(rect);
    const select = document.querySelector('select[name="completeness"]');
    return {
      kpis, filters, sets: sets.length, firstOpen: sets[0].open, secondClosed,
      singleCardSpans: Math.abs(singleCard.width - singleGrid.width) <= 1,
      firstSetFigures: figures.length, figureRects: figures.map(rect),
      partClosed: !figures[0].querySelector(".minifigure-parts").open,
      values: [...document.querySelectorAll("[data-minifigure-kpi]")].map((node) => Number(node.textContent)),
      options: [...select.options].map((option) => option.value),
      hasTable: Boolean(document.querySelector(".minifigure-set-group table")),
      figureFallback: Boolean(document.querySelector(".minifigure-card-image.minifigure-image-fallback")),
      partFallback: Boolean(document.querySelector(".minifigure-part-image.minifigure-image-fallback")),
      links: Boolean(document.querySelector(".minifigure-set-name[href], .minifigure-edit[href]")),
      progress: [...figures].every((card) => card.querySelector("progress") && card.querySelector("[data-figure-status]")),
    };
  })()`);
  const overlaps = (first, second) => first.left < second.right && first.right > second.left && first.top < second.bottom && first.bottom > second.top;
  const noPairOverlap = (rects) => rects.every((first, index) => rects.slice(index + 1).every((second) => !overlaps(first, second)));
  assert(initial.sets === 2 && initial.firstOpen && initial.secondClosed, `Minifigure set collapse state is wrong at ${width}px`);
  assert(initial.firstSetFigures === 2 && initial.partClosed && !initial.hasTable, `Minifigure collection structure is wrong at ${width}px`);
  assert(initial.singleCardSpans, `Single minifigure does not fill its set group at ${width}px`);
  assert(initial.values.join(",") === "1,1,1", `Minifigure KPI values are wrong at ${width}px: ${initial.values}`);
  assert(initial.options.join(",") === ",complete,partial,missing", `Minifigure completeness options are wrong at ${width}px`);
  assert(initial.figureFallback && initial.partFallback, `Minifigure image fallbacks are missing at ${width}px`);
  assert(initial.links && initial.progress, `Minifigure actions or progress are missing at ${width}px`);
  assert(noPairOverlap(initial.kpis) && noPairOverlap(initial.filters) && noPairOverlap(initial.figureRects), `Minifigure cards or filters overlap at ${width}px`);
  if (width >= 1001) assert(Math.abs(initial.figureRects[0].top - initial.figureRects[1].top) <= 1, `Minifigures are not side by side at ${width}px`);
  else assert(initial.figureRects[1].top >= initial.figureRects[0].bottom, `Minifigures are not stacked at ${width}px`);

  const accordion = await evaluate(client, `(() => {
    const details = document.querySelector("[data-minifigure] .minifigure-parts");
    const summary = details.querySelector("summary");
    summary.focus();
    const focused = document.activeElement === summary;
    summary.click();
    return {focused, open: details.open};
  })()`);
  assert(accordion.focused && accordion.open, `Minifigure part accordion is not keyboard-focusable or clickable at ${width}px`);
  await evaluate(client, `Promise.all([...document.querySelector("[data-set-group]").querySelectorAll(".minifigure-set-image img, .minifigure-card-image img, .minifigure-part-image img")].map((img) => { img.loading = "eager"; return img.decode().catch(() => null); }))`);
  const expanded = await evaluate(client, `(() => {
    const rect = (node) => { const box = node.getBoundingClientRect(); return {left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height}; };
    const set = document.querySelector("[data-set-group]");
    const figure = set.querySelector("[data-minifigure]");
    const parts = [...figure.querySelectorAll("[data-minifigure-part]")];
    const images = [...set.querySelectorAll(".minifigure-set-image img, .minifigure-card-image img, .minifigure-part-image img")].map((node) => ({
      image: rect(node), wrapper: rect(node.parentElement), objectFit: getComputedStyle(node).objectFit,
      src: node.getAttribute("src"), currentSrc: node.currentSrc, naturalWidth: node.naturalWidth,
      naturalHeight: node.naturalHeight,
    }));
    return {
      set: rect(set), figure: rect(figure), parts: parts.map(rect), images,
      controls: [...figure.querySelectorAll(".minifigure-part-quantity input, .minifigure-part-quantity button")].map(rect),
      form: rect(figure.querySelector(".minifigure-part-quantity")),
      formGrid: getComputedStyle(figure.querySelector(".minifigure-part-quantity > div")).gridTemplateColumns,
      progress: rect(figure.querySelector("progress")), status: rect(figure.querySelector("[data-figure-status]")),
      detailsOpen: figure.querySelector(".minifigure-parts").open,
      visibleText: figure.querySelector(".minifigure-parts summary").innerText,
    };
  })()`);
  const inside = (child, parent) => child.left >= parent.left - 1 && child.right <= parent.right + 1 && child.top >= parent.top - 1 && child.bottom <= parent.bottom + 1;
  assert(expanded.detailsOpen && expanded.visibleText.includes("Einzelteile ausblenden"), `Minifigure part accordion did not open at ${width}px`);
  assert(expanded.parts.length === 2 && noPairOverlap(expanded.parts), `Minifigure part cards overlap at ${width}px`);
  if (width > 600) assert(Math.abs(expanded.parts[0].top - expanded.parts[1].top) <= 1, `Minifigure part cards are not side by side at ${width}px`);
  else assert(expanded.parts[1].top >= expanded.parts[0].bottom, `Minifigure part cards are not stacked at ${width}px`);
  assert(expanded.parts.every((part) => inside(part, expanded.figure)), `Minifigure part cards leave the figure card at ${width}px`);
  assert(expanded.controls.every((control) => control.width === 0 || expanded.parts.some((part) => inside(control, part))), `Minifigure quantity controls are clipped at ${width}px: ${JSON.stringify({controls: expanded.controls, form: expanded.form, formGrid: expanded.formGrid, parts: expanded.parts})}`);
  assert(inside(expanded.progress, expanded.figure) && inside(expanded.status, expanded.figure), `Minifigure progress or status is clipped at ${width}px`);
  assert(expanded.images.every(({image, wrapper, objectFit, src, currentSrc, naturalWidth, naturalHeight}) => objectFit === "contain" && inside(image, wrapper) && src && currentSrc && naturalWidth > 0 && naturalHeight > 0), `Minifigure images are cropped or unloaded at ${width}px: ${JSON.stringify(expanded.images)}`);
  await evaluate(client, `(() => { const set = document.querySelector("[data-set-group]"); set.open = false; set.open = true; set.querySelector(".minifigure-parts").open = false; })()`);
}

async function auditMinifigureQuantity(client) {
  await navigate(client, routes.authenticated.minifigures);
  const setup = await evaluate(client, `(() => {
    const parts = document.querySelectorAll("[data-minifigure]")[1].querySelector(".minifigure-parts");
    parts.open = true;
    const button = parts.querySelector("[data-minifigure-part] .minifigure-part-shortcuts button");
    const form = button.closest("form");
    return {path: location.pathname, formAction: form.action, handler: form.dataset.inlineInventory, figures: document.querySelectorAll("[data-minifigure]").length};
  })()`);
  assert(setup.handler === "true", `Minifigure inline inventory handler is absent: ${JSON.stringify(setup)}`);
  await evaluate(client, `document.querySelectorAll("[data-minifigure]")[1].querySelector("[data-minifigure-part] .minifigure-part-shortcuts button").click()`);
  let state;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await delay(100);
    state = await evaluate(client, `(() => {
      const figure = document.querySelectorAll("[data-minifigure]")[1];
      if (!figure) return {path: location.pathname, figures: document.querySelectorAll("[data-minifigure]").length};
      const part = figure.querySelector("[data-minifigure-part]");
      if (!part || !part.querySelector("[data-part-owned]")) return {path: location.pathname, figure: figure.outerHTML.slice(0, 250), part: part?.outerHTML.slice(0, 250)};
      return {
        partOwned: part.querySelector("[data-part-owned]").textContent.trim(),
        partStatus: part.querySelector("[data-part-status]")?.textContent.trim(),
        figureOwned: figure.querySelector("[data-figure-owned]")?.textContent.trim(),
        figureStatus: figure.querySelector("[data-figure-status]")?.textContent.trim(),
        progress: figure.querySelector("progress")?.value,
        completeKpi: document.querySelector('[data-minifigure-kpi="complete"]')?.textContent.trim(),
        partialKpi: document.querySelector('[data-minifigure-kpi="partial"]')?.textContent.trim(),
        path: location.pathname,
      };
    })()`);
    if (state.figureStatus === "Vollständig") break;
  }
  assert(state.partOwned === "2" && state.partStatus === "Komplett" && state.figureOwned === "2" && state.figureStatus === "Vollständig" && state.progress === 100, `Minifigure quantity update did not refresh its cards: ${JSON.stringify(state)}`);
  assert(state.completeKpi === "2" && state.partialKpi === "0", `Minifigure KPI values did not refresh after quantity update: ${JSON.stringify(state)}`);
}

async function auditMissingPartsHotfixControls(client, width) {
  const result = await evaluate(client, `(() => {
    const rect = (node) => {
      const value = node?.getBoundingClientRect();
      return value && {left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height};
    };
    const within = (child, parent, tolerance = 1) => Boolean(child && parent)
      && child.left >= parent.left - tolerance && child.right <= parent.right + tolerance
      && child.top >= parent.top - tolerance && child.bottom <= parent.bottom + tolerance;
    const textRect = (node) => {
      const range = document.createRange();
      range.selectNodeContents(node);
      const value = range.getBoundingClientRect();
      return {left: value.left, right: value.right, top: value.top, bottom: value.bottom, width: value.width, height: value.height};
    };
    const overlaps = (first, second) => first.left < second.right && first.right > second.left
      && first.top < second.bottom && first.bottom > second.top;

    const colorDetails = document.querySelector("[data-color-filter]");
    colorDetails.open = true;
    const colorPopover = colorDetails.querySelector(".color-filter-popover");
    const popoverRect = rect(colorPopover);
    const colorRows = [...colorDetails.querySelectorAll(".color-options label")].map((row) => {
      const checkbox = row.querySelector('input[type="checkbox"]');
      const name = row.querySelector("span");
      return {
        group: row.closest("fieldset")?.querySelector("legend")?.textContent.trim() || "",
        label: name.textContent.trim(),
        row: rect(row),
        checkbox: rect(checkbox),
        name: rect(name),
        rowDisplay: getComputedStyle(row).display,
        columns: getComputedStyle(row).gridTemplateColumns,
        alignItems: getComputedStyle(row).alignItems,
        nameFits: within(rect(name), popoverRect),
      };
    });
    const colorActions = [...colorDetails.querySelectorAll(".color-filter-actions button")].map((button) => ({
      text: button.textContent.trim(), rect: rect(button), visible: Boolean(button.offsetWidth && button.offsetHeight),
    }));
    colorDetails.open = false;
    const allocationControls = [...document.querySelectorAll(".allocation-controls")].map((controls) => {
      const forms = [...controls.querySelectorAll(":scope > .allocation-form")];
      const formRects = forms.map(rect);
      return {
        columns: getComputedStyle(controls).gridTemplateColumns,
        hasQuantity: Boolean(controls.querySelector(".quantity-form")),
        hasStatus: Boolean(controls.querySelector(".status-form")),
        groupsOverlap: formRects.some((first, index) => formRects.slice(index + 1).some((second) => overlaps(first, second))),
        labelsLinked: forms.every((form) => {
          const label = form.querySelector("label");
          const control = form.querySelector("input:not([type=hidden]), select");
          return Boolean(label && control && label.htmlFor === control.id);
        }),
        buttons: [...controls.querySelectorAll("button")].map((button) => ({
          text: button.textContent.trim(),
          rect: rect(button),
          textRect: textRect(button),
          textFits: within(textRect(button), rect(button)),
          contentFits: button.scrollWidth <= button.clientWidth + 1,
          whiteSpace: getComputedStyle(button).whiteSpace,
        })),
      };
    });
    return {popover: popoverRect, colorRows, colorActions, allocationControls};
  })()`);

  if (process.env.BRICKMISSING_AUDIT_TRACE === "1") {
    process.stdout.write(`Missing-parts hotfix metrics ${width}px: ${JSON.stringify(result)}\n`);
  }
  assert(result.colorRows.length >= 4, "Color filter test fixtures are incomplete");
  const checkboxSizes = new Set(result.colorRows.map(({checkbox}) => `${checkbox.width}x${checkbox.height}`));
  assert(checkboxSizes.size === 1, `Color swatches differ in size at ${width}px: ${JSON.stringify(result.colorRows)}`);
  for (const group of new Set(result.colorRows.map(({group}) => group))) {
    const rows = result.colorRows.filter((row) => row.group === group);
    assert(new Set(rows.map(({checkbox}) => checkbox.left)).size === 1, `${group} swatches are not aligned at ${width}px`);
    assert(new Set(rows.map(({name}) => name.left)).size === 1, `${group} color names are not aligned at ${width}px`);
  }
  assert(result.colorRows.every(({rowDisplay, alignItems, nameFits}) => rowDisplay === "grid" && alignItems === "center" && nameFits), `Color rows are unstable at ${width}px: ${JSON.stringify(result.colorRows)}`);
  assert(result.colorRows.some(({label}) => label === "Glow in Dark White") && result.colorRows.some(({label}) => label === "Dark Bluish Gray"), "Long color-name fixtures are missing");
  assert(result.colorActions.map(({text}) => text).includes("Alle Farben anzeigen") && result.colorActions.map(({text}) => text).includes("Übernehmen") && result.colorActions.every(({visible}) => visible), `Color-filter actions are unavailable at ${width}px`);

  assert(result.allocationControls.some(({hasQuantity, hasStatus}) => hasQuantity && hasStatus), "Normal part controls are missing");
  assert(result.allocationControls.some(({hasQuantity, hasStatus}) => hasQuantity && !hasStatus), "Minifigure quantity-only controls are missing");
  for (const controls of result.allocationControls) {
    assert(!controls.groupsOverlap && controls.labelsLinked, `Allocation control groups overlap or lose labels at ${width}px: ${JSON.stringify(controls)}`);
    assert(controls.buttons.every(({textFits, contentFits}) => textFits && contentFits), `Allocation button text overflows at ${width}px: ${JSON.stringify(controls.buttons)}`);
  }
}

async function auditSetFilters(client) {
  const result = await evaluate(client, `(() => {
    const disclosure = document.querySelector("[data-responsive-disclosure]");
    if (disclosure && !disclosure.open) disclosure.querySelector("summary").click();
    const selectors = ["input[name=q]", "input[name=theme]", "select[name=sort]"];
    const controls = selectors.map((selector) => {
      const node = document.querySelector(selector);
      const rect = node?.getBoundingClientRect();
      return {selector, exists: Boolean(node), height: rect?.height || 0, width: rect?.width || 0};
    });
    const panel = document.querySelector(".set-filters")?.getBoundingClientRect();
    const cards = document.querySelector(".cards")?.getBoundingClientRect();
    return {controls, panel: panel && {left: panel.left, right: panel.right, height: panel.height}, cardsTop: cards?.top};
  })()`);
  for (const control of result.controls) {
    assert(control.exists, `Set filter is missing: ${control.selector}`);
    assert(control.height >= 40 && control.height <= 64, `${control.selector} has an unreasonable ${control.height}px height`);
    assert(control.width > 0 && control.width <= 390, `${control.selector} has an unreasonable width`);
  }
  assert(result.panel.left >= -1 && result.panel.right <= 391, "Set filter panel escapes the 390px viewport");
  assert(result.panel.height < 380, `Set filter panel is excessively tall: ${result.panel.height}px`);
  assert(result.cardsTop < 1100, "Set content is pushed unreasonably far below the filters");
}

async function auditTabletSetFilters(client, width) {
  const result = await evaluate(client, `(() => {
    const panelNode = document.querySelector(".set-filters");
    const panel = panelNode?.getBoundingClientRect();
    const nodes = [
      ["search", panelNode?.querySelector("input[name=q]")],
      ["theme", panelNode?.querySelector("input[name=theme]")],
      ["sort", panelNode?.querySelector("select[name=sort]")],
      ["button", panelNode?.querySelector("button[type=submit], button:not([type])")]
    ];
    const controls = nodes.map(([name, node]) => {
      const rect = node?.getBoundingClientRect();
      return {
        name,
        exists: Boolean(node),
        left: rect?.left || 0,
        right: rect?.right || 0,
        top: rect?.top || 0,
        bottom: rect?.bottom || 0,
        width: rect?.width || 0,
        height: rect?.height || 0,
        disabled: Boolean(node?.disabled),
        pointerEvents: node ? getComputedStyle(node).pointerEvents : "none",
        topmost: node && rect
          ? node.contains(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2))
            || document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2) === node
          : false
      };
    });
    return {
      panel: panel && {left: panel.left, right: panel.right, top: panel.top, bottom: panel.bottom, width: panel.width},
      controls,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth
    };
  })()`);
  assert(result.panel, "Set filter panel is missing at the tablet viewport");
  assert(result.panel.width > 0, "Set filter panel has no width at the tablet viewport");
  for (const control of result.controls) {
    assert(control.exists, `${control.name} control is missing at ${width}px`);
    assert(control.width > 0 && control.height > 0, `${control.name} control has no rendered size at ${width}px`);
    assert(control.left >= result.panel.left - 1, `${control.name} crosses the filter panel's left edge at ${width}px`);
    assert(control.right <= result.panel.right + 1, `${control.name} crosses the filter panel's right edge at ${width}px`);
    assert(control.top >= result.panel.top - 1 && control.bottom <= result.panel.bottom + 1, `${control.name} crosses the filter panel vertically at ${width}px`);
  }
  for (let index = 0; index < result.controls.length; index += 1) {
    for (let otherIndex = index + 1; otherIndex < result.controls.length; otherIndex += 1) {
      const first = result.controls[index];
      const second = result.controls[otherIndex];
      const overlaps = first.left < second.right && first.right > second.left
        && first.top < second.bottom && first.bottom > second.top;
      assert(!overlaps, `${first.name} overlaps ${second.name} at ${width}px`);
    }
  }
  const button = result.controls.find((control) => control.name === "button");
  assert(!button.disabled && button.pointerEvents !== "none" && button.topmost, `Search button is not fully clickable at ${width}px`);
  assert(result.documentWidth <= width + 1, `Set overview document overflows at ${width}px`);
  assert(result.bodyWidth <= width + 1, `Set overview body overflows at ${width}px`);
}

async function auditSetFilterAlignment(client, width, comparisonLabel) {
  const result = await evaluate(client, `(() => {
    const panel = document.querySelector(".set-filters");
    const colorDetails = panel?.querySelector(".color-filter");
    const snapshot = () => {
      const fields = [...panel.querySelectorAll(":scope > .filter-field")].map((field) => {
        const label = field.querySelector(":scope > .filter-label");
        const control = field.querySelector(":scope > input, :scope > select, :scope > .color-filter > summary");
        const labelRect = label?.getBoundingClientRect();
        const controlRect = control?.getBoundingClientRect();
        const fieldRect = field.getBoundingClientRect();
        return {
          label: label?.textContent.trim(),
          labelTop: labelRect?.top || 0,
          controlTop: controlRect?.top || 0,
          controlHeight: controlRect?.height || 0,
          fieldTop: fieldRect.top,
          fieldHeight: fieldRect.height,
        };
      });
      const detailsRect = colorDetails.getBoundingClientRect();
      const summaryRect = colorDetails.querySelector(":scope > summary").getBoundingClientRect();
      const popover = colorDetails.querySelector(":scope > .color-filter-popover");
      return {
        fields,
        detailsTop: detailsRect.top,
        detailsHeight: detailsRect.height,
        summaryTop: summaryRect.top,
        summaryHeight: summaryRect.height,
        popoverPosition: getComputedStyle(popover).position,
        popoverHeight: popover.getBoundingClientRect().height,
      };
    };
    colorDetails.open = false;
    const closed = snapshot();
    colorDetails.open = true;
    const opened = snapshot();
    colorDetails.open = false;
    const reclosed = snapshot();
    return {closed, opened, reclosed};
  })()`);
  const color = result.closed.fields.find((field) => field.label === "Fehlende Farben");
  const comparison = result.closed.fields.find((field) => field.label === comparisonLabel);
  assert(color, `Missing-color field is absent at ${width}px`);
  assert(result.closed.popoverPosition === "absolute", `Color popover participates in layout at ${width}px`);
  assert(Math.abs(result.closed.detailsHeight - result.closed.summaryHeight) <= 1, `Closed color details and summary heights differ at ${width}px: ${JSON.stringify(result.closed)}`);
  assert(Math.abs(result.opened.detailsHeight - result.opened.summaryHeight) <= 1, `Open color popover changes details height at ${width}px: ${JSON.stringify(result.opened)}`);
  assert(Math.abs(result.closed.detailsHeight - result.opened.detailsHeight) <= 1, `Closed/open color control heights differ at ${width}px: ${JSON.stringify(result)}`);
  assert(Math.abs(result.closed.summaryTop - result.opened.summaryTop) <= 1, `Opening moves the color control at ${width}px: ${JSON.stringify(result)}`);
  assert(Math.abs(result.closed.summaryTop - result.reclosed.summaryTop) <= 1, `Reclosing moves the color control at ${width}px: ${JSON.stringify(result)}`);
  if (comparisonLabel) {
    assert(comparison, `${comparisonLabel} field is absent at ${width}px`);
    assert(Math.abs(color.labelTop - comparison.labelTop) <= 1, `Closed color/${comparisonLabel} labels are misaligned at ${width}px: ${JSON.stringify(result.closed.fields)}`);
    assert(Math.abs(color.controlTop - comparison.controlTop) <= 1, `Closed color/${comparisonLabel} controls are misaligned at ${width}px: ${JSON.stringify(result.closed.fields)}`);
    assert(Math.abs(color.controlHeight - comparison.controlHeight) <= 1, `Closed color/${comparisonLabel} control heights differ at ${width}px: ${JSON.stringify(result.closed.fields)}`);
  }
}

async function auditDashboard(client, width) {
  const result = await evaluate(client, `(() => {
    const banner = document.querySelector(".dashboard-banner");
    const bannerImage = banner?.querySelector(".dashboard-banner-image");
    const bannerRect = banner?.getBoundingClientRect();
    const bannerImageRect = bannerImage?.getBoundingClientRect();
    const recentCards = [...document.querySelectorAll(".dashboard-set-card")];
    const recentCardRects = recentCards.map((node) => {
      const rect = node.getBoundingClientRect();
      return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom};
    });
    const shortcutLabels = [...document.querySelectorAll(".dashboard-shortcuts nav a > span:nth-child(2)")].map((node) => node.textContent.trim());
    const recentImages = [...document.querySelectorAll(".dashboard-set-media img")].map((image) => {
      const container = image.parentElement;
      const imageRect = image.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      const imageStyle = getComputedStyle(image);
      const containerStyle = getComputedStyle(container);
      const borderLeft = Number.parseFloat(containerStyle.borderLeftWidth);
      const borderTop = Number.parseFloat(containerStyle.borderTopWidth);
      const borderRight = Number.parseFloat(containerStyle.borderRightWidth);
      const borderBottom = Number.parseFloat(containerStyle.borderBottomWidth);
      const paddingLeft = Number.parseFloat(containerStyle.paddingLeft);
      const paddingTop = Number.parseFloat(containerStyle.paddingTop);
      const paddingRight = Number.parseFloat(containerStyle.paddingRight);
      const paddingBottom = Number.parseFloat(containerStyle.paddingBottom);
      const inner = {
        left: containerRect.left + borderLeft + paddingLeft,
        top: containerRect.top + borderTop + paddingTop,
        right: containerRect.right - borderRight - paddingRight,
        bottom: containerRect.bottom - borderBottom - paddingBottom,
      };
      inner.width = inner.right - inner.left;
      inner.height = inner.bottom - inner.top;
      const scale = Math.min(inner.width / image.naturalWidth, inner.height / image.naturalHeight);
      return {
        srcAttribute: image.getAttribute("src"),
        src: image.src,
        currentSrc: image.currentSrc,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
        widthAttribute: image.getAttribute("width"),
        heightAttribute: image.getAttribute("height"),
        imageRect: {left: imageRect.left, top: imageRect.top, right: imageRect.right, bottom: imageRect.bottom, width: imageRect.width, height: imageRect.height},
        containerRect: {left: containerRect.left, top: containerRect.top, right: containerRect.right, bottom: containerRect.bottom, width: containerRect.width, height: containerRect.height},
        inner,
        expectedWidth: image.naturalWidth * scale,
        expectedHeight: image.naturalHeight * scale,
        imageStyle: {
          display: imageStyle.display,
          position: imageStyle.position,
          overflow: imageStyle.overflow,
          objectFit: imageStyle.objectFit,
          objectPosition: imageStyle.objectPosition,
          width: imageStyle.width,
          height: imageStyle.height,
          minWidth: imageStyle.minWidth,
          minHeight: imageStyle.minHeight,
          maxWidth: imageStyle.maxWidth,
          maxHeight: imageStyle.maxHeight,
          aspectRatio: imageStyle.aspectRatio,
          padding: imageStyle.padding,
          margin: imageStyle.margin,
        },
        containerStyle: {
          display: containerStyle.display,
          position: containerStyle.position,
          overflow: containerStyle.overflow,
          width: containerStyle.width,
          height: containerStyle.height,
          minWidth: containerStyle.minWidth,
          minHeight: containerStyle.minHeight,
          maxWidth: containerStyle.maxWidth,
          maxHeight: containerStyle.maxHeight,
          aspectRatio: containerStyle.aspectRatio,
          padding: containerStyle.padding,
          margin: containerStyle.margin,
        },
      };
    });
    return ({
    title: Boolean(document.querySelector("h1")),
    duplicateSearch: Boolean(document.querySelector("#collection-search")),
    bannerVisible: bannerRect?.height > 0,
    bannerImageLoaded: Boolean(bannerImage?.complete && bannerImage.naturalWidth > 0 && bannerImage.naturalHeight > 0),
    bannerImageFit: getComputedStyle(bannerImage).objectFit === "cover",
    bannerImageFillsContainer: !bannerRect?.height || (Math.abs(bannerRect.width - bannerImageRect.width) <= 1 && Math.abs(bannerRect.height - bannerImageRect.height) <= 1),
    actionCount: document.querySelectorAll(".dashboard-actions .dashboard-action").length,
    shortcutCount: document.querySelectorAll(".dashboard-shortcuts nav a").length,
    shortcutLabels,
    partsShortcutPath: [...document.querySelectorAll(".dashboard-shortcuts nav a")].find((node) => node.textContent.includes("Teile"))?.pathname,
    recentCardCount: recentCards.length,
    recentCardRects,
    recentColumns: new Set(recentCardRects.map(({left}) => Math.round(left))).size,
    recentImages,
    stats: [...document.querySelectorAll(".dashboard-stats article")].map((node) => ({left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right})),
    valuesFit: [...document.querySelectorAll(".dashboard-stats strong")].every((node) => node.scrollWidth <= node.clientWidth + 1),
    donutReadable: document.querySelector(".dashboard-donut")?.getBoundingClientRect().width >= 150,
    topPartsFit: [...document.querySelectorAll(".dashboard-top-missing li")].every((node) => node.scrollWidth <= node.clientWidth + 1),
    cardsFit: [...document.querySelectorAll(".dashboard [class$='-card'], .dashboard .panel")].every((node) => node.getBoundingClientRect().right <= document.documentElement.clientWidth + 1),
    });
  })()`);
  assert(result.title, "Dashboard title is not visible");
  assert(!result.duplicateSearch, "Dashboard still contains a duplicate collection search");
  assert(result.bannerVisible === (width > 480), `Dashboard banner visibility is incorrect at ${width}px`);
  assert(result.bannerImageLoaded, `Dashboard banner image did not load at ${width}px`);
  assert(result.bannerImageFit, `Dashboard banner image is not using object-fit cover at ${width}px`);
  assert(result.bannerImageFillsContainer, `Dashboard banner image does not fill its container at ${width}px`);
  assert(result.actionCount === 4, "Dashboard quick actions are incomplete");
  assert(result.shortcutCount === 6, "Dashboard shortcuts are incomplete");
  assert(result.shortcutLabels.includes("Teile") && !result.shortcutLabels.includes("Farben"), "Dashboard parts shortcut is mislabeled");
  assert(result.partsShortcutPath === routes.authenticated.parts, "Dashboard parts shortcut route changed");
  assert(result.recentCardCount === 3, `Dashboard shows ${result.recentCardCount} recent sets instead of three`);
  assert(result.recentColumns === (width <= 480 ? 1 : 3), `Dashboard recent-set columns are incorrect at ${width}px`);
  for (const image of result.recentImages) {
    const tolerance = 1;
    assert(image.currentSrc === image.src && image.currentSrc.length > 0, `Dashboard image source resolution is inconsistent at ${width}px`);
    assert(image.naturalWidth > 0 && image.naturalHeight > 0, `Dashboard image has no intrinsic dimensions at ${width}px`);
    assert(image.widthAttribute === null && image.heightAttribute === null, `Dashboard image has unexpected HTML dimensions at ${width}px`);
    assert(image.imageStyle.objectFit === "contain" && image.imageStyle.objectPosition === "50% 50%", `Dashboard image contain styles are inactive at ${width}px`);
    assert(image.imageStyle.width !== "auto" && image.imageStyle.height !== "auto", `Dashboard image did not resolve to rendered dimensions at ${width}px`);
    assert(image.imageRect.left >= image.inner.left - tolerance && image.imageRect.right <= image.inner.right + tolerance, `Dashboard image crosses its horizontal content box at ${width}px: ${JSON.stringify(image)}`);
    assert(image.imageRect.top >= image.inner.top - tolerance && image.imageRect.bottom <= image.inner.bottom + tolerance, `Dashboard image crosses its vertical content box at ${width}px: ${JSON.stringify(image)}`);
    assert(image.imageRect.width <= image.inner.width + tolerance && image.imageRect.height <= image.inner.height + tolerance, `Dashboard image is larger than its visible container at ${width}px`);
    assert(Math.abs(image.imageRect.width - image.expectedWidth) <= tolerance && Math.abs(image.imageRect.height - image.expectedHeight) <= tolerance, `Dashboard image does not match mathematically expected contain geometry at ${width}px: ${JSON.stringify(image)}`);
    assert(Math.abs(image.imageRect.width / image.imageRect.height - image.naturalWidth / image.naturalHeight) <= .02, `Dashboard image aspect ratio is distorted at ${width}px`);
  }
  for (let index = 0; index < result.recentCardRects.length; index += 1) {
    for (let otherIndex = index + 1; otherIndex < result.recentCardRects.length; otherIndex += 1) {
      const first = result.recentCardRects[index];
      const second = result.recentCardRects[otherIndex];
      const overlaps = first.left < second.right && first.right > second.left
        && first.top < second.bottom && first.bottom > second.top;
      assert(!overlaps, `Dashboard recent-set cards overlap at ${width}px`);
    }
  }
  assert(result.stats.every(({left, right}) => left >= -1 && right <= width + 1), `Dashboard statistic card escapes at ${width}px`);
  assert(result.valuesFit, "Dashboard statistic value overflows its card");
  assert(result.donutReadable, `Dashboard donut is too small at ${width}px`);
  assert(result.topPartsFit, `Dashboard top-parts list overflows at ${width}px`);
  assert(result.cardsFit, `Dashboard card escapes at ${width}px`);
}

async function auditDashboardDonut(client) {
  const result = await evaluate(client, `(async () => {
    const root = document.querySelector(".dashboard-donut");
    const owned = root?.querySelector(".dashboard-donut-owned");
    const missing = root?.querySelector(".dashboard-donut-missing");
    const track = root?.querySelector(".dashboard-donut-track");
    const missingLegend = document.querySelector(".dashboard-donut-legend .missing");
    const numbers = (value) => String(value || "").split(/[ ,]+/).map(Number.parseFloat).filter(Number.isFinite);
    const read = () => ({
      ownedDashAttribute: owned.getAttribute("stroke-dasharray"),
      missingDash: numbers(missing.getAttribute("stroke-dasharray")),
      missingOffset: Number.parseFloat(missing.getAttribute("stroke-dashoffset")),
      pathLength: Number.parseFloat(owned.getAttribute("pathLength")),
      ownedComputedDash: getComputedStyle(owned).strokeDasharray,
      missingComputedDash: numbers(getComputedStyle(missing).strokeDasharray),
      missingComputedOffset: Number.parseFloat(getComputedStyle(missing).strokeDashoffset),
      ownedStroke: getComputedStyle(owned).stroke,
      missingStroke: getComputedStyle(missing).stroke,
    });
    const initial = read();
    const scenarios = [
      [100, 0],
      [0, 100],
      [50, 50],
      [99.9, .1],
      [0, 0],
    ].map(([ownedValue, missingValue]) => {
      root.classList.toggle("is-empty", ownedValue + missingValue === 0);
      missing.setAttribute("stroke-dasharray", String(missingValue) + " " + String(ownedValue));
      missing.setAttribute("stroke-dashoffset", String(ownedValue ? -ownedValue : 0));
      return {ownedValue, missingValue, ...read()};
    });
    root.classList.remove("is-empty");
    missing.setAttribute("stroke-dasharray", "2.3 97.7");
    missing.setAttribute("stroke-dashoffset", "-97.7");
    const svg = root.querySelector("svg");
    const clone = svg.cloneNode(true);
    clone.setAttribute("width", "420");
    clone.setAttribute("height", "420");
    clone.style.transform = "none";
    for (const selector of [".dashboard-donut-track", ".dashboard-donut-owned", ".dashboard-donut-missing"]) {
      const source = svg.querySelector(selector);
      const target = clone.querySelector(selector);
      const style = getComputedStyle(source);
      target.setAttribute("stroke", style.stroke);
      target.setAttribute("stroke-width", style.strokeWidth);
      target.setAttribute("stroke-linecap", style.strokeLinecap);
      target.setAttribute("fill", "none");
      target.setAttribute("transform", "rotate(-90 21 21)");
    }
    const raster = document.createElement("canvas");
    raster.width = 420;
    raster.height = 420;
    const rasterContext = raster.getContext("2d", {willReadFrequently: true});
    const rasterImage = new Image();
    rasterImage.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
    await rasterImage.decode();
    rasterContext.drawImage(rasterImage, 0, 0, 420, 420);
    const colorPixel = document.createElement("canvas");
    colorPixel.width = 1;
    colorPixel.height = 1;
    const colorContext = colorPixel.getContext("2d", {willReadFrequently: true});
    const rgb = (color) => {
      colorContext.clearRect(0, 0, 1, 1);
      colorContext.fillStyle = color;
      colorContext.fillRect(0, 0, 1, 1);
      return [...colorContext.getImageData(0, 0, 1, 1).data.slice(0, 3)];
    };
    const pixelAtPathPosition = (position) => {
      const angle = (-90 + position * 3.6) * Math.PI / 180;
      const x = Math.round(210 + 159.155 * Math.cos(angle));
      const y = Math.round(210 + 159.155 * Math.sin(angle));
      return {position, pixel: [...rasterContext.getImageData(x, y, 1, 1).data.slice(0, 3)]};
    };
    return {
      exists: Boolean(root && owned && missing && track),
      initial,
      scenarios,
      ownedLinecap: getComputedStyle(owned).strokeLinecap,
      missingLinecap: getComputedStyle(missing).strokeLinecap,
      segmentsUseDifferentColors: getComputedStyle(owned).stroke !== getComputedStyle(missing).stroke,
      missingMatchesLegend: getComputedStyle(missing).stroke === getComputedStyle(missingLegend).borderLeftColor,
      ariaLabel: root?.getAttribute("aria-label") || "",
      seamSamples: [97.65, 97.7, 97.75, 99.95, 0, .05].map(pixelAtPathPosition),
      trackColor: rgb(getComputedStyle(track).stroke),
      ownedColor: rgb(getComputedStyle(owned).stroke),
      missingColor: rgb(getComputedStyle(missing).stroke),
    };
  })()`);
  const tolerance = .05;
  const close = (actual, expected) => Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance;
  assert(result.exists, "Dashboard donut segments are incomplete");
  assert(close(result.initial.pathLength, 100), "Dashboard donut pathLength is not normalized to 100");
  assert(result.initial.ownedDashAttribute === null && result.initial.ownedComputedDash === "none", "Dashboard owned underlay is not a complete circle");
  assert(close(result.initial.missingDash[0], 2.3) && close(result.initial.missingDash[1], 97.7), "Dashboard donut does not render complementary 97.7/2.3 test data");
  assert(close(result.initial.missingOffset, -97.7), "Dashboard missing segment does not start after the owned segment");
  assert(result.initial.missingDash[0] > 0, "Dashboard missing segment has no positive length");
  assert(close(result.initial.missingComputedDash[0], 2.3) && close(result.initial.missingComputedDash[1], 97.7), "Computed donut dash lengths differ from SVG values");
  assert(close(result.initial.missingComputedOffset, -97.7), "Computed missing offset differs from the SVG value");
  for (const scenario of result.scenarios) {
    assert(scenario.ownedDashAttribute === null, `Owned donut underlay is not complete for ${scenario.ownedValue}/${scenario.missingValue}`);
    assert(close(scenario.missingDash[0], scenario.missingValue) && close(scenario.missingDash[1], scenario.ownedValue), `Missing donut pattern is incorrect for ${scenario.ownedValue}/${scenario.missingValue}`);
    assert(close(scenario.missingOffset, scenario.ownedValue ? -scenario.ownedValue : 0), `Missing donut offset is incorrect for ${scenario.ownedValue}/${scenario.missingValue}`);
    assert(close(scenario.missingComputedDash[0], scenario.missingValue) && close(scenario.missingComputedDash[1], scenario.ownedValue), `Computed missing pattern is incorrect for ${scenario.ownedValue}/${scenario.missingValue}`);
    if (scenario.ownedValue + scenario.missingValue === 0) {
      assert(scenario.ownedStroke === "none" && scenario.missingStroke === "none", "Zero-state donut still paints data segments");
    } else {
      assert(close(scenario.ownedValue + scenario.missingValue, 100), `Donut percentages do not close at 100 for ${scenario.ownedValue}/${scenario.missingValue}`);
      const missingStart = scenario.ownedValue;
      const ownedEnd = scenario.ownedValue;
      const missingEnd = missingStart + scenario.missingValue;
      assert(close(ownedEnd, missingStart), `Owned end and missing start diverge for ${scenario.ownedValue}/${scenario.missingValue}`);
      assert(close(missingEnd, 100), `Missing segment does not close the circle for ${scenario.ownedValue}/${scenario.missingValue}`);
    }
  }
  assert(result.ownedLinecap === "butt" && result.missingLinecap === "butt", "Rounded line caps distort small donut segments");
  assert(result.segmentsUseDifferentColors && result.missingMatchesLegend, "Donut segment colors do not match the legend");
  const colorDifference = (first, second) => first.reduce((sum, value, index) => sum + (value - second[index]) ** 2, 0);
  for (const sample of result.seamSamples) {
    const nearestDataColor = Math.min(
      colorDifference(sample.pixel, result.ownedColor),
      colorDifference(sample.pixel, result.missingColor),
    );
    assert(nearestDataColor < colorDifference(sample.pixel, result.trackColor), `Dark track leaks through the donut seam at ${sample.position}: ${JSON.stringify(result)}`);
  }
  assert(result.ariaLabel.includes("977 Teile vorhanden") && result.ariaLabel.includes("23 Teile fehlend"), "Donut text alternative is incomplete");
}

async function auditNavigation(client) {
  const result = await evaluate(client, `(() => {
    const trigger = document.querySelector(".nav-toggle");
    const before = getComputedStyle(trigger).display !== "none" && trigger.getAttribute("aria-expanded") === "false";
    trigger.click();
    const menu = document.querySelector("#main-navigation");
    const opened = trigger.getAttribute("aria-expanded") === "true" && menu.classList.contains("is-open");
    const accountLink = [...menu.querySelectorAll("a")].some((node) => node.textContent.includes("Konto"));
    document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
    return {before, opened, accountLink, closed: trigger.getAttribute("aria-expanded") === "false"};
  })()`);
  assert(result.before && result.opened && result.closed, "Mobile navigation open/Escape state is incorrect");
  assert(result.accountLink, "Mobile navigation does not expose account actions");
}

async function auditFormControls(client) {
  const result = await evaluate(client, `(() => ({
    inputs: [...document.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio])")].map((node) => node.getBoundingClientRect().height).filter(Boolean),
    selects: [...document.querySelectorAll("select")].map((node) => node.getBoundingClientRect().height).filter(Boolean),
    buttons: [...document.querySelectorAll("button, .button")].map((node) => node.getBoundingClientRect().height).filter(Boolean),
    textareas: [...document.querySelectorAll("textarea")].map((node) => node.getBoundingClientRect().height).filter(Boolean)
  }))()`);
  for (const height of [...result.inputs, ...result.selects, ...result.buttons]) {
    assert(height >= 36 && height <= 72, `Ordinary form control has an unreasonable ${height}px height`);
  }
  for (const height of result.textareas) assert(height >= 96 && height <= 420, `Textarea has an unreasonable ${height}px height`);
}

let client;
let targetId;
try {
  const debuggerInfo = await waitForDebugger();
  client = new CdpClient(debuggerInfo.webSocketDebuggerUrl);
  const target = await client.send("Target.createTarget", {url: "about:blank"}, null);
  targetId = target.targetId;
  const attached = await client.send("Target.attachToTarget", {targetId: target.targetId}, null);
  client.sessionId = attached.sessionId;
  await delay(500);
  await setViewport(client, 390, 844);
  await navigate(client, routes.login);
  await evaluate(client, `(() => {
    const form = document.querySelector("form[method=post]");
    form.elements.username.value = ${JSON.stringify(username)};
    form.elements.password.value = ${JSON.stringify(password)};
    form.submit();
  })()`);
  await waitForReady(client);
  const loginPath = await evaluate(client, "location.pathname");
  assert(loginPath !== routes.login, "Browser audit login failed");

  const mobileWidths = [320, 375, 390, 430];
  const desktopWidths = [768, 1024, 1280, 1440, 1920];
  for (const width of mobileWidths) {
    await setViewport(client, width, 844);
    for (const [name, path] of Object.entries(routes.authenticated)) {
      await navigate(client, path);
      await auditOverflow(client, name, width);
      if (name === "dashboard") await auditDashboard(client, width);
      if (name === "missingParts") {
        await auditMissingParts(client, width);
        await auditMissingPartsHotfixControls(client, width);
      }
      if (name === "minifigures") await auditMinifigures(client, width);
    }
  }
  for (const width of desktopWidths) {
    await setViewport(client, width, width >= 1440 ? 900 : 1024);
    for (const name of ["dashboard", "sets", "setForm", "setDetail", "missingParts", "minifigures"]) {
      await navigate(client, routes.authenticated[name]);
      await auditOverflow(client, name, width);
      if (name === "dashboard") await auditDashboard(client, width);
      if (name === "missingParts") {
        await auditMissingParts(client, width);
        await auditMissingPartsHotfixControls(client, width);
      }
      if (name === "minifigures") await auditMinifigures(client, width);
    }
  }

  await setViewport(client, 768, 1024);
  await navigate(client, routes.authenticated.sets);
  await auditTabletSetFilters(client, 768);
  await auditSetFilterAlignment(client, 768, "Vollständigkeit");

  await setViewport(client, 1440, 900);
  await navigate(client, routes.authenticated.sets);
  await auditSetFilterAlignment(client, 1440, "Sortierung");

  await setViewport(client, 390, 844);
  await navigate(client, routes.authenticated.sets);
  await auditSetFilters(client);
  await auditSetFilterAlignment(client, 390, "Sortierung");
  await setViewport(client, 320, 844);
  await navigate(client, routes.authenticated.sets);
  await auditSetFilterAlignment(client, 320, "");
  await auditNavigation(client);
  await navigate(client, routes.authenticated.dashboard);
  await auditDashboard(client, 390);
  await auditDashboardDonut(client);
  await navigate(client, routes.authenticated.setForm);
  await auditFormControls(client);

  if (artifactDirectory) {
    await mkdir(artifactDirectory, {recursive: true});
    const screenshots = [
      [390, 844],
      [768, 1024],
      [1440, 900],
    ];
    for (const [width, height] of screenshots) {
      await setViewport(client, width, height);
      for (const name of ["dashboard", "sets", "setForm", "missingParts", "minifigures"]) {
        await navigate(client, routes.authenticated[name]);
        const capture = await client.send("Page.captureScreenshot", {format: "png", fromSurface: true, captureBeyondViewport: ["dashboard", "missingParts", "minifigures"].includes(name)});
        await writeFile(join(artifactDirectory, `${name}-${width}x${height}.png`), Buffer.from(capture.data, "base64"));
        if (name === "missingParts") {
          await evaluate(client, `(() => {
            document.querySelector("[data-color-filter]").open = true;
          })()`);
          const controlsCapture = await client.send("Page.captureScreenshot", {format: "png", fromSurface: true, captureBeyondViewport: true});
          await writeFile(join(artifactDirectory, `${name}-controls-${width}x${height}.png`), Buffer.from(controlsCapture.data, "base64"));
        }
        if (name === "minifigures") {
          await evaluate(client, `document.querySelector("[data-minifigure] .minifigure-parts").open = true`);
          const expandedCapture = await client.send("Page.captureScreenshot", {format: "png", fromSurface: true, captureBeyondViewport: true});
          await writeFile(join(artifactDirectory, `${name}-expanded-${width}x${height}.png`), Buffer.from(expandedCapture.data, "base64"));
        }
      }
    }
  }
  await auditMinifigureQuantity(client);
  process.stdout.write("Responsive browser audit passed.\n");
} finally {
  if (client && targetId) {
    try {
      await client.send("Target.closeTarget", {targetId}, null);
    } catch {
      // The renderer may already be gone after a failed assertion.
    }
  }
  client?.close();
  browser.kill();
  await Promise.race([
    new Promise((resolve) => browser.once("exit", resolve)),
    delay(2000),
  ]);
}
