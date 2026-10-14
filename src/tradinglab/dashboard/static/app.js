"use strict";

const ids = [
  "status", "freshness", "source", "account", "server", "currency", "balance",
  "equity", "profit", "margin-free", "margin-level", "positions", "orders", "margin"
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const statusDot = document.getElementById("status-dot");
const identityPanel = document.querySelector(".identity");
const metricsPanel = document.querySelector(".metrics");
const sourcePill = document.getElementById("source-pill");
const groupByBotInput = document.getElementById("group-by-bot");
const errorHuman = document.getElementById("error-human");
const errorTechnical = document.getElementById("error-technical");
const errorTechnicalDetails = document.getElementById("error-technical-details");
const plainSummary = document.getElementById("plain-summary");
const riskBadge = document.getElementById("risk-badge");
const dddMeter = document.getElementById("ddd-meter");
const dddValue = document.getElementById("ddd-value");
const dddFill = document.getElementById("ddd-fill");
const dddCaption = document.getElementById("ddd-caption");
const maxddMeter = document.getElementById("maxdd-meter");
const maxddValue = document.getElementById("maxdd-value");
const maxddFill = document.getElementById("maxdd-fill");
const maxddCaption = document.getElementById("maxdd-caption");
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
const balanceReference = document.getElementById("balance-reference");
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
let lastPollSince = null;

const activityElements = {
  badge: document.getElementById("activity-badge"),
  body: document.getElementById("activity-body"),
  empty: document.getElementById("activity-empty"),
  magicFilter: document.getElementById("activity-magic-filter"),
  magicOptions: document.getElementById("activity-magic-options"),
  kindFilter: document.getElementById("activity-kind-filter"),
  resultFilter: document.getElementById("activity-result-filter"),
  windowPnl: document.getElementById("window-pnl-value"),
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
  buy_limit: "Compra limit",
  sell_limit: "Venta limit",
  buy_stop: "Compra stop",
  sell_stop: "Venta stop",
  buy_stop_limit: "Compra stop limit",
  sell_stop_limit: "Venta stop limit",
  close_by: "Cierre por otra",
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
  const safeCurrency = /^[A-Za-z]{3}$/.test(currency) ? currency : "USD";
  const key = `${safeCurrency}|${signed}`;
  let formatter = moneyFormatters.get(key);
  if (formatter === undefined) {
    try {
      formatter = new Intl.NumberFormat(LOCALE, {
        style: "currency",
        currency: safeCurrency,
        useGrouping: "always",
        signDisplay: signed ? "exceptZero" : "auto",
      });
    } catch (_) {
      formatter = null;
    }
    moneyFormatters.set(key, formatter);
  }
  if (formatter) return formatter.format(value);
  return `${value.toFixed(2)} ${safeCurrency}`;
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

// PROTOTIPO incremento 1: el panel de riesgo muestra la estructura final con
// valores ilustrativos SOLO para la fuente demo. Los números reales llegarán
// desde el snapshot cuando el contrato DDD/Max DD se apruebe con el socio.
const DEMO_RISK = {
  ddd: { usedPercent: 19, value: -0.95, limit: 5, caption: "reset a medianoche (Madrid)" },
  maxdd: { usedPercent: 62, value: -12.3, limit: 20, caption: "acumulado desde el inicio de la incubación" },
};

const madridPartsFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: "Europe/Madrid", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});

function madridResetLabel() {
  const parts = madridPartsFormatter.formatToParts(new Date());
  const hour = Number(parts.find((part) => part.type === "hour").value);
  const minute = Number(parts.find((part) => part.type === "minute").value);
  const second = Number(parts.find((part) => part.type === "second").value);
  const remaining = (24 * 3600 - (hour * 3600 + minute * 60 + second)) % (24 * 3600);
  return `faltan ${elapsed(remaining)}`;
}

function setRiskMeter(meter, valueEl, fillEl, captionEl, metric) {
  setText(valueEl, `${decimal(metric.value)} %`);
  const percent = Math.min(100, metric.usedPercent);
  fillEl.style.width = `${percent}%`;
  meter.classList.toggle("warn", percent >= 50 && percent < 80);
  meter.classList.toggle("critical", percent >= 80);
  setText(captionEl, `Usado el ${Math.round(percent)} % del límite (${decimal(metric.limit)} %) · ${metric.caption}`);
}

function clearRiskMeter(meter, valueEl, fillEl, captionEl) {
  setText(valueEl, "—");
  fillEl.style.width = "0%";
  meter.classList.remove("warn", "critical");
  setText(captionEl, "Fórmula y límites pendientes de validación con el socio.");
}

function renderRisk(source) {
  if (source === "demo") {
    setText(riskBadge, "Contrato pendiente · valores ilustrativos");
    const ddd = { ...DEMO_RISK.ddd, caption: `${DEMO_RISK.ddd.caption} · ${madridResetLabel()}` };
    setRiskMeter(dddMeter, dddValue, dddFill, dddCaption, ddd);
    setRiskMeter(maxddMeter, maxddValue, maxddFill, maxddCaption, DEMO_RISK.maxdd);
  } else {
    setText(riskBadge, "Contrato pendiente");
    clearRiskMeter(dddMeter, dddValue, dddFill, dddCaption);
    clearRiskMeter(maxddMeter, maxddValue, maxddFill, maxddCaption);
  }
}

function renderSummary(value, currency, status) {
  const plural = (count, singular, pluralForm) => `${count} ${count === 1 ? singular : pluralForm}`;
  const positions = plural(value.open_positions || 0, "posición abierta", "posiciones abiertas");
  const orders = plural(value.active_orders || 0, "orden activa", "órdenes activas");
  const profit = money(value.floating_profit || 0, currency, true);
  const riskPhrase = value.source === "demo"
    ? "riesgo dentro del límite (valores ilustrativos)"
    : "métricas de riesgo pendientes de contrato";
  const capturePhrase = status === "connected" ? "" : " · captura degradada, los datos pueden estar atrasados";
  setText(plainSummary, `Cuenta ${latestSource} · ${positions} · ${orders} · resultado abierto ${profit} · ${riskPhrase}${capturePhrase}`);
}

function renderState(state) {
  setText(elements.status, statusLabels[state.status] || "Lectura degradada");
  statusDot.className = `status-dot ${state.status}`;
  const errorText = state.error || "";
  if (errorText) {
    setText(errorHuman, "No pudimos leer el terminal. Se conserva la última muestra válida.");
    setText(errorTechnical, errorText);
    errorTechnicalDetails.hidden = false;
  }
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
  lastPollSince = value.observed_at;
  const currency = value.currency || "USD";
  latestCurrency = currency;
  latestSource = value.source.toUpperCase();
  setText(sourcePill, latestSource);
  elements.source.textContent = latestSource;
  elements.account.textContent = value.account_reference;
  elements.server.textContent = value.server;
  elements.currency.textContent = value.currency || "—";
  elements.balance.textContent = money(value.balance, currency);
  elements.equity.textContent = money(value.equity, currency);
  elements.profit.textContent = money(value.floating_profit, currency, true);
  elements["margin-free"].textContent = money(value.margin_free, currency);
  elements["margin-level"].textContent = value.margin_level === null
    ? "—"
    : `${number(value.margin_level)} %`;
  elements.positions.textContent = number(value.open_positions);
  elements.orders.textContent = number(value.active_orders);
  elements.margin.textContent = money(value.margin, currency);
  renderRisk(value.source);
  renderSummary(value, currency, state.status);
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
  if (state.history_truncated) {
    const known = new Set(lastHistory.map((item) => item.observed_at));
    const fresh = state.history.filter((item) => !known.has(item.observed_at));
    lastHistory = [...lastHistory, ...fresh].slice(-720);
  } else {
    lastHistory = state.history;
  }
  if (activeView === "overview") renderChart(lastHistory, latestIntervalSeconds);
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
  const result = activityElements.resultFilter.value;
  const signature = `${magic}|${kind}|${result}|${latestActivityWindowHours}|${latestCurrency}|${latestSource}|${latestActivityDataKey}`;
  if (signature === latestActivitySignature) return;
  latestActivitySignature = signature;
  const filtered = latestActivity.filter((item) => {
    if (magic && String(item.magic_number) !== magic) return false;
    if (kind && item.category !== kind) return false;
    if (result) {
      const net = netOf(item) || 0;
      if (result === "profit" && net <= 0) return false;
      if (result === "loss" && net >= 0) return false;
    }
    return true;
  });
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
  activityElements.visible.textContent = (magic || kind || result)
    ? `${number(filtered.length)} de ${number(latestActivity.length)}`
    : number(filtered.length);
  activityElements.deals.textContent = number(filtered.filter((item) => item.category === "deal").length);
  activityElements.orders.textContent = number(filtered.filter((item) => item.category === "order").length);
  activityElements.copy.textContent = `Operaciones cerradas (deals) y órdenes de las últimas ${number(latestActivityWindowHours)} horas.`;
  const windowNet = latestActivity.reduce((total, item) => total + (netOf(item) || 0), 0);
  setText(activityElements.windowPnl, money(windowNet, latestCurrency, true));
  activityElements.windowPnl.className = windowNet > 0 ? "positive" : windowNet < 0 ? "negative" : "";
  activityElements.clearFilter.disabled = !magic && !kind && !result;
}

function netOf(activity) {
  const components = [activity.profit, activity.commission, activity.swap, activity.fee]
    .filter((value) => Number.isFinite(value));
  return components.length ? components.reduce((total, value) => total + value, 0) : null;
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

  const netResult = netOf(activity);
  const breakdown = netResult !== null
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
  const grouped = groupByBotInput.checked;
  const signature = `${latestCurrency}|${filter}|${grouped}|${JSON.stringify(latestOperations)}`;
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

  operationsBody.replaceChildren(...operationRows(filtered, grouped));
  operationsEmpty.hidden = filtered.length > 0;
  operationsEmpty.textContent = latestOperations.length === 0
    ? `${latestSource} no informa operaciones activas.`
    : "Ninguna operación coincide con ese magic number.";
  visibleOperations.textContent = filter
    ? `${number(filtered.length)} de ${number(latestOperations.length)}`
    : number(filtered.length);
  visiblePositions.textContent = number(filtered.filter((item) => item.kind === "position").length);
  visibleOrders.textContent = number(filtered.filter((item) => item.kind === "order").length);
  clearFilter.disabled = !filter;
}

function operationRows(operations, grouped) {
  if (!grouped) return operations.map(operationRow);
  const groups = new Map();
  for (const operation of operations) {
    const magic = String(operation.magic_number);
    if (!groups.has(magic)) groups.set(magic, []);
    groups.get(magic).push(operation);
  }
  const magics = [...groups.keys()].sort(
    (left, right) => left.localeCompare(right, undefined, { numeric: true }),
  );
  const rows = [];
  for (const magic of magics) {
    const list = groups.get(magic);
    rows.push(groupRow(magic, list));
    rows.push(...list.map(operationRow));
  }
  return rows;
}

function groupRow(magic, operations) {
  const row = document.createElement("tr");
  row.className = "group-row";
  const labelCell = document.createElement("td");
  labelCell.colSpan = 7;
  const label = document.createElement("strong");
  label.className = "group-magic";
  label.textContent = `Bot · Magic ${magic}`;
  const count = document.createElement("span");
  count.className = "group-count";
  count.textContent = `${operations.length} operación${operations.length === 1 ? "" : "es"}`;
  labelCell.append(label, count);
  const profitSum = operations.reduce(
    (total, operation) => total + (Number.isFinite(operation.floating_profit) ? operation.floating_profit : 0),
    0,
  );
  row.setAttribute("aria-label", `Bot Magic ${magic}: ${operations.length} operación${operations.length === 1 ? "" : "es"}, P&L ${money(profitSum, latestCurrency, true)}`);
  const profitCell = document.createElement("td");
  profitCell.className = "numeric operation-profit";
  if (profitSum > 0) profitCell.classList.add("positive");
  else if (profitSum < 0) profitCell.classList.add("negative");
  profitCell.textContent = money(profitSum, latestCurrency, true);
  const timeCell = document.createElement("td");
  row.append(labelCell, profitCell, timeCell);
  return row;
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
  if (openedAt) {
    const ageSeconds = Math.max(0, (Date.now() - openedAt.getTime()) / 1000);
    row.appendChild(detailCell(dateTimeFormatter.format(openedAt), `hace ${elapsed(ageSeconds)}`));
  } else {
    row.appendChild(textCell("—"));
  }
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
    balanceReference.hidden = true;
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
  const referenceY = 295 - ((history[0].balance - low) / (high - low)) * 270;
  balanceReference.setAttribute("y1", String(referenceY));
  balanceReference.setAttribute("y2", String(referenceY));
  balanceReference.hidden = false;
  chartHigh.textContent = `Máx ${money(maximum, latestCurrency)}`;
  chartLow.textContent = `Mín ${money(minimum, latestCurrency)}`;
  chartStart.textContent = startAt ? timeFormatter.format(startAt) : "";
  chartEnd.textContent = endAt ? timeFormatter.format(endAt) : "";
  const spanSeconds = startAt && endAt
    ? Math.max(0, (endAt.getTime() - startAt.getTime()) / 1000)
    : Math.max(0, (history.length - 1) * intervalSeconds);
  const span = elapsed(spanSeconds);
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

let retryMultiplier = 1;

async function refresh() {
  if (document.hidden) return;
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    2 * latestIntervalSeconds * 1000,
  );
  try {
    const query = lastPollSince ? `?since=${encodeURIComponent(lastPollSince)}` : "";
    const response = await fetch(`/api/state${query}`, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderState(await response.json());
    retryMultiplier = 1;
  } catch (_) {
    setText(elements.status, "Sin conexión local");
    statusDot.className = "status-dot degraded";
    elements.freshness.classList.add("stale");
    setText(errorHuman, "No se pudo consultar el servicio local.");
    errorTechnicalDetails.hidden = true;
    errorBox.hidden = false;
    retryMultiplier = Math.min(retryMultiplier * 2, 6);
  } finally {
    window.clearTimeout(timeout);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});

drawGrid();
function activateView(view) {
  document.querySelectorAll(".view-tab").forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".dashboard-view").forEach((panel) => {
    panel.hidden = panel.id !== `${view}-view`;
  });
  activeView = view;
  if (activeView === "operations") renderOperations();
  else if (activeView === "activity") renderActivity();
  else renderChart(lastHistory, latestIntervalSeconds);
}

document.querySelectorAll(".view-tab").forEach((button) => {
  button.addEventListener("click", () => {
    activateView(button.dataset.view);
    history.replaceState(null, "", `#${button.dataset.view}`);
  });
  button.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll(".view-tab")];
    const index = tabs.indexOf(button);
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(index + direction + tabs.length) % tabs.length];
    next.focus();
    next.click();
  });
});

window.addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (["overview", "operations", "activity"].includes(view)) activateView(view);
});
const FILTER_STORE = "tradinglab-dashboard-filters";

function loadStoredFilters() {
  try {
    const stored = JSON.parse(localStorage.getItem(FILTER_STORE) || "{}");
    magicFilter.value = stored.magic || "";
    activityElements.magicFilter.value = stored.activityMagic || "";
    activityElements.kindFilter.value = stored.activityKind || "";
    activityElements.resultFilter.value = stored.activityResult || "";
    groupByBotInput.checked = Boolean(stored.groupByBot);
  } catch (_) {
    // almacenamiento no disponible
  }
}

function saveStoredFilters() {
  try {
    localStorage.setItem(FILTER_STORE, JSON.stringify({
      magic: magicFilter.value,
      activityMagic: activityElements.magicFilter.value,
      activityKind: activityElements.kindFilter.value,
      activityResult: activityElements.resultFilter.value,
      groupByBot: groupByBotInput.checked,
    }));
  } catch (_) {
    // almacenamiento no disponible
  }
}

magicFilter.addEventListener("input", () => { renderOperations(); saveStoredFilters(); });
groupByBotInput.addEventListener("change", () => { renderOperations(); saveStoredFilters(); });
clearFilter.addEventListener("click", () => {
  magicFilter.value = "";
  magicFilter.focus();
  renderOperations();
  saveStoredFilters();
});
activityElements.magicFilter.addEventListener("input", () => { renderActivity(); saveStoredFilters(); });
activityElements.kindFilter.addEventListener("change", () => { renderActivity(); saveStoredFilters(); });
activityElements.resultFilter.addEventListener("change", () => { renderActivity(); saveStoredFilters(); });
activityElements.clearFilter.addEventListener("click", () => {
  activityElements.magicFilter.value = "";
  activityElements.kindFilter.value = "";
  activityElements.resultFilter.value = "";
  activityElements.magicFilter.focus();
  renderActivity();
  saveStoredFilters();
});
function scheduleRefresh() {
  window.setTimeout(() => {
    refresh().finally(scheduleRefresh);
  }, latestIntervalSeconds * 1000 * retryMultiplier);
}

loadStoredFilters();
const initialView = location.hash.slice(1);
if (["overview", "operations", "activity"].includes(initialView)) {
  history.replaceState(null, "", `#${initialView}`);
  activateView(initialView);
}
refresh().finally(scheduleRefresh);
