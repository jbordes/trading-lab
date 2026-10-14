"use strict";

const ids = [
  "status", "freshness", "source", "account", "server", "currency", "balance",
  "equity", "profit", "margin-free", "margin-level", "positions", "orders", "margin"
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const statusDot = document.getElementById("status-dot");
const identityPanel = document.querySelector(".identity");
const metricsPanel = document.querySelector(".metrics");
const errorBox = document.getElementById("error");
const profitCard = document.getElementById("profit-card");
const chartEmpty = document.getElementById("chart-empty");
const chart = document.getElementById("chart");
const chartHigh = document.getElementById("chart-high");
const chartLow = document.getElementById("chart-low");
const chartStart = document.getElementById("chart-start");
const chartEnd = document.getElementById("chart-end");
const chartSpan = document.getElementById("chart-span");
const balanceLine = document.getElementById("balance-line");
const equityLine = document.getElementById("equity-line");
const grid = document.getElementById("grid");
const magicFilter = document.getElementById("magic-filter");
const magicOptions = document.getElementById("magic-options");
const operationsBody = document.getElementById("operations-body");
const operationsEmpty = document.getElementById("operations-empty");
const operationsBadge = document.getElementById("operations-badge");
const visibleOperations = document.getElementById("visible-operations");
const visiblePositions = document.getElementById("visible-positions");
const visibleOrders = document.getElementById("visible-orders");
const clearFilter = document.getElementById("clear-filter");
let latestOperations = [];
let latestCurrency = "USD";
let latestActivity = [];
let latestActivityDataKey = "";
let latestActivitySignature = "";
let latestActivityWindowHours = 24;
let latestIntervalSeconds = 5;
let lastObservedAt = null;
let latestOperationsSignature = "";
let latestMagicKey = "";
let latestActivityMagicKey = "";
let activeView = "overview";
let lastHistory = [];
let latestSource = "MT5";

const activityElements = {
  badge: document.getElementById("activity-badge"),
  body: document.getElementById("activity-body"),
  empty: document.getElementById("activity-empty"),
  magicFilter: document.getElementById("activity-magic-filter"),
  magicOptions: document.getElementById("activity-magic-options"),
  kindFilter: document.getElementById("activity-kind-filter"),
  clearFilter: document.getElementById("clear-activity-filter"),
  visible: document.getElementById("visible-activity"),
  deals: document.getElementById("visible-deals"),
  orders: document.getElementById("visible-history-orders"),
  copy: document.getElementById("activity-copy"),
};

const captureElements = {
  health: document.getElementById("capture-health"),
  streak: document.getElementById("capture-streak"),
  lastSuccess: document.getElementById("capture-last-success"),
  age: document.getElementById("capture-age"),
  duration: document.getElementById("capture-duration"),
  maxDuration: document.getElementById("capture-max-duration"),
  attempts: document.getElementById("capture-attempts"),
  results: document.getElementById("capture-results"),
};

const operationTypes = {
  buy: "Compra",
  sell: "Venta",
  buy_limit: "Buy limit",
  sell_limit: "Sell limit",
  buy_stop: "Buy stop",
  sell_stop: "Sell stop",
  buy_stop_limit: "Buy stop limit",
  sell_stop_limit: "Sell stop limit",
  close_by: "Close by",
};

const activityTypes = {
  buy_in: "Compra · entrada",
  buy_out: "Compra · salida",
  buy_inout: "Compra · reversión",
  buy_out_by: "Compra · cierre por",
  sell_in: "Venta · entrada",
  sell_out: "Venta · salida",
  sell_inout: "Venta · reversión",
  sell_out_by: "Venta · cierre por",
  balance: "Balance",
  credit: "Crédito",
  charge: "Cargo",
  correction: "Corrección",
  bonus: "Bonus",
  commission: "Comisión",
  commission_daily: "Comisión diaria",
  commission_monthly: "Comisión mensual",
  interest: "Interés",
  dividend: "Dividendo",
  tax: "Impuesto",
  ...operationTypes,
};

const activityStates = {
  started: "Iniciada",
  placed: "Colocada",
  canceled: "Cancelada",
  partial: "Parcial",
  filled: "Completada",
  rejected: "Rechazada",
  expired: "Expirada",
  request_add: "Solicitud de alta",
  request_modify: "Solicitud de cambio",
  request_cancel: "Solicitud de cancelación",
};

const LOCALE = "es-AR";
const numberFormatter = new Intl.NumberFormat(LOCALE, { useGrouping: "always" });
const decimalFormatter = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
  useGrouping: "always",
});
const priceFormatter = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
  useGrouping: "always",
});
const timeFormatter = new Intl.DateTimeFormat(LOCALE, {
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});
const dateTimeFormatter = new Intl.DateTimeFormat(LOCALE, {
  dateStyle: "short", timeStyle: "medium", hour12: false,
});
const moneyFormatters = new Map();

function money(value, currency, signed = false) {
  if (!Number.isFinite(value)) return "—";
  const key = `${currency}|${signed}`;
  let formatter = moneyFormatters.get(key);
  if (formatter === undefined) {
    try {
      formatter = new Intl.NumberFormat(LOCALE, {
        style: "currency",
        currency,
        useGrouping: "always",
        signDisplay: signed ? "exceptZero" : "auto",
      });
    } catch (_) {
      formatter = null;
    }
    moneyFormatters.set(key, formatter);
  }
  if (formatter) return formatter.format(value);
  return `${value.toFixed(2)} ${currency}`;
}

function number(value) {
  return Number.isFinite(value) ? numberFormatter.format(value) : "—";
}

const statusLabels = {
  connected: "Conectado",
  degraded: "Lectura degradada",
  starting: "Iniciando",
};

const captureHealthLabels = {
  connected: "Normal",
  degraded: "Degradada",
  starting: "Iniciando",
};

function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

function toDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function renderState(state) {
  setText(elements.status, statusLabels[state.status] || "Lectura degradada");
  statusDot.className = `status-dot ${state.status}`;
  const errorText = state.error || "";
  if (errorText) setText(errorBox, errorText);
  errorBox.hidden = !errorText;
  renderCapture(state);
  if (!state.latest) return;

  const value = state.latest;
  latestIntervalSeconds = state.interval_seconds || 5;
  const observedAt = toDate(value.observed_at);
  const ageSeconds = observedAt
    ? Math.max(0, (Date.now() - observedAt.getTime()) / 1000)
    : Infinity;
  const staleData = ageSeconds > 2 * latestIntervalSeconds;
  const criticalAge = ageSeconds > 10 * latestIntervalSeconds;
  setText(elements.freshness, observedAt
    ? `hace ${elapsed(ageSeconds)} · cada ${elapsed(latestIntervalSeconds)}`
    : "sin lectura válida");
  elements.freshness.title = observedAt ? `Última lectura ${timeFormatter.format(observedAt)}` : "";
  elements.freshness.classList.toggle("aged", staleData && !criticalAge);
  elements.freshness.classList.toggle("stale", criticalAge);
  identityPanel.classList.toggle("stale", staleData);
  metricsPanel.classList.toggle("stale", staleData);
  if (value.observed_at === lastObservedAt) return;
  lastObservedAt = value.observed_at;
  const currency = value.currency || "USD";
  latestCurrency = currency;
  latestSource = value.source.toUpperCase();
  elements.source.textContent = latestSource;
  elements.account.textContent = value.account_reference;
  elements.server.textContent = value.server;
  elements.currency.textContent = value.currency || "—";
  elements.balance.textContent = money(value.balance, currency);
  elements.equity.textContent = money(value.equity, currency);
  elements.profit.textContent = money(value.floating_profit, currency, true);
  elements["margin-free"].textContent = money(value.margin_free, currency);
  elements["margin-level"].textContent = value.margin_level === null
    ? "Nivel —"
    : `Nivel ${number(value.margin_level)}%`;
  elements.positions.textContent = number(value.open_positions);
  elements.orders.textContent = number(value.active_orders);
  elements.margin.textContent = money(value.margin, currency);
  profitCard.classList.toggle("positive", value.floating_profit > 0);
  profitCard.classList.toggle("negative", value.floating_profit < 0);
  latestOperations = Array.isArray(value.operations) ? value.operations : [];
  operationsBadge.textContent = number(latestOperations.length);
  if (activeView === "operations") renderOperations();
  const nextActivity = Array.isArray(value.recent_activity) ? value.recent_activity : [];
  latestActivityWindowHours = value.activity_window_hours || 24;
  const nextActivityKey = JSON.stringify(nextActivity);
  if (nextActivityKey !== latestActivityDataKey) {
    latestActivity = nextActivity;
    latestActivityDataKey = nextActivityKey;
  }
  activityElements.badge.textContent = number(latestActivity.length);
  if (activeView === "activity") renderActivity();
  lastHistory = state.history;
  if (activeView === "overview") renderChart(state.history, latestIntervalSeconds);
}

function renderCapture(state) {
  const capture = state.capture || {};
  const failures = capture.consecutive_failures || 0;
  setText(captureElements.health, captureHealthLabels[state.status] || "Degradada");
  captureElements.health.className = state.status === "connected"
    ? "positive-text"
    : state.status === "starting" ? "" : "negative-text";
  setText(captureElements.streak, failures === 0
    ? "Sin fallos consecutivos"
    : `${number(failures)} fallo${failures === 1 ? "" : "s"} consecutivo${failures === 1 ? "" : "s"}`);
  const lastSuccessAt = capture.last_success_at ? toDate(capture.last_success_at) : null;
  setText(captureElements.lastSuccess, lastSuccessAt ? timeFormatter.format(lastSuccessAt) : "—");
  const ageSeconds = lastSuccessAt
    ? Math.max(0, (Date.now() - lastSuccessAt.getTime()) / 1000)
    : null;
  setText(captureElements.age, ageSeconds === null ? "Edad —" : `Edad ${elapsed(ageSeconds)}`);
  setText(captureElements.duration, Number.isFinite(capture.last_duration_ms)
    ? `${number(capture.last_duration_ms)} ms`
    : "—");
  setText(captureElements.maxDuration, Number.isFinite(capture.max_duration_ms)
    ? `Máximo ${number(capture.max_duration_ms)} ms`
    : "Máximo —");
  setText(captureElements.attempts, number(capture.attempt_count || 0));
  setText(captureElements.results, `${number(capture.success_count || 0)} correctos · ${number(capture.failure_count || 0)} fallidos`);
}

function renderActivity() {
  const magic = activityElements.magicFilter.value.trim();
  const kind = activityElements.kindFilter.value;
  const signature = `${magic}|${kind}|${latestActivityWindowHours}|${latestActivityDataKey}`;
  if (signature === latestActivitySignature) return;
  latestActivitySignature = signature;
  const filtered = latestActivity.filter((item) => (
    (!magic || String(item.magic_number) === magic) && (!kind || item.category === kind)
  ));
  const magicNumbers = [...new Set(latestActivity.map((item) => String(item.magic_number)))];
  magicNumbers.sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  const magicKey = magicNumbers.join(",");
  if (magicKey !== latestActivityMagicKey) {
    latestActivityMagicKey = magicKey;
    activityElements.magicOptions.replaceChildren(...magicNumbers.map((value) => {
      const option = document.createElement("option");
      option.value = value;
      return option;
    }));
  }
  activityElements.body.replaceChildren(...filtered.map(activityRow));
  activityElements.empty.hidden = filtered.length > 0;
  activityElements.empty.textContent = latestActivity.length === 0
    ? `${latestSource} no informa actividad dentro de la ventana actual.`
    : "Ningún evento coincide con los filtros.";
  activityElements.visible.textContent = number(filtered.length);
  activityElements.deals.textContent = number(filtered.filter((item) => item.category === "deal").length);
  activityElements.orders.textContent = number(filtered.filter((item) => item.category === "order").length);
  activityElements.copy.textContent = `Operaciones cerradas (deals) y órdenes de las últimas ${number(latestActivityWindowHours)} horas.`;
  activityElements.clearFilter.disabled = !magic && !kind;
}

function activityRow(activity) {
  const row = document.createElement("tr");
  const occurredAt = toDate(activity.occurred_at);
  row.appendChild(textCell(occurredAt ? dateTimeFormatter.format(occurredAt) : "—"));
  const eventCell = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = `operation-kind ${activity.category}`;
  badge.textContent = activity.category === "deal" ? "Deal" : "Orden";
  eventCell.appendChild(badge);
  const eventText = document.createElement("small");
  eventText.className = "activity-event";
  const eventName = activityTypes[activity.event_type] || activity.event_type.replaceAll("_", " ");
  const stateName = activity.event_state ? activityStates[activity.event_state] || activity.event_state : "";
  eventText.textContent = stateName ? `${eventName} · ${stateName}` : eventName;
  eventCell.appendChild(eventText);
  row.appendChild(eventCell);
  row.appendChild(detailCell(`#${activity.ticket}`, `Magic ${activity.magic_number}`, "mono"));
  row.appendChild(detailCell(activity.symbol, activity.comment || "Sin comentario"));
  row.appendChild(detailCell(decimal(activity.volume), price(activity.price), "numeric"));

  const components = [activity.profit, activity.commission, activity.swap, activity.fee]
    .filter((value) => Number.isFinite(value));
  const netResult = components.length ? components.reduce((total, value) => total + value, 0) : null;
  const breakdown = components.length
    ? `P&L ${money(activity.profit || 0, latestCurrency)} · costes ${money((activity.commission || 0) + (activity.swap || 0) + (activity.fee || 0), latestCurrency)}`
    : "Sin resultado monetario";
  row.appendChild(detailCell(
    netResult === null ? "—" : money(netResult, latestCurrency, true),
    breakdown,
    `numeric ${netResult === null ? "" : netResult > 0 ? "positive-text" : netResult < 0 ? "negative-text" : ""}`,
  ));
  const reference = activity.position_id ? `Posición ${activity.position_id}` : "Sin posición";
  const order = activity.order_ticket ? `Orden ${activity.order_ticket}` : "";
  row.appendChild(detailCell(reference, order));
  return row;
}

function elapsed(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

function renderOperations() {
  const filter = magicFilter.value.trim();
  const signature = `${filter}|${JSON.stringify(latestOperations)}`;
  if (signature === latestOperationsSignature) return;
  latestOperationsSignature = signature;
  const filtered = latestOperations.filter((operation) => (
    !filter || String(operation.magic_number) === filter
  ));
  const magicNumbers = [...new Set(latestOperations.map((item) => String(item.magic_number)))];
  magicNumbers.sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  const magicKey = magicNumbers.join(",");
  if (magicKey !== latestMagicKey) {
    latestMagicKey = magicKey;
    magicOptions.replaceChildren(...magicNumbers.map((magic) => {
      const option = document.createElement("option");
      option.value = magic;
      return option;
    }));
  }

  operationsBody.replaceChildren(...filtered.map(operationRow));
  operationsEmpty.hidden = filtered.length > 0;
  operationsEmpty.textContent = latestOperations.length === 0
    ? `${latestSource} no informa operaciones activas.`
    : "Ninguna operación coincide con ese magic number.";
  visibleOperations.textContent = number(filtered.length);
  visiblePositions.textContent = number(filtered.filter((item) => item.kind === "position").length);
  visibleOrders.textContent = number(filtered.filter((item) => item.kind === "order").length);
  clearFilter.disabled = !filter;
}

function operationRow(operation) {
  const row = document.createElement("tr");
  const kind = operation.kind === "position" ? "Posición" : "Orden";
  const kindCell = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = `operation-kind ${operation.kind}`;
  badge.textContent = kind;
  kindCell.appendChild(badge);
  row.appendChild(kindCell);
  row.appendChild(detailCell(`#${operation.ticket}`, `Magic ${operation.magic_number}`, "mono"));
  row.appendChild(detailCell(operation.symbol, operation.comment || "Sin comentario"));
  row.appendChild(textCell(operationTypes[operation.operation_type] || operation.operation_type));
  row.appendChild(textCell(decimal(operation.volume), "numeric"));
  row.appendChild(detailCell(price(operation.price_open), price(operation.price_current), "numeric"));
  row.appendChild(detailCell(price(operation.stop_loss), price(operation.take_profit), "numeric"));

  const profit = document.createElement("td");
  profit.className = "numeric operation-profit";
  if (Number.isFinite(operation.floating_profit)) {
    profit.textContent = money(operation.floating_profit, latestCurrency, true);
    if (operation.floating_profit > 0) profit.classList.add("positive");
    else if (operation.floating_profit < 0) profit.classList.add("negative");
  } else {
    profit.textContent = "—";
  }
  row.appendChild(profit);
  const openedAt = operation.opened_at ? toDate(operation.opened_at) : null;
  row.appendChild(textCell(openedAt ? dateTimeFormatter.format(openedAt) : "—"));
  return row;
}

function textCell(value, className = "") {
  const cell = document.createElement("td");
  cell.className = className;
  cell.textContent = value;
  return cell;
}

function detailCell(primary, secondary, className = "") {
  const cell = document.createElement("td");
  cell.className = `cell-detail ${className}`.trim();
  const strong = document.createElement("strong");
  strong.textContent = primary;
  const small = document.createElement("small");
  small.textContent = secondary;
  if (secondary) small.title = secondary;
  cell.append(strong, small);
  return cell;
}

function decimal(value) {
  return Number.isFinite(value) ? decimalFormatter.format(value) : "—";
}

function price(value) {
  return Number.isFinite(value) ? priceFormatter.format(value) : "—";
}

function renderChart(history, intervalSeconds) {
  const clearLabels = () => {
    chartHigh.textContent = "";
    chartLow.textContent = "";
    chartStart.textContent = "";
    chartEnd.textContent = "";
    chartSpan.textContent = "";
  };
  if (history.length < 2) {
    chartEmpty.hidden = false;
    balanceLine.setAttribute("points", "");
    equityLine.setAttribute("points", "");
    chart.setAttribute("aria-label", "Evolución reciente de balance y equity");
    clearLabels();
    return;
  }
  chartEmpty.hidden = true;
  let minimum = Infinity;
  let maximum = -Infinity;
  for (const item of history) {
    minimum = Math.min(minimum, item.balance, item.equity);
    maximum = Math.max(maximum, item.balance, item.equity);
  }
  const padding = Math.max((maximum - minimum) * 0.15, Math.abs(maximum) * 0.0001, 1);
  const low = minimum - padding;
  const high = maximum + padding;
  const toPoints = (key) => history.map((item, index) => {
    const x = 25 + (index / (history.length - 1)) * 950;
    const y = 295 - ((item[key] - low) / (high - low)) * 270;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  balanceLine.setAttribute("points", toPoints("balance"));
  equityLine.setAttribute("points", toPoints("equity"));
  const startAt = toDate(history[0].observed_at);
  const endAt = toDate(history[history.length - 1].observed_at);
  chartHigh.textContent = `Máx ${money(maximum, latestCurrency)}`;
  chartLow.textContent = `Mín ${money(minimum, latestCurrency)}`;
  chartStart.textContent = startAt ? timeFormatter.format(startAt) : "";
  chartEnd.textContent = endAt ? timeFormatter.format(endAt) : "";
  const span = elapsed(history.length * intervalSeconds);
  chartSpan.textContent = `Ventana ${span}`;
  chart.setAttribute("aria-label", `Evolución de balance y equity, ventana ${span}`);
}

function drawGrid() {
  const namespace = "http://www.w3.org/2000/svg";
  for (let index = 0; index < 5; index += 1) {
    const line = document.createElementNS(namespace, "line");
    const y = 25 + index * 67.5;
    line.setAttribute("x1", "25");
    line.setAttribute("x2", "975");
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    line.setAttribute("class", "grid-line");
    grid.appendChild(line);
  }
}

async function refresh() {
  if (document.hidden) return;
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    2 * latestIntervalSeconds * 1000,
  );
  try {
    const response = await fetch("/api/state", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderState(await response.json());
  } catch (_) {
    setText(elements.status, "Sin conexión local");
    statusDot.className = "status-dot degraded";
    elements.freshness.classList.add("stale");
    setText(errorBox, "No se pudo consultar el servicio local.");
    errorBox.hidden = false;
  } finally {
    window.clearTimeout(timeout);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});

drawGrid();
document.querySelectorAll(".view-tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".view-tab").forEach((tab) => {
      const active = tab === button;
      tab.classList.toggle("active", active);
      if (active) tab.setAttribute("aria-current", "page");
      else tab.removeAttribute("aria-current");
    });
    document.querySelectorAll(".dashboard-view").forEach((view) => {
      view.hidden = view.id !== `${button.dataset.view}-view`;
    });
    activeView = button.dataset.view;
    if (activeView === "operations") renderOperations();
    else if (activeView === "activity") renderActivity();
    else renderChart(lastHistory, latestIntervalSeconds);
  });
});
magicFilter.addEventListener("input", renderOperations);
clearFilter.addEventListener("click", () => {
  magicFilter.value = "";
  magicFilter.focus();
  renderOperations();
});
activityElements.magicFilter.addEventListener("input", () => renderActivity());
activityElements.kindFilter.addEventListener("change", () => renderActivity());
activityElements.clearFilter.addEventListener("click", () => {
  activityElements.magicFilter.value = "";
  activityElements.kindFilter.value = "";
  activityElements.magicFilter.focus();
  renderActivity();
});
function scheduleRefresh() {
  window.setTimeout(() => {
    refresh().finally(scheduleRefresh);
  }, latestIntervalSeconds * 1000);
}

refresh().finally(scheduleRefresh);
