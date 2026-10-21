"use strict";

const ids = [
  "status", "freshness", "account-identity", "balance",
  "equity", "profit-line", "margin-free", "margin-level", "positions", "orders", "margin", "last-reading"
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const statusDot = document.getElementById("status-dot");
const metricsPanel = document.querySelector(".metrics");
const sourceDescription = document.getElementById("source-description");
const operationsNote = document.getElementById("operations-note");
const errorHuman = document.getElementById("error-human");
const errorTechnical = document.getElementById("error-technical");
const errorTechnicalDetails = document.getElementById("error-technical-details");
const plainSummary = document.getElementById("plain-summary");
const errorBox = document.getElementById("error");
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
const kindFilter = document.getElementById("kind-filter");
const modeNotice = document.getElementById("mode-notice");
const operationsBody = document.getElementById("operations-body");
const operationsEmpty = document.getElementById("operations-empty");
const operationsBadge = document.getElementById("operations-badge");
const visibleOperations = document.getElementById("visible-operations");
const visiblePositions = document.getElementById("visible-positions");
const visibleOrders = document.getElementById("visible-orders");
const clearFilter = document.getElementById("clear-filter");
const healthOverview = document.getElementById("health-overview");
let latestOperations = [];
let latestOperationsTotal = 0;
let latestOperationsTruncated = false;
let latestCurrency = "USD";
let latestActivity = [];
let latestIntervalSeconds = 5;
let lastObservedAt = null;
let latestOperationsSignature = "";
let latestMagicKey = "";
let activeView = "overview";
let lastHistory = [];
let telemetryMode = false;
let lastPollSince = null;
let latestObservedDate = null;
let serviceReachable = true;
let latestStatus = "starting";
let currentFilterScope = "uninitialized";
let refreshInFlight = null;
let latestHealthState = null;
const operationNodes = new Map();
const expandedOperationTickets = new Set();

const activityElements = {
  badge: document.getElementById("activity-badge"),
  content: document.getElementById("activity-content"),
};

const captureElements = {
  health: document.getElementById("capture-health"),
  lastSuccess: document.getElementById("capture-last-success"),
  streak: document.getElementById("capture-streak"),
  attempts: document.getElementById("capture-attempts"),
  results: document.getElementById("capture-results"),
};

const sourceHealthElements = {
  label: document.getElementById("source-health-label"),
  id: document.getElementById("source-health-id"),
  version: document.getElementById("source-health-version"),
  checked: document.getElementById("source-health-checked"),
};

const receiverElements = {
  summary: document.getElementById("receiver-summary"),
  accepted: document.getElementById("rc-accepted"),
  duplicates: document.getElementById("rc-duplicates"),
  gaps: document.getElementById("rc-gaps"),
  retained: document.getElementById("rc-retained"),
  sessions: document.getElementById("rc-sessions"),
  history: document.getElementById("rc-history"),
};

const HISTORY_STATUS_LABELS = {
  complete: "Completo",
  truncated: "Truncado",
  error: "Con error",
  unavailable: "Sin datos",
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

const SOURCE_LABELS = {
  demo: "Demo local · datos simulados",
  "mt5-telemetry": "MT5 · telemetría",
  mt5: "MT5 · lectura directa",
};

function sourceLabel(source) {
  return SOURCE_LABELS[source] || "Fuente local";
}

function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

function toDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function renderSummary(value, currency, status) {
  const plural = (count, singular, pluralForm) => `${count} ${count === 1 ? singular : pluralForm}`;
  const positions = plural(value.open_positions || 0, "posición abierta", "posiciones abiertas");
  const orders = plural(value.active_orders || 0, "orden activa", "órdenes activas");
  const profit = money(value.floating_profit || 0, currency, true);
  const capturePhrase = status === "connected" ? "" : " · captura degradada, los datos pueden estar atrasados";
  setText(plainSummary, `${sourceLabel(value.source)} · ${positions} · ${orders} · resultado abierto ${profit} · métricas de riesgo pendientes de contrato${capturePhrase}`);
}

function renderState(state) {
  latestHealthState = state;
  latestStatus = state.status;
  setText(elements.status, statusLabels[state.status] || "Lectura degradada");
  statusDot.className = `status-dot ${state.status}`;
  const errorText = state.error || "";
  if (errorText) {
    setText(errorHuman, "No pudimos leer la fuente de datos. Se conserva la última muestra válida.");
    setText(errorTechnical, errorText);
    errorTechnicalDetails.hidden = false;
  }
  errorBox.hidden = !errorText;
  renderCapture(state);
  renderSourceHealth(state);
  renderHealthOverview(state);
  if (!state.latest) {
    if (activeView === "operations") renderOperations();
    updateFreshness();
    return;
  }

  const value = state.latest;
  latestIntervalSeconds = state.interval_seconds || 5;
  const observedAt = toDate(value.observed_at);
  latestObservedDate = observedAt;
  updateFreshness();
  const currency = value.currency || "USD";
  renderSummary(value, currency, state.status);
  const health = state.source_health || {};
  const filterScope = health.source_id || value.source || "local";
  if (filterScope !== currentFilterScope) loadStoredFilters(filterScope);
  if (value.observed_at === lastObservedAt) return;
  lastObservedAt = value.observed_at;
  lastPollSince = value.observed_at;
  latestCurrency = currency;
  telemetryMode = value.source === "mt5-telemetry";
  modeNotice.hidden = value.source !== "demo";
  elements["account-identity"].textContent = value.account_reference && value.server
    ? `Cuenta ${value.account_reference} · ${value.server} · ${currency}`
    : "Cuenta sin identificar";
  elements.balance.textContent = money(value.balance, currency);
  elements.equity.textContent = money(value.equity, currency);
  const profitWord = value.floating_profit > 0 ? "ganancia" : value.floating_profit < 0 ? "pérdida" : "sin resultado";
  setText(elements["profit-line"], `Resultado abierto: ${money(value.floating_profit || 0, currency, true)} (${profitWord})`);
  elements["profit-line"].className = value.floating_profit > 0
    ? "profit-line positive-text"
    : value.floating_profit < 0 ? "profit-line negative-text" : "profit-line";
  elements["margin-free"].textContent = money(value.margin_free, currency);
  elements["margin-level"].textContent = value.margin_level === null
    ? "—"
    : `${number(value.margin_level)} %`;
  elements.positions.textContent = number(value.open_positions);
  elements.orders.textContent = number(value.active_orders);
  elements.margin.textContent = money(value.margin, currency);
  setText(elements["last-reading"], observedAt ? timeFormatter.format(observedAt) : "—");
  setText(sourceDescription, sourceLabel(value.source));
  latestOperations = Array.isArray(value.operations) ? value.operations : [];
  latestOperationsTotal = Math.max(
    latestOperations.length,
    Number(value.open_positions || 0) + Number(value.active_orders || 0),
  );
  latestOperationsTruncated = value.operations_truncated === true;
  operationsBadge.textContent = number(latestOperationsTotal);
  if (activeView === "operations") renderOperations();
  const nextActivity = Array.isArray(value.recent_activity) ? value.recent_activity : [];
  latestActivity = nextActivity;
  activityElements.badge.textContent = number(latestActivity.length);
  activityElements.badge.hidden = telemetryMode || latestActivity.length === 0;
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
  const lastSuccessAt = capture.last_success_at ? toDate(capture.last_success_at) : null;
  setText(captureElements.lastSuccess, lastSuccessAt ? timeFormatter.format(lastSuccessAt) : "—");
  setText(captureElements.streak, failures === 0 ? "Sin fallos" : number(failures));
  captureElements.streak.className = failures === 0 ? "" : "negative-text";
  setText(captureElements.attempts, number(capture.attempt_count || 0));
  const duration = Number.isFinite(capture.last_duration_ms) ? `${number(capture.last_duration_ms)} ms` : "—";
  const maxDuration = Number.isFinite(capture.max_duration_ms) ? `${number(capture.max_duration_ms)} ms` : "—";
  setText(captureElements.results, `${number(capture.success_count || 0)} éxitos · ${number(capture.failure_count || 0)} fallos · duración última ${duration} · máxima ${maxDuration}`);
}

function renderHealthOverview(state) {
  const health = state.source_health || {};
  const receiver = health.receiver || {};
  const hasObservations = receiver.missing_sequences > 0
    || receiver.history_status === "truncated"
    || receiver.history_status === "error";
  let message = "Comprobando la fuente de datos…";
  let tone = "";
  if (state.status === "connected" && health.availability === "available" && !hasObservations) {
    message = "La cuenta está actualizada y el receptor local no informa problemas.";
    tone = "positive";
  } else if (state.status === "connected" && health.availability === "not_applicable") {
    message = "Los datos de demostración están actualizados.";
    tone = "positive";
  } else if (state.status === "connected" && health.availability === "unavailable") {
    message = "La cuenta está actualizada, pero no se pudo consultar el diagnóstico del receptor.";
    tone = "warning";
  } else if (state.status === "connected" && hasObservations) {
    message = "La cuenta está actualizada, pero la fuente requiere revisión.";
    tone = "warning";
  } else if (state.status === "degraded") {
    message = "La lectura está degradada. Se muestran los últimos datos válidos.";
    tone = "warning";
  }
  const outdated = state.latest && toDate(state.latest.observed_at)
    && Date.now() - toDate(state.latest.observed_at).getTime() > 2 * latestIntervalSeconds * 1000;
  if (!serviceReachable || outdated) {
    message = !serviceReachable
      ? "Sin conexión con el servicio local. No se están recibiendo datos nuevos."
      : "La última lectura está atrasada. Los valores visibles no representan el estado actual de la cuenta.";
    tone = "warning";
  }
  setText(healthOverview, message);
  healthOverview.className = `health-overview ${tone}`.trim();
}

function renderSourceHealth(state) {
  const health = state.source_health || {};
  const label = state.latest ? sourceLabel(state.latest.source) : "Fuente local";
  setText(sourceHealthElements.label, label);
  const availability = health.availability;
  if (availability === "available" && health.receiver) {
    const receiver = health.receiver;
    setText(sourceHealthElements.id, health.source_id ? `Identificador: ${health.source_id}` : "");
    setText(sourceHealthElements.version, health.collector_version
      ? `Colector: ${health.collector_version}`
      : "Colector: no informado todavía");
    const checkedAt = health.checked_at ? toDate(health.checked_at) : null;
    setText(sourceHealthElements.checked, checkedAt
      ? `Última verificación: ${timeFormatter.format(checkedAt)}`
      : "");
    const observations = [];
    if (receiver.missing_sequences > 0) {
      observations.push(`${number(receiver.missing_sequences)} secuencias faltantes`);
    }
    if (receiver.history_status === "truncated" || receiver.history_status === "error") {
      observations.push("historial incompleto");
    }
    setText(receiverElements.summary, observations.length
      ? `Receptor local con observaciones: ${observations.join(" y ")}.`
      : receiver.accepted === 0
        ? "El receptor está disponible pero todavía no recibió mensajes."
        : "Receptor local disponible y sin observaciones.");
    receiverElements.summary.className = observations.length ? "health-summary warn-text" : "health-summary";
    receiverElements.summary.title = health.error || "";
    setText(receiverElements.accepted, number(receiver.accepted));
    setText(receiverElements.duplicates, number(receiver.duplicates));
    setText(receiverElements.gaps, number(receiver.missing_sequences));
    receiverElements.gaps.className = receiver.missing_sequences > 0 ? "warn-text" : "";
    setText(receiverElements.retained, number(receiver.retained));
    setText(receiverElements.sessions, number(receiver.retained_sessions));
    setText(receiverElements.history, HISTORY_STATUS_LABELS[receiver.history_status] || receiver.history_status);
    receiverElements.history.className = receiver.history_status === "truncated" || receiver.history_status === "error"
      ? "warn-text"
      : "";
    return;
  }
  if (availability === "unavailable") {
    setText(sourceHealthElements.id, health.source_id ? `Identificador: ${health.source_id}` : "");
    setText(sourceHealthElements.version, health.collector_version
      ? `Colector: ${health.collector_version}`
      : "Colector: no informado todavía");
    setText(sourceHealthElements.checked, "");
    setText(receiverElements.summary, "No pudimos consultar el estado del receptor.");
    receiverElements.summary.className = "health-summary warn-text";
    receiverElements.summary.title = health.error || "";
  } else {
    setText(sourceHealthElements.id, "Sin receptor de telemetría: esta fuente no aplica.");
    setText(sourceHealthElements.version, "");
    setText(sourceHealthElements.checked, "");
    setText(receiverElements.summary, "La salud del receptor no aplica para esta fuente.");
    receiverElements.summary.className = "health-summary";
    receiverElements.summary.title = "";
  }
  ["accepted", "duplicates", "gaps", "retained", "sessions", "history"].forEach((key) => {
    setText(receiverElements[key], "—");
    receiverElements[key].className = "";
  });
}

function renderActivity() {
  if (!latestObservedDate) return;
  activityElements.content.replaceChildren(...buildActivityContent(latestActivity));
}

function buildActivityContent(events) {
  if (telemetryMode) {
    const block = document.createElement("div");
    block.className = "activity-info";
    const text = document.createElement("p");
    text.textContent = "Todavía no mostramos operaciones cerradas en la telemetría. Estamos validando la zona horaria del servidor de MetaTrader 5 y los resultados antes de publicarlos.";
    const link = document.createElement("a");
    link.href = "#operations";
    link.textContent = "Ver operaciones abiertas";
    block.append(text, link);
    return [block];
  }
  if (events.length === 0) {
    const empty = document.createElement("p");
    empty.className = "operations-empty";
    empty.textContent = "Esta fuente no informa actividad reciente en esta versión.";
    return [empty];
  }
  const nodes = [];
  const chip = document.createElement("p");
  chip.className = "activity-demo-chip";
  chip.textContent = "Datos de demostración: los eventos son sintéticos y sirven para validar la interfaz.";
  nodes.push(chip);
  const table = document.createElement("table");
  table.setAttribute("role", "table");
  table.className = "operations-table activity-table";
  const caption = document.createElement("caption");
  caption.className = "sr-only";
  caption.textContent = "Actividad reciente informada por la fuente";
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  ["Hora", "Evento", "Instrumento", "Magic", "Resultado"].forEach((label, index) => {
    const th = document.createElement("th");
    th.setAttribute("scope", "col");
    if (index === 4) th.className = "numeric";
    th.textContent = label;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  const tbody = document.createElement("tbody");
  events.forEach((activity) => {
    const row = document.createElement("tr");
    const occurredAt = toDate(activity.occurred_at);
    row.appendChild(textCell(occurredAt ? dateTimeFormatter.format(occurredAt) : "—", "", "Hora"));
    const eventName = activityTypes[activity.event_type] || activity.event_type.replaceAll("_", " ");
    const stateName = activity.event_state ? activityStates[activity.event_state] || activity.event_state : "";
    row.appendChild(textCell(stateName ? `${eventName} · ${stateName}` : eventName, "", "Evento"));
    row.appendChild(textCell(activity.symbol, "", "Instrumento"));
    row.appendChild(textCell(String(activity.magic_number), "", "Magic"));
    const profitCell = document.createElement("td");
    profitCell.className = "numeric";
    profitCell.setAttribute("data-label", "Resultado");
    if (Number.isFinite(activity.profit)) {
      profitCell.textContent = money(activity.profit, latestCurrency, true);
      if (activity.profit > 0) profitCell.classList.add("positive-text");
      else if (activity.profit < 0) profitCell.classList.add("negative-text");
    } else {
      profitCell.textContent = "—";
    }
    row.appendChild(profitCell);
    tbody.appendChild(row);
  });
  table.append(caption, thead, tbody);
  nodes.push(table);
  return nodes;
}

function elapsed(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

function updateFreshness() {
  if (latestHealthState) renderHealthOverview(latestHealthState);
  if (!latestObservedDate) {
    setText(elements.freshness, serviceReachable ? "Esperando primera captura" : "Sin una lectura válida todavía");
    return;
  }
  const ageSeconds = Math.max(0, (Date.now() - latestObservedDate.getTime()) / 1000);
  const staleData = !serviceReachable || latestStatus !== "connected" || ageSeconds > 2 * latestIntervalSeconds;
  const criticalAge = !serviceReachable || ageSeconds > 10 * latestIntervalSeconds;
  setText(
    elements.freshness,
    serviceReachable
      ? `Actualizado hace ${elapsed(ageSeconds)}`
      : `Última lectura válida hace ${elapsed(ageSeconds)}`,
  );
  elements.freshness.title = `Última lectura ${timeFormatter.format(latestObservedDate)}`;
  elements.freshness.classList.toggle("aged", staleData && !criticalAge);
  elements.freshness.classList.toggle("stale", criticalAge);
  metricsPanel.classList.toggle("stale", staleData);
  if (staleData && latestStatus === "connected") {
    setText(elements.status, serviceReachable ? "Datos desactualizados" : "Sin conexión local");
    statusDot.className = "status-dot degraded";
  }
}

function renderOperations() {
  if (!latestObservedDate) {
    operationsEmpty.hidden = false;
    operationsEmpty.textContent = serviceReachable
      ? "Esperando la primera lectura de operaciones…"
      : "No hay una lectura disponible. El servicio local volverá a intentar la conexión.";
    return;
  }
  const filter = magicFilter.value.trim();
  const kind = kindFilter.value;
  const currentOperationKeys = new Set(
    latestOperations.map((operation) => `${operation.kind}-${operation.ticket}`),
  );
  for (const ticket of expandedOperationTickets) {
    if (!currentOperationKeys.has(ticket)) expandedOperationTickets.delete(ticket);
  }
  const signature = `${latestCurrency}|${filter}|${kind}|${latestOperationsTotal}|${latestOperationsTruncated}|${JSON.stringify(latestOperations)}`;
  if (signature === latestOperationsSignature) return;
  latestOperationsSignature = signature;
  const filtered = latestOperations.filter((operation) => (
    (!filter || String(operation.magic_number) === filter)
    && (kind === "all" || operation.kind === kind)
  ));
  updateMagicOptions(filter);
  reconcileOperations(filtered);
  operationsEmpty.hidden = filtered.length > 0;
  operationsEmpty.textContent = latestOperations.length === 0
    ? latestOperationsTruncated
      ? "La fuente informa operaciones abiertas, pero no incluyó su detalle."
      : "La fuente no informa operaciones abiertas."
    : "Ninguna operación coincide con los filtros elegidos.";
  operationsNote.hidden = !(telemetryMode && (latestOperations.length > 0 || latestOperationsTruncated));
  operationsNote.textContent = latestOperationsTruncated
    ? `La fuente informa ${number(latestOperationsTotal)} operaciones abiertas y envió el detalle de ${number(latestOperations.length)}. Los filtros solo abarcan el detalle recibido. La hora de cada operación todavía no está validada.`
    : "La hora de cada operación todavía no está validada. El indicador de actualización corresponde a la captura de la cuenta.";
  visibleOperations.textContent = latestOperationsTruncated
    ? `${number(filtered.length)} de ${number(latestOperationsTotal)}`
    : filter || kind !== "all"
    ? `${number(filtered.length)} de ${number(latestOperations.length)}`
    : number(filtered.length);
  visiblePositions.textContent = number(filtered.filter((item) => item.kind === "position").length);
  visibleOrders.textContent = number(filtered.filter((item) => item.kind === "order").length);
  clearFilter.disabled = !filter && kind === "all";
}

function updateMagicOptions(selected = "") {
  const numbers = [...new Set(latestOperations.map((item) => String(item.magic_number)))];
  numbers.sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  const missing = selected && !numbers.includes(selected);
  if (missing) numbers.push(selected);
  const key = JSON.stringify([numbers, selected, Boolean(missing)]);
  if (key === latestMagicKey) return;
  latestMagicKey = key;
  magicFilter.replaceChildren(...["", ...numbers].map((magic) => {
    const option = document.createElement("option");
    option.value = magic;
    option.textContent = !magic ? "Todos los bots"
      : magic === selected && missing ? `${magic} · sin operaciones` : magic;
    return option;
  }));
  magicFilter.value = selected;
}

// Conserva los nodos y sus listeners: una captura no debe quitar el foco ni cerrar detalles.
function syncOperationNode(current, next) {
  if (current.nodeType === Node.TEXT_NODE) {
    if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
    return;
  }
  for (const attribute of [...current.attributes]) {
    if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
  }
  for (const attribute of next.attributes) {
    if (current.getAttribute(attribute.name) !== attribute.value) {
      current.setAttribute(attribute.name, attribute.value);
    }
  }
  const children = [...next.childNodes];
  children.forEach((child, index) => {
    const existing = current.childNodes[index];
    if (!existing) current.appendChild(child);
    else if (existing.nodeType !== child.nodeType || existing.nodeName !== child.nodeName) {
      current.replaceChild(child, existing);
    } else syncOperationNode(existing, child);
  });
  while (current.childNodes.length > children.length) current.lastChild.remove();
}

function reconcileOperations(operations) {
  const focused = operationsBody.contains(document.activeElement) ? document.activeElement : null;
  const visibleKeys = new Set(operations.map((item) => `${item.kind}-${item.ticket}`));
  for (const [key, nodes] of operationNodes) {
    if (!visibleKeys.has(key)) {
      if (nodes.some((node) => node.contains(document.activeElement))) magicFilter.focus();
      nodes.forEach((node) => node.remove());
      operationNodes.delete(key);
    }
  }
  let cursor = operationsBody.firstChild;
  for (const operation of operations) {
    const key = `${operation.kind}-${operation.ticket}`;
    const next = operationRow(operation);
    let nodes = operationNodes.get(key);
    if (nodes) nodes.forEach((node, index) => syncOperationNode(node, next[index]));
    else { nodes = next; operationNodes.set(key, nodes); }
    for (const node of nodes) {
      if (node !== cursor) operationsBody.insertBefore(node, cursor);
      cursor = node.nextSibling;
    }
  }
  if (focused?.isConnected && document.activeElement !== focused) focused.focus({ preventScroll: true });
}

function operationRow(operation) {
  const ticket = String(operation.ticket);
  const operationKey = `${operation.kind}-${ticket}`;
  const row = document.createElement("tr");
  row.setAttribute("role", "row");
  const kind = operation.kind === "position" ? "Posición" : "Orden";
  const kindCell = document.createElement("td");
  kindCell.setAttribute("data-label", "Operación");
  const badge = document.createElement("span");
  badge.className = `operation-kind ${operation.kind}`;
  badge.textContent = kind;
  kindCell.appendChild(badge);
  const typeText = document.createElement("small");
  typeText.className = "cell-detail-text";
  typeText.textContent = operationTypes[operation.operation_type] || operation.operation_type;
  kindCell.appendChild(typeText);
  row.appendChild(kindCell);
  const operationContext = `Magic ${operation.magic_number}`;
  row.appendChild(detailCell(operation.symbol, operationContext, "", "Instrumento"));
  row.appendChild(textCell(decimal(operation.volume), "numeric", "Volumen"));

  const openedAt = operation.opened_at ? toDate(operation.opened_at) : null;
  const profit = document.createElement("td");
  profit.className = "numeric operation-profit";
  profit.setAttribute("data-label", "Resultado abierto");
  if (operation.kind === "position" && Number.isFinite(operation.floating_profit)) {
    profit.textContent = money(operation.floating_profit, latestCurrency, true);
    if (operation.floating_profit > 0) profit.classList.add("positive");
    else if (operation.floating_profit < 0) profit.classList.add("negative");
  } else if (operation.kind === "order") {
    profit.textContent = "No aplica";
    profit.classList.add("na");
  } else {
    profit.textContent = "—";
  }
  row.appendChild(profit);
  row.appendChild(textCell(
    openedAt ? dateTimeFormatter.format(openedAt) : "No informada",
    "",
    "Hora",
  ));

  const detailRow = document.createElement("tr");
  detailRow.className = "detail-row";
  detailRow.id = `operation-detail-${operationKey}`;
  detailRow.hidden = !expandedOperationTickets.has(operationKey);
  const detailCellEl = document.createElement("td");
  detailCellEl.colSpan = 6;
  const list = document.createElement("dl");
  const addDetail = (term, value) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    list.append(dt, dd);
  };
  addDetail("Ticket", `#${operation.ticket}`);
  addDetail("Magic", String(operation.magic_number));
  addDetail("Precio de apertura", price(operation.price_open));
  addDetail("Precio actual", price(operation.price_current));
  addDetail("Stop loss", price(operation.stop_loss));
  addDetail("Take profit", price(operation.take_profit));
  addDetail("Comentario", operation.comment || "Sin comentario");
  addDetail("Hora", openedAt
    ? dateTimeFormatter.format(openedAt)
    : "La fuente todavía no expone una hora validada.");
  detailCellEl.appendChild(list);
  detailRow.appendChild(detailCellEl);

  const buttonCell = document.createElement("td");
  buttonCell.setAttribute("data-label", "");
  const button = document.createElement("button");
  button.className = "detail-toggle";
  button.type = "button";
  button.dataset.operationTicket = operationKey;
  button.setAttribute("aria-label", `Detalle de ${operation.symbol}, ${kind.toLowerCase()} ${ticket}`);
  button.setAttribute("aria-controls", detailRow.id);
  button.setAttribute("aria-expanded", String(!detailRow.hidden));
  button.textContent = detailRow.hidden ? "Ver detalle" : "Ocultar detalle";
  button.addEventListener("click", () => {
    const expanded = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!expanded));
    button.textContent = expanded ? "Ver detalle" : "Ocultar detalle";
    detailRow.hidden = expanded;
    if (expanded) expandedOperationTickets.delete(operationKey);
    else expandedOperationTickets.add(operationKey);
  });
  buttonCell.appendChild(button);
  row.appendChild(buttonCell);
  detailRow.setAttribute("role", "row");
  [...row.children, ...detailRow.children].forEach((cell) => cell.setAttribute("role", "cell"));
  return [row, detailRow];
}

function textCell(value, className = "", dataLabel = "") {
  const cell = document.createElement("td");
  cell.className = className;
  if (dataLabel) cell.setAttribute("data-label", dataLabel);
  cell.textContent = value;
  return cell;
}

function detailCell(primary, secondary, className = "", dataLabel = "") {
  const cell = document.createElement("td");
  cell.className = `cell-detail ${className}`.trim();
  if (dataLabel) cell.setAttribute("data-label", dataLabel);
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
  const timeline = history
    .map((item) => ({ ...item, at: toDate(item.observed_at) }))
    .filter((item) => item.at && Number.isFinite(item.balance) && Number.isFinite(item.equity))
    .sort((left, right) => left.at - right.at);
  if (timeline.length < 2) {
    chartEmpty.hidden = false;
    balanceLine.setAttribute("d", "");
    equityLine.setAttribute("d", "");
    balanceReference.classList.add("is-hidden");
    chart.setAttribute("aria-label", "Evolución reciente de balance y equity");
    clearLabels();
    return;
  }
  chartEmpty.hidden = true;
  let minimum = Infinity;
  let maximum = -Infinity;
  for (const item of timeline) {
    minimum = Math.min(minimum, item.balance, item.equity);
    maximum = Math.max(maximum, item.balance, item.equity);
  }
  const padding = Math.max((maximum - minimum) * 0.15, Math.abs(maximum) * 0.0001, 1);
  const low = minimum - padding;
  const high = maximum + padding;
  const startAt = timeline[0].at;
  const endAt = timeline[timeline.length - 1].at;
  const timeRange = Math.max(1, endAt.getTime() - startAt.getTime());
  const gapThreshold = intervalSeconds * 2.5 * 1000;
  let gaps = 0;
  const toPath = (key) => timeline.map((item, index) => {
    const x = 25 + ((item.at.getTime() - startAt.getTime()) / timeRange) * 950;
    const y = 295 - ((item[key] - low) / (high - low)) * 270;
    const followsGap = index > 0 && item.at.getTime() - timeline[index - 1].at.getTime() > gapThreshold;
    if (key === "balance" && followsGap) gaps += 1;
    return `${index === 0 || followsGap ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  balanceLine.setAttribute("d", toPath("balance"));
  equityLine.setAttribute("d", toPath("equity"));
  const referenceY = 295 - ((timeline[0].balance - low) / (high - low)) * 270;
  balanceReference.setAttribute("y1", String(referenceY));
  balanceReference.setAttribute("y2", String(referenceY));
  balanceReference.classList.remove("is-hidden");
  chartHigh.textContent = `Máx ${money(maximum, latestCurrency)}`;
  chartLow.textContent = `Mín ${money(minimum, latestCurrency)}`;
  chartStart.textContent = timeFormatter.format(startAt);
  chartEnd.textContent = timeFormatter.format(endAt);
  const spanSeconds = Math.max(0, timeRange / 1000);
  const span = elapsed(spanSeconds);
  chartSpan.textContent = gaps ? `Ventana ${span} · ${gaps} ${gaps === 1 ? "interrupción" : "interrupciones"}` : `Ventana ${span}`;
  chart.setAttribute(
    "aria-label",
    `Evolución de balance y equity, ventana ${span}${gaps ? `, ${gaps} interrupciones de captura` : ""}`,
  );
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

async function performRefresh() {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    2 * latestIntervalSeconds * 1000,
  );
  try {
    const query = lastPollSince ? `?since=${encodeURIComponent(lastPollSince)}` : "";
    const response = await fetch(`/api/state${query}`, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    serviceReachable = true;
    renderState(await response.json());
    retryMultiplier = 1;
  } catch (_) {
    serviceReachable = false;
    setText(elements.status, "Sin conexión local");
    statusDot.className = "status-dot degraded";
    updateFreshness();
    if (activeView === "operations") renderOperations();
    setText(errorHuman, "No se pudo consultar el servicio local.");
    errorTechnicalDetails.hidden = true;
    errorBox.hidden = false;
    setText(healthOverview, latestObservedDate
      ? "No se puede consultar el servicio local. Se muestran los últimos datos válidos."
      : "No se puede consultar el servicio local. Todavía no hay datos para mostrar.");
    healthOverview.className = "health-overview warning";
    retryMultiplier = Math.min(retryMultiplier * 2, 6);
  } finally {
    window.clearTimeout(timeout);
  }
}

function refresh() {
  if (document.hidden) return Promise.resolve();
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = performRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});

drawGrid();
window.setInterval(updateFreshness, 1000);
function activateView(view) {
  const titles = { overview: "Resumen", operations: "Operaciones", activity: "Actividad" };
  setText(document.getElementById("page-title"), titles[view]);
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
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll(".view-tab")];
    const index = tabs.indexOf(button);
    const direction = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
    const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1]
      : tabs[(index + direction + tabs.length) % tabs.length];
    next.focus();
    next.click();
  });
});

window.addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (["overview", "operations", "activity"].includes(view)) activateView(view);
});
const FILTER_STORE = "tradinglab-dashboard-filters";

function loadStoredFilters(scope) {
  currentFilterScope = scope;
  expandedOperationTickets.clear();
  lastObservedAt = null;
  try {
    const stored = JSON.parse(localStorage.getItem(FILTER_STORE) || "{}");
    const selected = stored.scopes?.[scope] || {};
    updateMagicOptions(typeof selected.magic === "string" ? selected.magic : "");
    kindFilter.value = ["all", "position", "order"].includes(selected.kind)
      ? selected.kind
      : "all";
  } catch (_) {
    magicFilter.value = "";
    kindFilter.value = "all";
  }
  latestOperationsSignature = "";
}

function saveStoredFilters() {
  try {
    const stored = JSON.parse(localStorage.getItem(FILTER_STORE) || "{}");
    const scopes = stored.scopes && typeof stored.scopes === "object" ? stored.scopes : {};
    scopes[currentFilterScope] = { magic: magicFilter.value, kind: kindFilter.value };
    localStorage.setItem(FILTER_STORE, JSON.stringify({ scopes }));
  } catch (_) {
    // almacenamiento no disponible
  }
}

magicFilter.addEventListener("change", () => { renderOperations(); saveStoredFilters(); });
kindFilter.addEventListener("change", () => { renderOperations(); saveStoredFilters(); });
clearFilter.addEventListener("click", () => {
  magicFilter.value = "";
  kindFilter.value = "all";
  magicFilter.focus();
  renderOperations();
  saveStoredFilters();
});
function scheduleRefresh() {
  window.setTimeout(() => {
    refresh().finally(scheduleRefresh);
  }, latestIntervalSeconds * 1000 * retryMultiplier);
}

const initialView = location.hash.slice(1);
if (["overview", "operations", "activity"].includes(initialView)) {
  history.replaceState(null, "", `#${initialView}`);
  activateView(initialView);
}
refresh().finally(scheduleRefresh);
