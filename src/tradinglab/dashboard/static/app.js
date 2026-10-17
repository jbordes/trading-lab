"use strict";

const ids = [
  "status", "freshness", "account-identity", "balance",
  "equity", "profit-line", "margin-free", "margin-level", "positions", "orders", "margin", "last-reading"
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const statusDot = document.getElementById("status-dot");
const metricsPanel = document.querySelector(".metrics");
const equityCard = document.getElementById("equity-card");
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
let latestIntervalSeconds = 5;
let lastObservedAt = null;
let latestOperationsSignature = "";
let latestMagicKey = "";
let activeView = "overview";
let lastHistory = [];
let telemetryMode = false;
let lastPollSince = null;

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
    ? `Actualizado hace ${elapsed(ageSeconds)}`
    : "sin lectura válida");
  elements.freshness.title = observedAt ? `Última lectura ${timeFormatter.format(observedAt)}` : "";
  elements.freshness.classList.toggle("aged", staleData && !criticalAge);
  elements.freshness.classList.toggle("stale", criticalAge);
  metricsPanel.classList.toggle("stale", staleData);
  if (value.observed_at === lastObservedAt) return;
  lastObservedAt = value.observed_at;
  lastPollSince = value.observed_at;
  const currency = value.currency || "USD";
  latestCurrency = currency;
  telemetryMode = value.source === "mt5-telemetry";
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
  equityCard.classList.toggle("positive", value.floating_profit > 0);
  equityCard.classList.toggle("negative", value.floating_profit < 0);
  elements["margin-free"].textContent = money(value.margin_free, currency);
  elements["margin-level"].textContent = value.margin_level === null
    ? "—"
    : `${number(value.margin_level)} %`;
  elements.positions.textContent = number(value.open_positions);
  elements.orders.textContent = number(value.active_orders);
  elements.margin.textContent = money(value.margin, currency);
  setText(elements["last-reading"], observedAt ? timeFormatter.format(observedAt) : "—");
  const health = state.source_health || {};
  const sourceId = health.source_id ? ` · ${health.source_id}` : "";
  const collector = health.collector_version ? ` · Colector ${health.collector_version}` : "";
  setText(sourceDescription, `${sourceLabel(value.source)}${sourceId}${collector}`);
  renderSummary(value, currency, state.status);
  latestOperations = Array.isArray(value.operations) ? value.operations : [];
  operationsBadge.textContent = number(latestOperations.length);
  if (activeView === "operations") renderOperations();
  const nextActivity = Array.isArray(value.recent_activity) ? value.recent_activity : [];
  latestActivity = nextActivity;
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
  const lastSuccessAt = capture.last_success_at ? toDate(capture.last_success_at) : null;
  setText(captureElements.lastSuccess, lastSuccessAt ? timeFormatter.format(lastSuccessAt) : "—");
  setText(captureElements.streak, failures === 0 ? "Sin fallos" : number(failures));
  captureElements.streak.className = failures === 0 ? "" : "negative-text";
  setText(captureElements.attempts, number(capture.attempt_count || 0));
  const duration = Number.isFinite(capture.last_duration_ms) ? `${number(capture.last_duration_ms)} ms` : "—";
  const maxDuration = Number.isFinite(capture.max_duration_ms) ? `${number(capture.max_duration_ms)} ms` : "—";
  setText(captureElements.results, `${number(capture.success_count || 0)} éxitos · ${number(capture.failure_count || 0)} fallos · duración última ${duration} · máxima ${maxDuration}`);
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

function renderOperations() {
  const filter = magicFilter.value.trim();
  const signature = `${latestCurrency}|${filter}|${JSON.stringify(latestOperations)}`;
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

  operationsBody.replaceChildren(...filtered.flatMap(operationRow));
  operationsEmpty.hidden = filtered.length > 0;
  operationsEmpty.textContent = latestOperations.length === 0
    ? "La fuente no informa operaciones abiertas."
    : "Ninguna operación coincide con ese Magic.";
  operationsNote.hidden = !(telemetryMode && latestOperations.length > 0);
  visibleOperations.textContent = filter
    ? `${number(filtered.length)} de ${number(latestOperations.length)}`
    : number(filtered.length);
  visiblePositions.textContent = number(filtered.filter((item) => item.kind === "position").length);
  visibleOrders.textContent = number(filtered.filter((item) => item.kind === "order").length);
  clearFilter.disabled = !filter;
}

function operationRow(operation) {
  const row = document.createElement("tr");
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
  row.appendChild(detailCell(operation.symbol, operation.comment || "Sin comentario", "", "Instrumento"));
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
  detailRow.hidden = true;
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
  button.setAttribute("aria-expanded", "false");
  button.textContent = "Ver detalle";
  button.addEventListener("click", () => {
    const expanded = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!expanded));
    button.textContent = expanded ? "Ver detalle" : "Ocultar detalle";
    detailRow.hidden = expanded;
  });
  buttonCell.appendChild(button);
  row.appendChild(buttonCell);
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
  if (history.length < 2) {
    chartEmpty.hidden = false;
    balanceLine.setAttribute("points", "");
    equityLine.setAttribute("points", "");
    balanceReference.classList.add("is-hidden");
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
  balanceReference.classList.remove("is-hidden");
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
  } catch (_) {
    // almacenamiento no disponible
  }
}

function saveStoredFilters() {
  try {
    localStorage.setItem(FILTER_STORE, JSON.stringify({
      magic: magicFilter.value,
    }));
  } catch (_) {
    // almacenamiento no disponible
  }
}

magicFilter.addEventListener("input", () => { renderOperations(); saveStoredFilters(); });
clearFilter.addEventListener("click", () => {
  magicFilter.value = "";
  magicFilter.focus();
  renderOperations();
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
