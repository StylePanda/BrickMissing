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
  throw lastError;
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
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
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

async function auditDashboard(client) {
  const result = await evaluate(client, `(() => ({
    title: Boolean(document.querySelector("h1")),
    search: document.querySelector("#collection-search")?.getBoundingClientRect().height || 0,
    actionCount: document.querySelectorAll(".page-head .actions .button").length,
    stats: [...document.querySelectorAll(".stats article")].map((node) => node.getBoundingClientRect().right),
    valuesFit: [...document.querySelectorAll(".stats strong")].every((node) => node.scrollWidth <= node.clientWidth + 1)
  }))()`);
  assert(result.title, "Dashboard title is not visible");
  assert(result.search >= 40 && result.search <= 64, "Dashboard search has an unreasonable height");
  assert(result.actionCount >= 2, "Dashboard primary actions are missing");
  assert(result.stats.every((right) => right <= 391), "Dashboard statistic card escapes the viewport");
  assert(result.valuesFit, "Dashboard statistic value overflows its card");
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
    }
  }
  for (const width of desktopWidths) {
    await setViewport(client, width, width >= 1440 ? 900 : 1024);
    for (const name of ["dashboard", "sets", "setForm", "setDetail"]) {
      await navigate(client, routes.authenticated[name]);
      await auditOverflow(client, name, width);
    }
  }

  await setViewport(client, 768, 1024);
  await navigate(client, routes.authenticated.sets);
  await auditTabletSetFilters(client, 768);

  await setViewport(client, 390, 844);
  await navigate(client, routes.authenticated.sets);
  await auditSetFilters(client);
  await auditNavigation(client);
  await navigate(client, routes.authenticated.dashboard);
  await auditDashboard(client);
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
      for (const name of ["dashboard", "sets", "setForm"]) {
        await navigate(client, routes.authenticated[name]);
        const capture = await client.send("Page.captureScreenshot", {format: "png", fromSurface: true});
        await writeFile(join(artifactDirectory, `${name}-${width}x${height}.png`), Buffer.from(capture.data, "base64"));
      }
    }
  }
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
