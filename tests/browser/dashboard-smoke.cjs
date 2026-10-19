/* Optional browser checks. Requires an isolated Chrome debugging port and the demo server.
 * node tests/browser/dashboard-smoke.cjs [http://127.0.0.1:8786] [http://127.0.0.1:9340]
 * Screenshots and results go to ignored _storage/product-design-review.
 */
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

async function main() {
  const base = new URL(process.argv[2] || "http://127.0.0.1:8786");
  const debug = new URL(process.argv[3] || "http://127.0.0.1:9340");
  for (const url of [base, debug]) {
    assert.equal(url.hostname, "127.0.0.1", "Only isolated localhost services are allowed");
    assert.equal(url.protocol, "http:");
  }
  const initial = await (await fetch(new URL("/api/state", base))).json();
  assert.equal(initial.latest?.source, "demo", "Never run this test against a live account");
  const output = path.resolve(__dirname, "../../_storage/product-design-review");
  fs.mkdirSync(output, { recursive: true });
  const pages = await (await fetch(new URL("/json/list", debug))).json();
  const ws = new WebSocket(pages.find((page) => page.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(request.timeout);
      if (message.error) request.reject(new Error(JSON.stringify(message.error)));
      else request.resolve(message.result);
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails);
    }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const key = ++id;
    const timeout = setTimeout(() => reject(new Error(`Timeout: ${method}`)), 10000);
    pending.set(key, { resolve, reject, timeout });
    ws.send(JSON.stringify({ id: key, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const screenshot = async (name) => {
    const result = await call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    fs.writeFileSync(path.join(output, `${name}.png`), Buffer.from(result.data, "base64"));
  };
  const navigate = async (route) => {
    await call("Page.navigate", { url: new URL(route, base).href });
    for (let attempt = 0; attempt < 50; attempt++) {
      if (await evaluate(`document.readyState === 'complete' && (${JSON.stringify(route)} === '/' || Boolean(document.getElementById('mode-notice') && !document.getElementById('mode-notice').hidden))`)) return;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`Page did not become ready: ${route}`);
  };
  try {
    await call("Page.enable");
    await call("Runtime.enable");
    // La prueba controla cada lectura; los polls automáticos causarían carreras con los fallos simulados.
    await call("Page.addScriptToEvaluateOnNewDocument", {
      source: "window.setInterval = () => 0; window.setTimeout = () => 0;",
    });
    const layouts = [];
    for (const theme of ["light", "dark"]) {
      // Contraste de pestaña y página pueden ser opuestos.
      await call("Emulation.setEmulatedMedia", {
        features: [{ name: "prefers-color-scheme", value: theme === "light" ? "dark" : "light" }],
      });
      for (const width of [1440, 768, 390, 320]) {
        await call("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
        for (const route of ["/", "/dashboard#overview", "/dashboard#operations", "/dashboard#activity"]) {
          await navigate(route);
          await evaluate(`(() => {
            const current = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
            if (current !== ${JSON.stringify(theme)}) document.querySelector('[data-theme-toggle]').click();
          })()`);
          const layout = await evaluate(`({
            width: document.documentElement.clientWidth,
            scroll: document.documentElement.scrollWidth,
            footer: document.querySelector('footer').getBoundingClientRect().top,
            tableBottom: document.querySelector('#operations-view:not([hidden]) .operations-table')?.getBoundingClientRect().bottom || 0,
            chartTop: document.querySelector('#overview-view:not([hidden]) .chart-panel')?.getBoundingClientRect().top || 0,
            navPosition: document.querySelector('.site-nav-links') ? getComputedStyle(document.querySelector('.site-nav-links')).position : null,
            logo: getComputedStyle(document.querySelector('.brand-mark')).backgroundImage,
            iconTheme: document.querySelector('[data-theme-icon]')?.dataset.themeIcon || '',
            browserTheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
            squareIcon: document.querySelector('[data-theme-icon]')?.href.includes('/assets/favicon-') || false,
            publicHeader: Boolean(document.querySelector('.public-header')),
            viewCount: document.querySelectorAll('.view-tab').length,
            homeLinks: document.querySelectorAll('a[href^="/dashboard#"]').length,
            title: document.querySelector('#page-title')?.textContent || ''
          })`);
          const name = `${theme}-${width}-${route === "/" ? "home" : route.split("#")[1]}`;
          layouts.push({ name, ...layout });
          assert.ok(layout.scroll <= layout.width, `${name}: horizontal overflow ${JSON.stringify(layout)}`);
          assert.ok(layout.footer >= layout.tableBottom, `${name}: footer overlaps operations`);
          assert.equal(layout.navPosition, route === "/" ? null : width < 1000 ? "fixed" : "static", `${name}: navigation position`);
          assert.equal(layout.publicHeader, route === "/", `${name}: public and workspace shells are separate`);
          assert.equal(layout.viewCount, route === "/" ? 0 : 3, `${name}: dashboard has only its three views`);
          assert.equal(layout.homeLinks, 0, `${name}: no cross-section links from presentation page`);
          assert.ok(layout.logo.includes(`tradinglab-apple-touch-icon-${theme === "light" ? "black" : "white"}.png`), `${name}: logo theme`);
          assert.equal(layout.iconTheme, layout.browserTheme, `${name}: favicon follows browser preference`);
          assert.ok(layout.squareIcon, `${name}: favicon keeps logo aspect on a square canvas`);
          if (route.includes("#")) {
            const expected = { overview: "Resumen", operations: "Operaciones", activity: "Actividad" }[route.split("#")[1]];
            assert.equal(layout.title, expected, `${name}: page title`);
          }
          await screenshot(name);
        }
      }
    }
    await call("Emulation.setEmulatedMedia", { features: [] });
    await navigate("/dashboard#operations");
    const interaction = await evaluate(`(async () => {
      const state = await (await fetch('/api/state')).json();
      window.fetch = async () => ({ ok: true, json: async () => state });
      renderState(state);
      document.querySelector('#tab-operations').dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
      const endWorks = document.activeElement.id === 'tab-activity' && activeView === 'activity';
      document.querySelector('#tab-activity').dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
      const keyboard = endWorks && document.activeElement.id === 'tab-overview' && activeView === 'overview';
      document.querySelector('#tab-operations').click();
      magicFilter.value = ''; kindFilter.value = 'all'; renderOperations();
      const button = document.querySelector('.detail-toggle');
      button.click(); button.focus();
      const originalRow = button.closest('tr');
      latestOperations = latestOperations.map((item, index) => index ? item : { ...item, floating_profit: 123.45 });
      renderOperations();
      const stable = document.activeElement === button && originalRow.isConnected
        && button.getAttribute('aria-expanded') === 'true'
        && !document.getElementById(button.getAttribute('aria-controls')).hidden;
      button.click();
      const toggleWorks = document.getElementById(button.getAttribute('aria-controls')).hidden;
      const magic = String(latestOperations[0].magic_number);
      magicFilter.value = magic; kindFilter.value = 'position'; renderOperations(); saveStoredFilters();
      const exact = [...operationsBody.querySelectorAll('.cell-detail small')].every((el) => el.textContent === 'Magic ' + magic)
        && operationsBody.querySelectorAll('.operation-kind.order').length === 0;
      loadStoredFilters(currentFilterScope); renderOperations();
      const persisted = magicFilter.value === magic && kindFilter.value === 'position';
      const scope = currentFilterScope;
      loadStoredFilters('isolated-test-source'); renderOperations();
      const isolated = magicFilter.value === '' && kindFilter.value === 'all';
      loadStoredFilters(scope); renderOperations();
      latestOperations = []; renderOperations();
      const missing = magicFilter.value === magic && magicFilter.selectedOptions[0].textContent.includes('sin operaciones');
      clearFilter.click();
      const empty = !operationsEmpty.hidden && operationsEmpty.textContent.includes('no informa');
      latestObservedDate = null; latestOperationsSignature = ''; renderOperations();
      const loading = operationsEmpty.textContent.includes('Esperando');
      serviceReachable = false; renderOperations(); updateFreshness();
      const offlineFirst = operationsEmpty.textContent.includes('No hay una lectura');
      latestObservedDate = new Date(Date.now() - 600000); serviceReachable = true; latestStatus = 'connected';
      latestHealthState = { ...state, latest: { ...state.latest, observed_at: latestObservedDate.toISOString() }};
      updateFreshness();
      const stale = elements.status.textContent === 'Datos desactualizados' && healthOverview.classList.contains('warning');
      latestObservedDate = new Date(); latestHealthState = { ...state, latest: { ...state.latest, observed_at: latestObservedDate.toISOString() }};
      renderState(latestHealthState);
      const recovered = !metricsPanel.classList.contains('stale') && healthOverview.classList.contains('positive');
      window.fetch = async () => { throw new Error('Controlled offline test'); };
      await performRefresh();
      const networkFailure = !errorBox.hidden && elements.status.textContent === 'Sin conexión local';
      window.fetch = async () => ({ ok: true, json: async () => state });
      await performRefresh();
      const networkRecovery = errorBox.hidden && serviceReachable;
      const bigMagic = '18446744073709551615';
      latestOperations = Array.from({ length: 35 }, (_, i) => ({ ...state.latest.operations[0], ticket: String(i + 1),
        magic_number: bigMagic, symbol: 'SYMBOL_WITH_A_LONG_SUFFIX', comment: 'Long '.repeat(80) }));
      updateMagicOptions(bigMagic); renderOperations();
      document.querySelector('.detail-toggle').click();
      const overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;
      const footerClear = document.querySelector('footer').getBoundingClientRect().top >= operationsBody.getBoundingClientRect().bottom;
      return { keyboard, isolated, networkFailure, networkRecovery, stable, toggleWorks, exact, persisted, missing, empty, loading, offlineFirst, stale, recovered,
        longIdentifiers: magicFilter.value === bigMagic, noOverflow: !overflow, footerClear };
    })()`);
    await screenshot("stress-mobile-details");
    for (const [name, result] of Object.entries(interaction)) assert.equal(result, true, name);
    assert.equal(errors.length, 0, JSON.stringify(errors));
    fs.writeFileSync(path.join(output, "results.json"), JSON.stringify({ layouts, interaction, errors }, null, 2));
    console.log(JSON.stringify({ layouts: layouts.length, interaction, errors }));
  } finally {
    ws.close();
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
