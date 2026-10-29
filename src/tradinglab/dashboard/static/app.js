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
const chartSpan = document.getElementById("chart-span");
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
const historyFilters = document.getElementById("history-filters");
const historyPeriod = document.getElementById("history-period");
const historyMagic = document.getElementById("history-magic");
const historyEntity = document.getElementById("history-entity");
const historyEntityField = document.getElementById("history-entity-field");
const historyReset = document.getElementById("history-reset");
const historyBody = document.getElementById("history-body");
const historyEmpty = document.getElementById("history-empty");
const historyCount = document.getElementById("history-count");
const historyScope = document.getElementById("history-scope");
const historyCoverage = document.getElementById("history-coverage");
const historyMore = document.getElementById("history-more");
const historyMetricsPanel = document.getElementById("history-metrics");
const historyTitle = document.getElementById("history-title");
const historyCopy = document.getElementById("history-copy");
const historyNote = document.getElementById("history-note");
const historyCountLabel = document.getElementById("history-count-label");
const historyCaption = document.getElementById("history-caption");
const historyHead = document.getElementById("history-head");
const tradingCurrentPanel = document.getElementById("trading-current-panel");
const tradingHistoryPanel = document.getElementById("trading-history-panel");
const metricsStatus = document.getElementById("metrics-status");
const metricElements = {
  net: document.getElementById("metric-net"), count: document.getElementById("metric-count"),
  pf: document.getElementById("metric-pf"), win: document.getElementById("metric-win"),
  average: document.getElementById("metric-average"), maxDd: document.getElementById("metric-max-dd"),
  maxDdPct: document.getElementById("metric-max-dd-pct"),
  currentDd: document.getElementById("metric-current-dd"),
  currentDdPct: document.getElementById("metric-current-dd-pct"),
  returnDd: document.getElementById("metric-return-dd"), expectancy: document.getElementById("metric-expectancy"),
  standardDeviation: document.getElementById("metric-standard-deviation"),
};
let latestOperations = [];
let latestOperationsTotal = 0;
let latestOperationsTruncated = false;
let latestCurrency = "USD";
let latestActivity = [];
let latestIntervalSeconds = 5;
let latestCaptureIntervalSeconds = 20;
let latestFreshnessToleranceSeconds = 10;
let latestAgeAtResponse = null;
let latestAgeMarkedAt = 0;
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
let historyRecords = [];
let historyNextCursor = null;
let historyNextCursors = { deals: null, orders: null };
let historyQuery = null;
let historyInitialized = false;
let historyLoading = false;
let tradingScope = "current";
let historyRequest = 0;
let metricsRequest = 0;
let historyMetrics = null;
let historyCoverageByEntity = {};
let brokerUtcOffsetMinutes = null;
let accountChart = null;
const metricCharts = new Map();
const METRIC_CHART_GROUP = "financial-performance";
let metricChartWindowKey = null;
const operationNodes = new Map();
const expandedOperationTickets = new Set();
const expandedClosedPositions = new Set();
const selectedEaMagics = new Set();
const comparedEaMagics = new Set();
let availableEaMagics = [];
let financialMode = "summary";
const MAX_COMPARISON_EAS = 5;
let accountHistoryWindow = null;
let accountHistoryData = null;
let accountHistoryRequest = 0;
let accountChartWindowKey = null;
let rankingRequest = 0;
let rankingKey = "";
let rankingCheckedAt = 0;

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

const dealTypes = {
  0: "Compra", 1: "Venta", 2: "Balance", 3: "Crédito", 4: "Cargo",
  5: "Corrección", 6: "Bonus", 7: "Comisión", 8: "Comisión diaria",
  9: "Comisión mensual", 10: "Comisión agente", 11: "Interés",
  12: "Compra cancelada", 13: "Venta cancelada", 14: "Dividendo",
  15: "Dividendo franqueado", 16: "Impuesto", 17: "Otro",
};

const dealEntries = {
  0: "Entrada", 1: "Salida", 2: "Entrada y salida", 3: "Cierre por otra posición",
};

const historicalOrderTypes = {
  0: "Compra", 1: "Venta", 2: "Compra limit", 3: "Venta limit",
  4: "Compra stop", 5: "Venta stop", 6: "Compra stop limit",
  7: "Venta stop limit", 8: "Cierre por otra",
};

const historicalOrderStates = {
  0: "Iniciada", 1: "Colocada", 2: "Cancelada", 3: "Parcial",
  4: "Completada", 5: "Rechazada", 6: "Expirada", 7: "Solicitud de alta",
  8: "Solicitud de cambio", 9: "Solicitud de cancelación",
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
const brokerDateTimeFormatter = new Intl.DateTimeFormat(LOCALE, {
  dateStyle: "short", timeStyle: "medium", hour12: false, timeZone: "UTC",
});
const brokerRowTimeFormatter = new Intl.DateTimeFormat(LOCALE, {
  dateStyle: "short", timeStyle: "short", hour12: false, timeZone: "UTC",
});
const compactLocalFormatter = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
});
const compactBrokerFormatter = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  timeZone: "UTC",
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

function operationalTime(rawMsc) {
  if (rawMsc === null || rawMsc === undefined || rawMsc === "") return null;
  const numeric = typeof rawMsc === "string" ? Date.parse(rawMsc) : Number(rawMsc);
  if (!Number.isFinite(numeric)) return null;
  const broker = new Date(numeric);
  if (Number.isNaN(broker.getTime())) return null;
  const local = Number.isInteger(brokerUtcOffsetMinutes)
    ? new Date(numeric - brokerUtcOffsetMinutes * 60 * 1000)
    : null;
  return {
    broker: brokerDateTimeFormatter.format(broker),
    local: local ? dateTimeFormatter.format(local) : "Offset no configurado",
  };
}

function operationalTimeCell(rawMsc, label) {
  const value = operationalTime(rawMsc);
  return value
    ? detailCell(`Broker ${value.broker}`, `Local ${value.local}`, "dual-time", label)
    : textCell("—", "", label);
}

function operationalChartLabel(rawMsc) {
  const numeric = Number(rawMsc);
  if (!Number.isFinite(numeric)) return "—";
  const broker = new Date(numeric);
  if (Number.isNaN(broker.getTime())) return "—";
  const brokerLabel = compactBrokerFormatter.format(broker);
  if (!Number.isInteger(brokerUtcOffsetMinutes)) return `B ${brokerLabel}`;
  const local = new Date(numeric - brokerUtcOffsetMinutes * 60 * 1000);
  return `B ${brokerLabel}\nL ${compactLocalFormatter.format(local)}`;
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
  latestIntervalSeconds = state.interval_seconds || 5;
  latestCaptureIntervalSeconds = state.capture_interval_seconds || latestIntervalSeconds;
  latestFreshnessToleranceSeconds = state.freshness_tolerance_seconds
    || Math.max(5, latestIntervalSeconds * 2);
  latestAgeAtResponse = Number.isFinite(state.latest_age_seconds)
    ? Math.max(0, state.latest_age_seconds) : null;
  latestAgeMarkedAt = performance.now();
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
    if (activeView === "trading" && tradingScope === "current") renderOperations();
    updateFreshness();
    return;
  }

  const value = state.latest;
  const observedAt = toDate(value.observed_at);
  latestObservedDate = observedAt;
  updateFreshness();
  const currency = value.currency || "USD";
  renderSummary(value, currency, state.status);
  const health = state.source_health || {};
  const filterScope = health.source_id || value.source || "local";
  if (filterScope !== currentFilterScope) loadStoredFilters(filterScope);
  const currencyChanged = latestCurrency !== currency;
  latestCurrency = currency;
  telemetryMode = value.source === "mt5-telemetry";
  if (value.observed_at === lastObservedAt) {
    if (currencyChanged && ["financial", "execution"].includes(activeView)) renderHistory();
    if (currencyChanged && activeView === "overview") renderChart(lastHistory, latestIntervalSeconds);
    return;
  }
  lastObservedAt = value.observed_at;
  lastPollSince = value.observed_at;
  modeNotice.hidden = value.source !== "demo";
  elements["account-identity"].textContent = value.account_reference && value.server
    ? `Cuenta ${value.account_reference} · ${value.server} · ${currency}`
    : "Cuenta sin identificar";
  elements.balance.textContent = money(value.balance, currency);
  elements.equity.textContent = money(value.equity, currency);
  setText(elements["profit-line"], `PnL flotante ${money(value.floating_profit, currency, true)}`);
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
  if (activeView === "overview") refreshEaRanking();
  latestOperationsTotal = Math.max(
    latestOperations.length,
    Number(value.open_positions || 0) + Number(value.active_orders || 0),
  );
  latestOperationsTruncated = value.operations_truncated === true;
  operationsBadge.textContent = number(latestOperationsTotal);
  if (activeView === "trading" && tradingScope === "current") renderOperations();
  if (
    activeView === "execution"
    && ["all", "current"].includes(historyEntity.value)
  ) {
    historyRecords = [
      ...historyRecords.filter((record) => record._entity !== "current"),
      ...registryCurrentRecords(historyEntity.value, historyQuery?.magic ?? null),
    ].sort((left, right) => historyRecordTime(right) - historyRecordTime(left));
    renderHistory();
  }
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
  const ageSeconds = currentFreshnessAge();
  const outdated = ageSeconds !== null
    && ageSeconds > latestCaptureIntervalSeconds + latestFreshnessToleranceSeconds;
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
    text.textContent = "Las ejecuciones conservadas en SQLite se consultan en Historial. Esta sección queda reservada para el estado de captura y los eventos recientes.";
    const link = document.createElement("a");
    link.href = "#history";
    link.textContent = "Ver historial de ejecuciones";
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
  ["Broker / Local", "Evento", "Instrumento", "Magic", "Resultado"].forEach((label, index) => {
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
    row.appendChild(operationalTimeCell(activity.occurred_at, "Broker / Local"));
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

const HISTORY_PAGE_SIZE = 50;
const HISTORY_CLIENT_LIMIT = 500;

function historyMagicValue() {
  const value = historyMagic.value.trim();
  historyMagic.setCustomValidity("");
  if (!value) return null;
  if (!/^-?(0|[1-9][0-9]{0,18})$/.test(value)) {
    historyMagic.setCustomValidity("Ingresá un Magic Number entero sin espacios.");
    return null;
  }
  const parsed = BigInt(value);
  if (parsed < -(2n ** 63n) || parsed > 2n ** 63n - 1n) {
    historyMagic.setCustomValidity("El Magic Number está fuera del rango admitido por MT5.");
    return null;
  }
  return value;
}

function setHistoryLoading(loading) {
  historyLoading = loading;
  historyFilters.querySelector('button[type="submit"]').disabled = loading;
  historyMore.disabled = loading;
  if (loading && historyRecords.length === 0) {
    historyEmpty.hidden = false;
    historyEmpty.textContent = "Consultando el historial guardado…";
  }
  renderHistoryCoverage();
}

function coverageState(coverage, query) {
  if (!coverage || !query || !Array.isArray(coverage.complete_ranges)
      || !Number.isInteger(coverage.incomplete_batches)) return null;
  const ranges = coverage.complete_ranges
    .map((item) => [Number(item?.from_msc), Number(item?.to_msc)])
    .filter(([start, end]) => Number.isSafeInteger(start) && Number.isSafeInteger(end) && start <= end)
    .sort((left, right) => left[0] - right[0]);
  let coveredUntil = query.fromMsc - 1;
  for (const [start, end] of ranges) {
    if (start > coveredUntil + 1) break;
    coveredUntil = Math.max(coveredUntil, end);
  }
  return {
    complete: coverage.incomplete_batches === 0 && coveredUntil >= query.toMsc - 1,
    coveredUntil,
    incompleteBatches: coverage.incomplete_batches,
  };
}

function renderHistoryCoverage() {
  let label = "Sin consultar cobertura";
  let tone = "neutral";
  let title = "La cobertura indica si SQLite conserva evidencia completa para el período filtrado.";
  if (historyLoading) {
    label = "Comprobando cobertura…";
  } else if (tradingScope === "registry" && historyEntity.value === "current") {
    label = "Instantánea actual";
    title = "La actividad en curso es una instantánea y no un rango histórico.";
  } else if (historyQuery) {
    const required = tradingScope === "closed" ? [historyCoverageByEntity.deals]
      : historyEntity.value === "all"
        ? [historyCoverageByEntity.deals, historyCoverageByEntity.orders]
        : [historyCoverageByEntity[historyEntity.value]];
    const states = required.map((value) => coverageState(value, historyQuery));
    if (states.every(Boolean)) {
      const complete = states.every((state) => state.complete);
      label = complete ? "Datos completos" : "Datos parciales";
      tone = complete ? "complete" : "partial";
      const incomplete = states.reduce((total, state) => total + state.incompleteBatches, 0);
      const earliestGap = Math.min(...states.map((state) => state.coveredUntil));
      title = complete
        ? "SQLite confirma cobertura completa para todo el período filtrado."
        : `La evidencia no cubre todo el período${incomplete ? `; ${incomplete} lote(s) incompleto(s)` : ""}.`
          + (earliestGap >= historyQuery.fromMsc
            ? ` Cobertura continua hasta Broker ${operationalTime(earliestGap)?.broker || "desconocido"}.`
            : "");
    }
  }
  historyCoverage.className = `coverage-indicator ${tone}`;
  historyCoverage.lastElementChild.textContent = label;
  historyCoverage.title = title;
}

function selectedTimeWindow(days, endDate = "", broker = false, now = Date.now()) {
  if (![1, 7, 30, 90, 180, 365].includes(days)) throw new Error("Período inválido.");
  const current = now + (broker ? (brokerUtcOffsetMinutes ?? 0) * 60000 : 0);
  let toMsc = current;
  if (endDate) {
    const date = new Date(`${endDate}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(endDate) || !Number.isFinite(date.getTime())
      || date.toISOString().slice(0, 10) !== endDate || date.getTime() > current) {
      throw new Error("Elegí una fecha válida, hasta hoy.");
    }
    toMsc = Math.min(current, date.getTime() + 86400000);
  }
  let fromMsc = toMsc - days * 86400000;
  if (days === 365) {
    const previousYear = new Date(toMsc);
    const month = previousYear.getUTCMonth();
    previousYear.setUTCFullYear(previousYear.getUTCFullYear() - 1);
    if (previousYear.getUTCMonth() !== month) previousYear.setUTCDate(0);
    fromMsc = previousYear.getTime();
  }
  return { fromMsc, toMsc };
}

async function loadTradingHistory({ append = false } = {}) {
  if (historyLoading) return;
  const magic = tradingScope === "closed" ? null : historyMagicValue();
  if (tradingScope !== "closed" && historyMagic.validationMessage) {
    historyMagic.reportValidity();
    return;
  }
  if (!append) {
    expandedRegistryRecords.clear();
    const days = Number(historyPeriod.value);
    let period;
    try {
      period = selectedTimeWindow(days, document.getElementById("history-end-date").value, true);
    } catch (error) {
      metricsStatus.textContent = error.message;
      return;
    }
    const toMsc = period.toMsc;
    historyQuery = {
      fromMsc: period.fromMsc,
      toMsc,
      magic,
      magics: tradingScope === "closed" ? [...(financialMode === "compare" ? comparedEaMagics : selectedEaMagics)] : [],
      days,
      endDate: document.getElementById("history-end-date").value,
    };
    historyRecords = [];
    historyNextCursor = null;
    historyNextCursors = { deals: null, orders: null };
    historyCoverageByEntity = {};
    historyInitialized = true;
    renderHistory();
  }
  if (!historyQuery) return;

  if (tradingScope === "closed") {
    await loadClosedOperations({ append });
  } else {
    await loadMt5Registry({ append });
  }
}

function historyParameters(query, cursor = null) {
  const parameters = new URLSearchParams({
    from_msc: String(query.fromMsc),
    to_msc: String(query.toMsc),
    limit: String(HISTORY_PAGE_SIZE),
  });
  if (query.magic !== null) parameters.set("magic_number", query.magic);
  if (cursor) parameters.set("cursor", cursor);
  return parameters;
}

async function authenticatedHistoryFetch(url, signal) {
  const response = await fetch(url, { cache: "no-store", signal });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("La sesión expiró.");
  }
  if (response.status === 404) {
    throw new Error("El historial durable requiere el receptor con almacenamiento SQLite.");
  }
  if (!response.ok) throw new Error("No se pudo consultar el historial guardado.");
  return response.json();
}

async function loadClosedOperations({ append }) {
  if (append && !historyNextCursor) return;
  const requestNumber = ++historyRequest;
  if (!append) void loadHistoryMetrics(historyQuery, ++metricsRequest);
  const parameters = historyParameters(historyQuery, append ? historyNextCursor : null);
  parameters.delete("magic_number");
  if (historyQuery.magic !== null) parameters.set("owner_magic", historyQuery.magic);
  if (historyQuery.magics?.length) parameters.set("owner_magics", historyQuery.magics.join(","));
  parameters.set("closed", "true");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  setHistoryLoading(true);
  try {
    const payload = await authenticatedHistoryFetch(
      `/api/position-cycles?${parameters}`,
      controller.signal,
    );
    if (requestNumber !== historyRequest) return;
    const incoming = Array.isArray(payload.cycles)
      ? payload.cycles.map((item) => ({ ...item, _entity: "cycle" })) : [];
    const known = new Set(historyRecords.map(historyRecordKey));
    historyRecords = [...historyRecords, ...incoming.filter((item) => !known.has(historyRecordKey(item)))]
      .slice(0, HISTORY_CLIENT_LIMIT);
    historyNextCursor = historyRecords.length >= HISTORY_CLIENT_LIMIT ? null : payload.next_cursor;
    renderHistory();
  } catch (error) {
    handleHistoryError(error, requestNumber);
  } finally {
    window.clearTimeout(timeout);
    if (requestNumber === historyRequest) setHistoryLoading(false);
  }
}

async function loadMt5Registry({ append }) {
  const selected = historyEntity.value;
  const targets = selected === "all" ? ["deals", "orders"]
    : selected === "current" ? [] : [selected];
  if (append && !targets.some((entity) => historyNextCursors[entity])) return;
  const requestNumber = ++historyRequest;
  if (!append) {
    historyRecords = registryCurrentRecords(selected, historyQuery.magic);
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  setHistoryLoading(true);
  try {
    const requests = targets
      .filter((entity) => !append || historyNextCursors[entity])
      .map(async (entity) => {
        const parameters = historyParameters(
          historyQuery,
          append ? historyNextCursors[entity] : null,
        );
        const payload = await authenticatedHistoryFetch(`/api/${entity}?${parameters}`, controller.signal);
        const values = Array.isArray(payload[entity]) ? payload[entity] : [];
        return {
          entity,
          nextCursor: payload.next_cursor,
          coverage: payload.coverage,
          records: values.map((item) => ({
            ...item,
            _entity: entity === "deals" ? "deal" : "order",
          })),
        };
      });
    const results = await Promise.all(requests);
    if (requestNumber !== historyRequest) return;
    results.forEach((result) => {
      historyNextCursors[result.entity] = result.nextCursor;
      if (result.coverage) historyCoverageByEntity[result.entity] = result.coverage;
    });
    const incoming = results.flatMap((result) => result.records);
    const known = new Set(historyRecords.map(historyRecordKey));
    historyRecords = [
      ...historyRecords,
      ...incoming.filter((item) => !known.has(historyRecordKey(item))),
    ]
      .sort((left, right) => historyRecordTime(right) - historyRecordTime(left))
      .slice(0, HISTORY_CLIENT_LIMIT);
    historyNextCursor = targets.some((entity) => historyNextCursors[entity]) ? "registry" : null;
    renderHistory();
  } catch (error) {
    handleHistoryError(error, requestNumber);
  } finally {
    window.clearTimeout(timeout);
    if (requestNumber === historyRequest) setHistoryLoading(false);
  }
}

function registryCurrentRecords(selected, magic) {
  if (!["all", "current"].includes(selected)) return [];
  return latestOperations
    .filter((operation) => magic === null || String(operation.magic_number) === magic)
    .map((operation) => ({ ...operation, _entity: "current" }));
}

function historyRecordKey(record) {
  if (record._entity === "cycle") return `cycle:${record.cycle.account_id}:${record.cycle.position_id}`;
  return `${record._entity}:${record.account_id || "current"}:${record.ticket}`;
}

function historyRecordTime(record) {
  if (record._entity === "cycle") return record.cycle.last_event_at_msc;
  if (record._entity === "deal") return record.time_msc;
  if (record._entity === "order") return record.done_time_msc;
  const opened = record.opened_at ? toDate(record.opened_at) : null;
  return opened ? opened.getTime() : Number.MAX_SAFE_INTEGER;
}

function handleHistoryError(error, requestNumber) {
  if (requestNumber !== historyRequest) return;
  historyNextCursor = null;
  historyEmpty.hidden = historyRecords.length > 0;
  historyEmpty.textContent = error.name === "AbortError"
    ? "La consulta tardó demasiado. Podés volver a intentarlo."
    : error.message;
  historyMore.hidden = true;
}

async function loadHistoryMetrics(query, requestNumber) {
  historyMetrics = null;
  renderHistoryMetrics();
  metricsStatus.textContent = "Calculando sobre el historial verificado…";
  const parameters = new URLSearchParams({
    from_msc: String(query.fromMsc),
    to_msc: String(query.toMsc),
  });
  if (query.magic !== null) parameters.set("magic_number", query.magic);
  if (query.magics?.length) parameters.set("magic_numbers", query.magics.join(","));
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  try {
    const discovery = await fetch("/api/cycle-magics", {
      cache: "no-store", signal: controller.signal,
    });
    if (discovery.status === 401) {
      window.location.assign("/login");
      return;
    }
    if (discovery.ok) {
      const discovered = await discovery.json();
      if (requestNumber !== metricsRequest) return;
      if (Array.isArray(discovered.magics)) renderEaSelector(discovered.magics);
    }
    const response = await fetch(`/api/cycle-metrics?${parameters}`, {
      cache: "no-store", signal: controller.signal,
    });
    if (response.status === 401) {
      window.location.assign("/login");
      return;
    }
    if (!response.ok) throw new Error("No se pudieron calcular las métricas para este período.");
    const payload = await response.json();
    if (requestNumber !== metricsRequest) return;
    if (payload?.formula_version !== "position-cycle-v1" || !Array.isArray(payload.series)) {
      throw new Error("El servicio devolvió métricas en un formato desconocido.");
    }
    historyMetrics = payload;
    if (!query.magics?.length) {
      renderEaSelector(payload.available_magics || payload.by_ea.map((ea) => ea.magic_number));
    }
    historyCoverageByEntity.deals = payload.coverage;
    renderHistoryMetrics();
    renderHistoryCoverage();
  } catch (error) {
    if (requestNumber !== metricsRequest) return;
    metricsStatus.textContent = error.name === "AbortError"
      ? "El cálculo tardó demasiado. Probá un período menor."
      : error.message;
  } finally {
    window.clearTimeout(timeout);
  }
}

function renderHistoryMetrics() {
  const value = historyMetrics;
  metricElements.net.textContent = value ? money(value.net_profit, latestCurrency, true) : "—";
  metricElements.net.classList.toggle("positive-text", Boolean(value && value.net_profit > 0));
  metricElements.net.classList.toggle("negative-text", Boolean(value && value.net_profit < 0));
  metricElements.count.textContent = value ? number(value.trade_count) : "—";
  metricElements.pf.textContent = value ? decimal(value.profit_factor) : "—";
  metricElements.win.textContent = value && Number.isFinite(value.winning_percentage)
    ? `${decimal(value.winning_percentage * 100)} %` : "—";
  metricElements.average.textContent = value ? money(value.average_trade, latestCurrency, true) : "—";
  metricElements.maxDd.textContent = value ? money(value.maximum_drawdown, latestCurrency) : "—";
  metricElements.maxDdPct.textContent = value && Number.isFinite(value.maximum_drawdown_percentage)
    ? `${decimal(value.maximum_drawdown_percentage * 100)} %` : "—";
  metricElements.currentDd.textContent = value ? money(value.current_drawdown, latestCurrency) : "—";
  metricElements.currentDdPct.textContent = value && Number.isFinite(value.current_drawdown_percentage)
    ? `${decimal(value.current_drawdown_percentage * 100)} %` : "—";
  metricElements.returnDd.textContent = value ? decimal(value.return_drawdown_ratio) : "—";
  metricElements.expectancy.textContent = value && Number.isFinite(value.expectancy_r)
    ? `${decimal(value.expectancy_r)} R` : "—";
  metricElements.standardDeviation.textContent = value
    ? money(value.standard_deviation, latestCurrency) : "—";
  if (!value) {
    metricCharts.forEach((chartInstance) => chartInstance.clear());
    document.getElementById("ea-comparison-table").replaceChildren();
    document.getElementById("ea-comparison-note").textContent = "";
    return;
  }
  metricsStatus.textContent = value.trade_count
    ? `${value.trade_count} operaciones · ${financialMode === "compare" ? "Comparación por EA" : historyQuery?.magics?.length ? "Selección combinada" : "Todos los EAs"}`
      + (coverageState(value.coverage, historyQuery)?.complete ? "" : " · cobertura parcial")
    : "Sin operaciones elegibles para los filtros elegidos.";
  metricsStatus.classList.toggle(
    "warn-text",
    !coverageState(value.coverage, historyQuery)?.complete,
  );
  updateFinancialLayout();
  renderMetricCharts();
}

function eaColor(magic) {
  let hash = 0;
  for (const char of String(magic)) hash = (Math.imul(hash, 31) + char.charCodeAt(0)) | 0;
  return `hsl(${((hash >>> 0) * 137.508) % 360}, 52%, 56%)`;
}

function rankedEas(items) {
  return [...items].sort((a, b) => b.net_profit - a.net_profit
    || String(a.magic_number).localeCompare(String(b.magic_number)));
}

function renderEaComparison(items) {
  const table = document.createElement("table");
  table.className = "ea-metrics-table";
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  const metricTitle = document.createElement("th");
  metricTitle.scope = "col"; metricTitle.textContent = "Métrica"; header.appendChild(metricTitle);
  items.forEach((ea) => {
    const cell = document.createElement("th");
    cell.scope = "col"; cell.textContent = `Magic ${ea.magic_number}`;
    cell.style.borderTop = `3px solid ${eaColor(ea.magic_number)}`;
    header.appendChild(cell);
  });
  head.appendChild(header);
  const body = document.createElement("tbody");
  const percent = (value) => Number.isFinite(value) ? `${decimal(value * 100)} %` : "—";
  const cash = (value) => money(value, latestCurrency, true);
  const definitions = [
    ["PnL neto", "net_profit", cash], ["Operaciones", "trade_count", number],
    ["Profit Factor", "profit_factor", decimal], ["Ganadoras", "winning_percentage", percent],
    ["Promedio", "average_trade", cash], ["Max Drawdown", "maximum_drawdown", cash],
    ["Max Drawdown %", "maximum_drawdown_percentage", percent],
    ["Drawdown actual", "current_drawdown", cash], ["Drawdown actual %", "current_drawdown_percentage", percent],
    ["Return / DD", "return_drawdown_ratio", decimal],
    ["Expectancy neta (R)", "expectancy_r", (value) => Number.isFinite(value) ? `${decimal(value)} R` : "—"],
    ["Desviación estándar", "standard_deviation", cash],
  ];
  definitions.forEach(([label, field, format]) => {
    const row = document.createElement("tr");
    const heading = document.createElement("th"); heading.scope = "row"; heading.textContent = label;
    row.appendChild(heading);
    items.forEach((ea) => row.appendChild(textCell(format(ea[field]), "numeric", `Magic ${ea.magic_number}`)));
    body.appendChild(row);
  });
  table.append(head, body);
  document.getElementById("ea-comparison-table").replaceChildren(...(items.length ? [table] : []));
  document.getElementById("ea-comparison-note").textContent = items.length ? "" : "Seleccioná hasta 5 EAs para comparar.";
}

function updateFinancialLayout() {
  const comparing = financialMode === "compare";
  document.getElementById("summary-metrics").hidden = comparing;
  document.getElementById("ea-comparison").hidden = !comparing;
  document.getElementById("comparison-sidebar").hidden = !comparing;
  document.querySelector(".financial-layout").classList.toggle("is-comparing", comparing);
  document.getElementById("ea-selector").hidden = tradingScope !== "closed" || comparing;
  document.querySelectorAll("[data-financial-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.financialMode === financialMode));
  });
}

function applyFinancialFilters() {
  // Obsolete requests may finish, but cannot replace the newly selected view.
  historyRequest += 1;
  metricsRequest += 1;
  setHistoryLoading(false);
  loadTradingHistory();
}

document.querySelectorAll("[data-financial-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    if (financialMode === button.dataset.financialMode) return;
    financialMode = button.dataset.financialMode;
    updateFinancialLayout();
    renderComparisonOptions();
    applyFinancialFilters();
    window.requestAnimationFrame(() => metricCharts.forEach((chart) => chart.resize()));
  });
});

function renderComparisonOptions() {
  const list = document.getElementById("comparison-options");
  const search = document.getElementById("comparison-search").value.trim().toLowerCase();
  const magics = [...new Set([...availableEaMagics, ...comparedEaMagics])].sort()
    .filter((magic) => magic.toLowerCase().includes(search));
  list.replaceChildren();
  magics.forEach((magic) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox"; input.value = magic; input.checked = comparedEaMagics.has(magic);
    input.disabled = !input.checked && comparedEaMagics.size >= MAX_COMPARISON_EAS;
    const swatch = document.createElement("span");
    swatch.className = "ea-color-dot"; swatch.style.backgroundColor = eaColor(magic); swatch.setAttribute("aria-hidden", "true");
    const name = document.createElement("span"); name.textContent = magic;
    input.addEventListener("change", () => {
      if (input.checked && comparedEaMagics.size < MAX_COMPARISON_EAS) comparedEaMagics.add(magic);
      else comparedEaMagics.delete(magic);
      document.querySelectorAll("#comparison-options input").forEach((option) => {
        option.disabled = !option.checked && comparedEaMagics.size >= MAX_COMPARISON_EAS;
      });
      updateComparisonCount();
    });
    label.addEventListener("pointerenter", () => focusMetricEa(magic));
    label.addEventListener("pointerleave", () => focusMetricEa(null));
    label.append(input, swatch, name); list.appendChild(label);
  });
  if (!magics.length) list.textContent = search ? "Sin coincidencias." : "Sin EAs disponibles para este período.";
  updateComparisonCount();
}

function updateComparisonCount() {
  document.getElementById("comparison-count").textContent = `${comparedEaMagics.size} / ${MAX_COMPARISON_EAS}`;
  document.getElementById("comparison-feedback").textContent =
    comparedEaMagics.size >= MAX_COMPARISON_EAS ? "Máximo 5 EAs." : "";
}
document.getElementById("comparison-search").addEventListener("input", renderComparisonOptions);
document.getElementById("comparison-clear").addEventListener("click", () => {
  comparedEaMagics.clear(); renderComparisonOptions();
});
document.getElementById("comparison-apply").addEventListener("click", applyFinancialFilters);

function renderEaSelector(magics) {
  availableEaMagics = magics;
  renderComparisonOptions();
  const options = document.getElementById("ea-selector-options");
  options.replaceChildren();
  const available = [...new Set([...magics, ...selectedEaMagics])].sort();
  available.forEach((magic) => {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = magic;
    checkbox.checked = selectedEaMagics.has(magic);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked && selectedEaMagics.size >= 12) {
        checkbox.checked = false;
        document.getElementById("ea-selector-status").textContent = "Máximo 12 EAs por selección.";
        return;
      }
      if (checkbox.checked) selectedEaMagics.add(magic);
      else selectedEaMagics.delete(magic);
      updateEaSelectionLabel();
    });
    const text = document.createElement("span");
    text.textContent = `Magic ${magic}`;
    label.append(checkbox, text); options.appendChild(label);
  });
  if (!available.length) options.textContent = "No hay EAs elegibles en este período.";
  updateEaSelectionLabel();
}

function updateEaSelectionLabel() {
  document.getElementById("ea-selector-label").textContent = selectedEaMagics.size
    ? `${selectedEaMagics.size} EA(s) seleccionados` : "Todos los EAs";
  document.getElementById("ea-selector-status").textContent = "Hasta 12 EAs · aplicá los filtros para actualizar.";
}

document.getElementById("ea-select-all").addEventListener("click", () => {
  selectedEaMagics.clear();
  document.querySelectorAll("#ea-selector-options input").forEach((input) => { input.checked = false; });
  updateEaSelectionLabel();
});

async function refreshEaRanking(force = false) {
  if (!latestObservedDate) return;
  const days = Number(document.getElementById("ranking-period").value);
  const key = `${currentFilterScope}:${elements["account-identity"].textContent}:${days}`;
  if (!force && key === rankingKey && Date.now() - rankingCheckedAt < 60000) return;
  rankingKey = key; rankingCheckedAt = Date.now();
  const request = ++rankingRequest;
  const status = document.getElementById("ranking-status");
  const list = document.getElementById("ea-ranking-list");
  list.replaceChildren(); status.textContent = "Consultando operaciones cerradas…";
  const toMsc = Date.now() + (brokerUtcOffsetMinutes ?? 0) * 60000;
  const query = { fromMsc: toMsc - days * 86400000, toMsc };
  const parameters = new URLSearchParams({ from_msc: String(query.fromMsc), to_msc: String(toMsc) });
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  try {
    const payload = await authenticatedHistoryFetch(`/api/cycle-metrics?${parameters}`, controller.signal);
    if (request !== rankingRequest) return;
    if (!Array.isArray(payload.by_ea)) throw new Error("Comparativa no disponible; reiniciá el servidor actualizado.");
    const top = rankedEas(payload.by_ea).slice(0, 3);
    status.textContent = top.length ? `Últimos ${days} días · ${coverageState(payload.coverage, query).complete ? "cobertura completa" : "cobertura parcial"}`
      : `Sin operaciones elegibles en los últimos ${days} días.`;
    top.forEach((ea) => {
      const item = document.createElement("li");
      const identity = document.createElement("span");
      identity.textContent = `Magic ${ea.magic_number} · ${ea.trade_count} ops.`;
      identity.style.borderLeft = `3px solid ${eaColor(ea.magic_number)}`;
      const pnl = document.createElement("strong");
      pnl.textContent = money(ea.net_profit, latestCurrency, true);
      pnl.className = ea.net_profit > 0 ? "positive-text" : ea.net_profit < 0 ? "negative-text" : "";
      item.append(identity, pnl); list.appendChild(item);
    });
  } catch (error) {
    if (request !== rankingRequest) return;
    status.textContent = error.name === "AbortError" ? "La consulta tardó demasiado. Probá 7 días." : error.message;
  } finally { window.clearTimeout(timeout); }
}

document.getElementById("ranking-period").addEventListener("change", () => refreshEaRanking(true));

function resolvedChartTheme() {
  const style = getComputedStyle(document.documentElement);
  return {
    ink: style.getPropertyValue("--chart-text").trim(),
    grid: style.getPropertyValue("--chart-grid").trim(),
    axis: style.getPropertyValue("--chart-axis").trim(),
    surface: style.getPropertyValue("--chart-surface").trim(),
    accent: style.getPropertyValue("--chart-accent").trim(),
    profit: style.getPropertyValue("--chart-profit").trim(),
    loss: style.getPropertyValue("--chart-loss").trim(),
  };
}

function focusMetricEa(magic) {
  metricCharts.forEach((chartInstance) => {
    chartInstance.dispatchAction({ type: "downplay" });
    if (magic !== null) chartInstance.dispatchAction({ type: "highlight", seriesName: `Magic ${magic}` });
  });
}

function eaChartSeries(items, field, fromMsc, comparing = false) {
  return items.map((ea) => ({
    name: `Magic ${ea.magic_number}`,
    type: field === "net_profit" ? "bar" : "line",
    smooth: false,
    showSymbol: false,
    symbolSize: 4,
    barMaxWidth: field === "net_profit" ? 16 : undefined,
    barMinHeight: field === "net_profit" ? 1 : undefined,
    barGap: field === "net_profit" && comparing ? "20%" : undefined,
    itemStyle: { color: eaColor(ea.magic_number) },
    lineStyle: { color: eaColor(ea.magic_number), width: 2 },
    label: field === "net_profit" ? {
      show: true,
      distance: 3,
      fontSize: 9,
      formatter: (item) => {
        const value = Number(item.value[1]);
        return Number.isFinite(value) ? `${value > 0 ? "+" : ""}${decimal(value)}` : "";
      },
    } : undefined,
    data: [
      ...(["cumulative_profit", "drawdown"].includes(field) ? [[fromMsc, 0]] : []),
      ...ea.series.map((point) => {
        const result = field === "drawdown" ? -Math.abs(point[field]) : point[field];
        return field === "net_profit"
          ? { value: [point.time_msc, result], label: { position: result < 0 ? "bottom" : "top" } }
          : [point.time_msc, result];
      }),
    ],
    emphasis: { focus: "series", blurScope: "coordinateSystem", scale: true },
  }));
}

function renderMetricCharts() {
  if (!window.echarts) {
    metricsStatus.textContent = "La librería de gráficos no pudo cargarse.";
    return;
  }
  const value = historyMetrics;
  if (!value) return;
  const comparing = financialMode === "compare";
  const items = historyQuery?.magics?.length ? (value.by_ea || []) : [];
  const plotted = comparing ? items.slice(0, MAX_COMPARISON_EAS)
    : [{ magic_number: "summary", series: value.series }];
  if (comparing && !historyQuery?.magics?.length) metricsStatus.textContent = "Seleccioná hasta 5 EAs y aplicá la selección.";
  else if (comparing && !items.length) metricsStatus.textContent = "Sin operaciones elegibles para la selección.";
  const { ink, grid: border, axis, surface, accent, profit, loss } = resolvedChartTheme();
  const chartWindowKey = `${value.from_msc}:${value.to_msc}:${financialMode}`;
  const previous = metricChartWindowKey === chartWindowKey
    ? metricCharts.values().next().value?.getOption?.().dataZoom?.[0] : null;
  const zoom = previous ? { start: previous.start, end: previous.end } : { start: 0, end: 100 };
  metricChartWindowKey = chartWindowKey;
  const common = {
    animationDuration: 250, aria: { enabled: true },
    legend: { show: false },
    grid: { left: 8, right: 10, top: 12, bottom: 30, containLabel: true },
    textStyle: { color: ink },
    tooltip: {
      trigger: "axis", order: "seriesAsc", renderMode: "richText", backgroundColor: surface, borderColor: axis,
      textStyle: { color: ink },
      axisPointer: { type: "line", lineStyle: { color: axis, type: "dashed", width: 1 } },
      valueFormatter: (point) => money(Array.isArray(point) ? point[1] : point, latestCurrency, true),
    },
    xAxis: { type: "time", min: value.from_msc, max: value.to_msc,
      axisLabel: { color: ink, hideOverlap: true, formatter: operationalChartLabel },
      axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
    yAxis: { type: "value", splitNumber: 4, axisLabel: { color: ink }, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: border, type: "dashed", opacity: 0.72 } } },
  };
  [["chart-cumulative", "cumulative_profit"], ["chart-drawdown", "drawdown"],
    ["chart-profit", "net_profit"], ["chart-rolling", "rolling_average_20"]].forEach(([id, field]) => {
    const instance = metricCharts.get(id) || window.echarts.init(document.getElementById(id));
    metricCharts.set(id, instance);
    instance.group = METRIC_CHART_GROUP;
    const isDrawdown = field === "drawdown";
    const showTimeline = field !== "cumulative_profit";
    const series = eaChartSeries(plotted, field, value.from_msc, comparing).map((item) => {
      const labeled = { ...item, label: item.label ? { ...item.label, color: ink } : undefined };
      return comparing ? labeled : {
        ...labeled, name: "Conjunto seleccionado",
        itemStyle: field === "net_profit" ? { color: (point) => point.value[1] >= 0 ? profit : loss } : { color: accent },
        lineStyle: { color: isDrawdown ? loss : accent, width: 2 },
        areaStyle: ["cumulative_profit", "drawdown"].includes(field)
          ? { color: isDrawdown ? loss : accent, opacity: 0.08 } : undefined,
      };
    });
    instance.setOption({
      ...common,
      tooltip: { ...common.tooltip, trigger: "axis" },
      grid: { ...common.grid, bottom: isDrawdown ? 46 : showTimeline ? 30 : 10 },
      xAxis: { ...common.xAxis, axisLabel: { ...common.xAxis.axisLabel, show: showTimeline } },
      yAxis: { ...common.yAxis, ...(isDrawdown ? { max: 0 } : {}), ...(field === "net_profit" ? {
        min: ({ min }) => min < 0 ? min * 1.14 : 0,
        max: ({ max }) => max > 0 ? max * 1.14 : 0,
      } : {}) },
      dataZoom: [{ type: "inside", ...zoom }, ...(isDrawdown ? [{ type: "slider", height: 16, bottom: 4, ...zoom }] : [])],
      series,
    }, true);
  });
  window.echarts.connect(METRIC_CHART_GROUP);
  renderEaComparison(items);

}

function renderHistory() {
  const showingClosed = tradingScope === "closed";
  historyTitle.textContent = showingClosed ? "Operaciones cerradas" : "Registro MT5";
  historyCopy.textContent = showingClosed
    ? "Posiciones reconstruidas de principio a fin. Las métricas usan únicamente operaciones completas y atribuibles a un solo EA."
    : "Evidencia detallada de órdenes, ejecuciones y actividad en curso para investigar qué hizo MT5 o un EA.";
  historyNote.textContent = showingClosed
    ? "Las operaciones intervenidas, incompletas o con Magic mixtos permanecen visibles, pero se excluyen del rendimiento."
    : "Este registro sirve para auditoría y diagnóstico. Sus filas no se mezclan para calcular métricas de rendimiento.";
  historyCountLabel.textContent = showingClosed ? "operaciones cargadas" : "eventos cargados";
  historyCaption.textContent = showingClosed
    ? "Operaciones cerradas reconstruidas por posición"
    : "Registro de entidades informadas por MT5";
  historyMetricsPanel.hidden = !showingClosed;
  document.getElementById("history-heading").hidden = showingClosed;
  document.getElementById("financial-toolbar").hidden = !showingClosed;
  document.getElementById("financial-help").hidden = !showingClosed;
  historyNote.hidden = showingClosed;
  historyEntityField.hidden = showingClosed;
  historyMagic.closest("label").hidden = showingClosed;
  historyMagic.disabled = showingClosed;
  updateFinancialLayout();
  historyBody.closest("table").classList.add("closed-trades-table");
  historyBody.closest("table").classList.toggle("registry-table", !showingClosed);
  renderHistoryHeader(showingClosed);
  const visibleRecords = showingClosed && historyQuery?.magics?.length
    ? historyRecords.filter((item) => historyQuery.magics.includes(item.cycle.owner_magic)) : historyRecords;
  historyBody.replaceChildren(...visibleRecords.map(showingClosed ? positionCycleRow : registryRow));
  historyCount.textContent = number(visibleRecords.length);
  const period = historyQuery ? (historyQuery.endDate
    ? `${historyQuery.days === 365 ? "12 meses" : `${historyQuery.days} días`} hasta ${historyQuery.endDate}`
    : `${historyQuery.days === 1 ? "Últimas 24 horas" : `Últimos ${historyQuery.days} días`}`) : "—";
  const bot = historyQuery?.magic ? `Magic ${historyQuery.magic}` : "todos los bots";
  historyScope.textContent = `${period} · ${showingClosed && historyQuery?.magics?.length ? "Magic " + historyQuery.magics.join(", ") : bot}`
    + (showingClosed ? ` · ${historyRecords.length} registros consultados${historyRecords.length >= HISTORY_CLIENT_LIMIT ? " (límite de consulta alcanzado)" : ""}` : "");
  historyEmpty.hidden = visibleRecords.length > 0;
  if (!historyLoading) {
    historyEmpty.textContent = historyInitialized
      ? `No hay ${showingClosed ? "operaciones cerradas" : "eventos"} guardados para los filtros elegidos.`
      : "Abrí esta sección para consultar el historial.";
    if (showingClosed && !visibleRecords.length && (historyNextCursor || historyRecords.length >= HISTORY_CLIENT_LIMIT)) {
      historyEmpty.textContent = "Sin coincidencias entre los registros cargados. Cargá más o acotá el período si alcanzaste el límite de consulta.";
    }
  }
  historyMore.hidden = !historyNextCursor;
  historyMore.textContent = "Cargar 50 más";
  renderHistoryCoverage();
}

function renderHistoryHeader(showingClosed) {
  const labels = showingClosed
    ? ["Magic", "Tipo", "Símbolo", "Volumen", "Open", "Close", "TP / SL", "PnL neto"]
    : ["Magic", "Entidad", "Símbolo", "Volumen", "Hora broker", "Estado / resultado", "Ticket"];
  const row = document.createElement("tr");
  labels.forEach((label, index) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    if ((showingClosed && [3, 4, 5, 7].includes(index)) || (!showingClosed && [3, 5].includes(index))) {
      cell.className = "numeric";
    }
    cell.textContent = label;
    if (showingClosed && [4, 5].includes(index)) {
      cell.title = "Precio medio y fecha/hora del broker.";
    }
    row.appendChild(cell);
  });
  historyHead.replaceChildren(row);
}

function positionCycleRow(item) {
  const cycle = item.cycle;
  const facts = item.details || {};
  const key = `${cycle.account_id}:${cycle.position_id}`;
  const fragment = document.createDocumentFragment();
  const row = document.createElement("tr");
  row.className = "closed-trade-row";
  const netResult = Number(cycle.observed_net_result);
  const tone = netResult > 0 ? "trade-profit" : netResult < 0 ? "trade-loss" : "";
  if (tone) row.classList.add(tone);
  row.appendChild(textCell(cycle.owner_magic || "Sin atribuir", "trade-magic", "Magic"));
  row.appendChild(detailCell(
    facts.side === "long" ? "Long" : facts.side === "short" ? "Short" : "Mixta / sin determinar",
    `#${cycle.position_id}`, "", "Tipo",
  ));
  row.appendChild(textCell(facts.symbol || "—", "", "Símbolo"));
  row.appendChild(textCell(decimal(facts.volume), "numeric", "Volumen"));
  row.appendChild(detailCell(price(facts.open_price), closedTradeBrokerTime(cycle.started_at_msc), "numeric trade-price", "Open"));
  row.appendChild(detailCell(price(facts.close_price), closedTradeBrokerTime(cycle.last_event_at_msc), "numeric trade-price", "Close"));
  row.appendChild(tradeLevelsCell(facts));
  const result = textCell(money(netResult, latestCurrency, true), "numeric", "PnL neto");
  if (netResult > 0) result.classList.add("positive-text");
  else if (netResult < 0) result.classList.add("negative-text");
  row.appendChild(result);
  const detailRow = document.createElement("tr");
  detailRow.className = `closed-trade-detail ${tone}`;
  detailRow.id = `closed-${cycle.account_id}-${cycle.position_id}`;
  detailRow.hidden = !expandedClosedPositions.has(key);
  const container = document.createElement("td");
  container.className = "trade-detail-panel";
  container.colSpan = 8;
  const list = document.createElement("dl");
  list.className = "trade-facts";
  const add = (label, value, className = "") => {
    const group = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    description.className = className;
    group.append(term, description);
    list.appendChild(group);
  };
  add("Deals", cycle.deal_tickets.join(" · "));
  const opened = operationalTime(cycle.started_at_msc);
  const closed = operationalTime(cycle.last_event_at_msc);
  add("Open · hora local", opened?.local || "No informada");
  add("Close · hora local", closed?.local || "No informada");
  add("Swap", money(facts.swap, latestCurrency, true));
  add("Comisión", money(facts.commission, latestCurrency, true));
  add("Fee", money(facts.fee, latestCurrency, true));
  add("PnL bruto", money(facts.gross_profit, latestCurrency, true));
  add("Pips", "— · tamaño de pip pendiente para este símbolo");
  add("Duración (horas)", decimal(facts.duration_hours));
  container.appendChild(list);
  detailRow.appendChild(container);
  row.tabIndex = 0;
  row.setAttribute("aria-controls", detailRow.id);
  row.setAttribute("aria-expanded", String(!detailRow.hidden));
  row.title = "Mostrar u ocultar detalle · clic, Enter o Espacio";
  const toggleDetail = () => {
    detailRow.hidden = !detailRow.hidden;
    if (detailRow.hidden) expandedClosedPositions.delete(key);
    else expandedClosedPositions.add(key);
    row.setAttribute("aria-expanded", String(!detailRow.hidden));
  };
  row.addEventListener("click", () => {
    const selection = window.getSelection();
    if (selection?.toString() && row.contains(selection.anchorNode)) return;
    toggleDetail();
  });
  row.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (!event.repeat) toggleDetail();
  });
  fragment.append(row, detailRow);
  return fragment;
}

function tradeLevelsCell(facts) {
  const cell = document.createElement("td");
  cell.className = "trade-levels";
  cell.setAttribute("data-label", "TP / SL");
  const fields = facts.side === "short"
    ? [["stop_loss", "SL"], ["take_profit", "TP"]]
    : [["take_profit", "TP"], ["stop_loss", "SL"]];
  fields.forEach(([field, label]) => {
    const line = document.createElement("span");
    line.className = field === "take_profit" ? "positive-text" : "negative-text";
    const value = facts[field];
    line.textContent = `${label} ${value === null || value === undefined || value === 0 ? "—" : price(value)}`;
    cell.appendChild(line);
  });
  cell.title = facts.levels_basis === "current" ? "Niveles de la última captura"
    : facts.levels_basis === "exit_order" ? "Niveles registrados al cierre"
    : facts.levels_basis === "initial_order" ? "Niveles iniciales; cambios posteriores no confirmados"
      : "Sin evidencia de TP/SL";
  return cell;
}

function closedTradeBrokerTime(msc) {
  if (!Number.isSafeInteger(msc)) return "—";
  const date = new Date(msc);
  return Number.isNaN(date.getTime()) ? "—" : brokerRowTimeFormatter.format(date);
}

function registryRow(record) {
  const row = document.createElement("tr");
  if (record._entity === "deal") appendDealRegistryCells(row, record);
  else if (record._entity === "order") appendOrderRegistryCells(row, record);
  else appendCurrentRegistryCells(row, record);
  const cells = [...row.children];
  const timeMsc = historyRecordTime(record);
  const validTime = Number.isFinite(timeMsc) && timeMsc !== Number.MAX_SAFE_INTEGER ? timeMsc : null;
  row.replaceChildren(cells[2], cells[0], cells[1], cells[3],
    textCell(closedTradeBrokerTime(validTime), "trade-price", "Hora broker"), cells[4], cells[5]);
  cells[2].classList.add("trade-magic");
  const fields = [["Hora local", operationalTime(validTime)?.local || "No informada"]];
  if (record._entity === "deal") {
    fields.push(["Precio", price(record.price)], ["PnL bruto", money(record.profit, latestCurrency, true)],
      ["Swap", money(record.swap, latestCurrency, true)], ["Comisión", money(record.commission, latestCurrency, true)],
      ["Otros cargos", money(record.fee, latestCurrency, true)]);
  } else if (record._entity === "order") {
    fields.push(["Precio solicitado", price(record.price_open)],
      ["Volumen restante", decimal(record.volume_current)], ["SL", price(record.stop_loss)],
      ["TP", price(record.take_profit)]);
  } else {
    fields.push(["Precio de apertura", price(record.price_open)], ["Precio actual", price(record.price_current)],
      ["SL", price(record.stop_loss)], ["TP", price(record.take_profit)]);
  }
  if (record.comment) fields.push(["Comentario", record.comment]);
  const key = `${currentFilterScope}:${record._entity}:${record.kind || ""}:${record.ticket}`;
  const fragment = document.createDocumentFragment();
  fragment.append(...expandableRecordRows(row, fields, `registry-${encodeURIComponent(key)}`,
    expandedRegistryRecords, key));
  return fragment;
}

function appendDealRegistryCells(row, deal) {
  const type = dealTypes[deal.deal_type] || `Tipo ${deal.deal_type}`;
  const entry = dealEntries[deal.entry] || `Entrada ${deal.entry}`;
  row.appendChild(detailCell("Ejecución", `${type} · ${entry}`, "", "Entidad"));
  row.appendChild(detailCell(deal.symbol || "Cuenta", `Posición #${deal.position_id}`, "", "Símbolo"));
  row.appendChild(textCell(String(deal.magic_number), "", "Magic"));
  row.appendChild(textCell(decimal(deal.volume), "numeric", "Volumen"));
  const net = deal.profit + deal.commission + deal.swap + deal.fee;
  const result = textCell(money(net, latestCurrency, true), "numeric", "Estado / resultado");
  if (net > 0) result.classList.add("positive-text");
  else if (net < 0) result.classList.add("negative-text");
  row.appendChild(result);
  row.appendChild(textCell(`Deal #${deal.ticket}`, "", "Identificador"));
}

function appendOrderRegistryCells(row, order) {
  const type = historicalOrderTypes[order.order_type] || `Tipo ${order.order_type}`;
  row.appendChild(detailCell("Orden", type, "", "Entidad"));
  const position = order.position_id && order.position_id !== "0"
    ? `Posición #${order.position_id}` : "Sin posición asociada";
  row.appendChild(detailCell(order.symbol || "Cuenta", position, "", "Símbolo"));
  row.appendChild(textCell(String(order.magic_number), "", "Magic"));
  row.appendChild(textCell(decimal(order.volume_initial), "numeric", "Volumen"));
  const state = historicalOrderStates[order.state] || `Estado ${order.state}`;
  const stateCell = textCell(state, "numeric", "Estado / resultado");
  if ([2, 5, 6].includes(order.state)) stateCell.classList.add("warn-text");
  row.appendChild(stateCell);
  row.appendChild(textCell(`Orden #${order.ticket}`, "", "Identificador"));
}

function appendCurrentRegistryCells(row, operation) {
  const kind = operation.kind === "position" ? "Posición en curso" : "Orden pendiente";
  const type = operationTypes[operation.operation_type] || operation.operation_type;
  row.appendChild(detailCell(kind, type, "", "Entidad"));
  row.appendChild(textCell(operation.symbol, "", "Símbolo"));
  row.appendChild(textCell(String(operation.magic_number), "", "Magic"));
  row.appendChild(textCell(decimal(operation.volume), "numeric", "Volumen"));
  const value = operation.kind === "position" && Number.isFinite(operation.floating_profit)
    ? money(operation.floating_profit, latestCurrency, true) : "Pendiente";
  row.appendChild(textCell(value, "numeric", "Estado / resultado"));
  row.appendChild(textCell(`#${operation.ticket}`, "", "Identificador"));
}

function elapsed(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

function currentFreshnessAge() {
  if (latestAgeAtResponse === null) return null;
  return Math.max(0, latestAgeAtResponse + (performance.now() - latestAgeMarkedAt) / 1000);
}

function updateFreshness() {
  if (latestHealthState) renderHealthOverview(latestHealthState);
  if (!latestObservedDate) {
    setText(elements.freshness, serviceReachable ? "Esperando primera captura" : "Sin una lectura válida todavía");
    return;
  }
  const ageSeconds = currentFreshnessAge();
  if (ageSeconds === null) return;
  const staleAfter = latestCaptureIntervalSeconds + latestFreshnessToleranceSeconds;
  const criticalAfter = 3 * latestCaptureIntervalSeconds + latestFreshnessToleranceSeconds;
  const staleData = !serviceReachable || latestStatus !== "connected" || ageSeconds > staleAfter;
  const criticalAge = !serviceReachable || ageSeconds > criticalAfter;
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
  const key = `${operation.kind}-${operation.ticket}`;
  const row = document.createElement("tr");
  row.appendChild(textCell(String(operation.magic_number), "trade-magic", "Magic"));
  const kind = operation.kind === "position" ? "Posición" : "Orden pendiente";
  const type = operationTypes[operation.operation_type] || operation.operation_type;
  row.appendChild(detailCell(type, kind, "", "Tipo"));
  row.appendChild(textCell(operation.symbol, "", "Símbolo"));
  row.appendChild(textCell(decimal(operation.volume), "numeric", "Volumen"));
  const opened = operationalTime(operation.opened_at);
  const openedMsc = typeof operation.opened_at === "string" ? Date.parse(operation.opened_at) : operation.opened_at;
  row.appendChild(detailCell(price(operation.price_open), closedTradeBrokerTime(openedMsc), "numeric trade-price", "Open"));
  row.appendChild(textCell(price(operation.price_current), "numeric", "Actual"));
  row.appendChild(tradeLevelsCell({
    ...operation, side: String(operation.operation_type).startsWith("sell") ? "short" : "long",
    levels_basis: "current",
  }));
  const profit = operation.kind === "position" ? operation.floating_profit : null;
  row.appendChild(textCell(operation.kind === "order" ? "No aplica" : money(profit, latestCurrency, true),
    `numeric ${profit > 0 ? "positive-text" : profit < 0 ? "negative-text" : ""}`, "PnL flotante"));
  return expandableRecordRows(row, [
    ["Ticket", String(operation.ticket)],
    ["Hora local", opened?.local || "No informada"],
    ["Comentario", operation.comment || "Sin comentario"],
  ], `operation-detail-${key}`, expandedOperationTickets, key);
}

const expandedRegistryRecords = new Set();

function expandableRecordRows(row, fields, id, expanded, key) {
  row.classList.add("closed-trade-row");
  row.tabIndex = 0;
  row.setAttribute("aria-controls", id);
  row.setAttribute("aria-expanded", String(expanded.has(key)));
  row.title = "Mostrar u ocultar detalle · clic, Enter o Espacio";
  const detail = document.createElement("tr");
  detail.className = "closed-trade-detail";
  detail.id = id;
  detail.hidden = !expanded.has(key);
  const cell = document.createElement("td");
  cell.className = "trade-detail-panel";
  cell.colSpan = row.children.length;
  const list = document.createElement("dl");
  list.className = "trade-facts";
  fields.forEach(([label, value]) => {
    const group = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    group.append(term, description);
    list.appendChild(group);
  });
  cell.appendChild(list);
  detail.appendChild(cell);
  // Resolve the live sibling: current rows are reconciled in place on every capture.
  const toggle = () => {
    const liveDetail = document.getElementById(id);
    if (!liveDetail) return;
    if (expanded.has(key)) expanded.delete(key);
    else expanded.add(key);
    row.setAttribute("aria-expanded", String(expanded.has(key)));
    liveDetail.hidden = !expanded.has(key);
  };
  row.addEventListener("click", () => {
    const selection = window.getSelection();
    if (selection?.toString() && row.contains(selection.anchorNode)) return;
    toggle();
  });
  row.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    if (!event.repeat) toggle();
  });
  return [row, detail];
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

function accountChartSeries(timeline, key, gapThreshold, bucketWindow = null) {
  const data = [];
  let gaps = 0;
  timeline.forEach((item, index) => {
    const timestamp = item.at.getTime();
    const previous = index > 0 ? timeline[index - 1].at.getTime() : null;
    const missingBucket = bucketWindow && previous !== null
      && Math.floor((timestamp - bucketWindow.fromMsc) / bucketWindow.bucketMsc)
        - Math.floor((previous - bucketWindow.fromMsc) / bucketWindow.bucketMsc) > 1;
    if (previous !== null && (missingBucket || timestamp - previous > gapThreshold)) {
      data.push([Math.max(previous + 1, timestamp - 1), null]);
      gaps += 1;
    }
    data.push([timestamp, item[key]]);
  });
  return { data, gaps };
}

async function loadAccountHistory() {
  const request = ++accountHistoryRequest;
  const value = document.getElementById("account-history-period").value;
  const status = document.getElementById("account-chart-status");
  if (value === "live") {
    accountHistoryWindow = null; accountHistoryData = null;
    status.textContent = "Evolución reciente";
    renderChart(lastHistory, latestIntervalSeconds);
    return;
  }
  try {
    accountHistoryWindow = selectedTimeWindow(Number(value), document.getElementById("account-history-end").value);
  } catch (error) { status.textContent = error.message; return; }
  accountHistoryData = null;
  accountChart?.clear();
  status.textContent = "Consultando historial…";
  chartEmpty.hidden = false; chartEmpty.textContent = "Consultando historial…";
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  try {
    const parameters = new URLSearchParams({ from_msc: String(accountHistoryWindow.fromMsc), to_msc: String(accountHistoryWindow.toMsc) });
    const response = await fetch(`/api/account-history?${parameters}`, { cache: "no-store", signal: controller.signal });
    if (response.status === 401) { window.location.assign("/login"); return; }
    if (!response.ok) throw new Error("Historial no disponible. Comprobá que el servidor y el receptor estén actualizados.");
    const payload = await response.json();
    if (request !== accountHistoryRequest) return;
    if (!Array.isArray(payload.points) || !Number.isFinite(payload.bucket_msc)) throw new Error("Respuesta histórica inválida.");
    accountHistoryData = payload;
    status.textContent = payload.points.length ? `${payload.points.length} observaciones disponibles` : "Sin observaciones guardadas para este período";
    status.title = "Muestras históricas conservadas, agrupadas por intervalo. No reconstruye equity entre capturas ni antes de comenzar a recopilar datos.";
    renderChart(lastHistory, latestIntervalSeconds);
  } catch (error) {
    if (request !== accountHistoryRequest) return;
    status.textContent = error.name === "AbortError" ? "La consulta tardó demasiado. Probá un período menor." : error.message;
    chartEmpty.textContent = "No se pudo cargar el historial.";
  } finally { window.clearTimeout(timeout); }
}
document.getElementById("account-history-apply").addEventListener("click", loadAccountHistory);

function renderChart(history, intervalSeconds) {
  if (accountHistoryWindow) {
    if (!accountHistoryData) return;
    history = accountHistoryData.points;
    intervalSeconds = accountHistoryData.bucket_msc / 1000;
  }
  const timeline = history
    .map((item) => ({ ...item, at: toDate(item.observed_at) }))
    .filter((item) => item.at && Number.isFinite(item.balance) && Number.isFinite(item.equity))
    .sort((left, right) => left.at - right.at);
  if (timeline.length < (accountHistoryWindow ? 1 : 2)) {
    chartEmpty.hidden = false;
    chartEmpty.textContent = accountHistoryWindow ? "Sin observaciones guardadas en este período." : "Recolectando observaciones…";
    if (accountChart) accountChart.clear();
    chart.setAttribute("aria-label", "Evolución reciente de balance y equity");
    chartSpan.textContent = "";
    return;
  }
  if (!window.echarts) {
    chartEmpty.hidden = false;
    chartEmpty.textContent = "La librería de gráficos no pudo cargarse.";
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
  const bucketWindow = accountHistoryWindow ? { ...accountHistoryWindow, bucketMsc: accountHistoryData.bucket_msc } : null;
  const balance = accountChartSeries(timeline, "balance", gapThreshold, bucketWindow);
  const equity = accountChartSeries(timeline, "equity", gapThreshold, bucketWindow);
  const gaps = balance.gaps;
  const spanSeconds = Math.max(0, timeRange / 1000);
  const span = elapsed(spanSeconds);
  const interruption = gaps
    ? ` · ${gaps} ${gaps === 1 ? "interrupción" : "interrupciones"}`
    : "";
  chartSpan.textContent = `Mín ${money(minimum, latestCurrency)} · Máx ${money(maximum, latestCurrency)} · Ventana ${span}${interruption}`;
  chart.setAttribute(
    "aria-label",
    `Evolución de balance y equity, ventana ${span}${gaps ? `, ${gaps} interrupciones de captura` : ""}`,
  );
  const { ink, grid: gridColor, axis, surface, accent } = resolvedChartTheme();
  accountChart ||= window.echarts.init(chart);
  const windowKey = accountHistoryWindow ? JSON.stringify(accountHistoryWindow) : "live";
  const previousZoom = accountChartWindowKey === windowKey ? accountChart.getOption().dataZoom?.[0] : null;
  const zoom = previousZoom ? { start: previousZoom.start, end: previousZoom.end } : { start: 0, end: 100 };
  accountChartWindowKey = windowKey;
  const seriesTooltip = {
    valueFormatter: (value) => money(Array.isArray(value) ? value[1] : value, latestCurrency),
  };
  accountChart.setOption({
    animationDuration: 250,
    aria: { enabled: true },
    grid: { left: 12, right: 12, top: 14, bottom: 42, containLabel: true },
    dataZoom: [{ type: "inside", ...zoom }, { type: "slider", height: 16, bottom: 4, ...zoom }],
    textStyle: { color: ink },
    tooltip: {
      trigger: "axis",
      backgroundColor: surface,
      borderColor: axis,
      textStyle: { color: ink },
      axisPointer: { type: "line", lineStyle: { color: axis, type: "dashed", width: 1 } },
    },
    xAxis: {
      type: "time",
      min: accountHistoryWindow?.fromMsc ?? startAt.getTime(),
      max: accountHistoryWindow?.toMsc ?? endAt.getTime(),
      axisLabel: { color: ink, hideOverlap: true, formatter: (value) => accountHistoryWindow
        ? new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit" }).format(new Date(value))
        : timeFormatter.format(new Date(value)) },
      axisLine: { lineStyle: { color: axis } },
      axisTick: { lineStyle: { color: axis } },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      min: low,
      max: high,
      axisLabel: { color: ink, formatter: (value) => money(value, latestCurrency) },
      splitLine: { lineStyle: { color: gridColor } },
    },
    series: [
      {
        name: "Balance",
        type: "line",
        data: balance.data,
        connectNulls: false,
        showSymbol: timeline.length === 1,
        itemStyle: { color: ink },
        lineStyle: { color: ink, width: 2, type: "dashed" },
        emphasis: { disabled: true },
        tooltip: seriesTooltip,
        markLine: {
          silent: true,
          symbol: "none",
          label: { show: false },
          lineStyle: { color: axis, width: 1, type: "dotted" },
          data: [{ yAxis: timeline[0].balance }],
        },
      },
      {
        name: "Equity",
        type: "line",
        data: equity.data,
        connectNulls: false,
        showSymbol: timeline.length === 1,
        itemStyle: { color: accent },
        lineStyle: { color: accent, width: 2 },
        emphasis: { disabled: true },
        tooltip: seriesTooltip,
      },
    ],
  }, true);
}

let retryMultiplier = 1;

async function loadRuntimeConfig() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (response.status === 401) {
      window.location.assign("/login");
      return;
    }
    if (!response.ok) return;
    const config = await response.json();
    if (Number.isInteger(config.broker_utc_offset_minutes)) {
      brokerUtcOffsetMinutes = config.broker_utc_offset_minutes;
    }
  } catch (_) {
    brokerUtcOffsetMinutes = null;
  }
}

async function performRefresh() {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    2 * latestIntervalSeconds * 1000,
  );
  try {
    const query = lastPollSince ? `?since=${encodeURIComponent(lastPollSince)}` : "";
    const response = await fetch(`/api/state${query}`, { cache: "no-store", signal: controller.signal });
    if (response.status === 401) {
      window.location.assign("/login");
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    serviceReachable = true;
    renderState(await response.json());
    retryMultiplier = 1;
  } catch (_) {
    serviceReachable = false;
    setText(elements.status, "Sin conexión local");
    statusDot.className = "status-dot degraded";
    updateFreshness();
    if (activeView === "trading" && tradingScope === "current") renderOperations();
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

window.setInterval(updateFreshness, 1000);

function activateTradingScope(scope) {
  if (!["current", "closed", "registry"].includes(scope)) return;
  const scopeChanged = tradingScope !== scope;
  tradingScope = scope;
  tradingCurrentPanel.hidden = scope !== "current";
  tradingHistoryPanel.hidden = scope === "current";
  if (scopeChanged) {
    historyRecords = [];
    historyNextCursor = null;
    historyNextCursors = { deals: null, orders: null };
    historyInitialized = false;
    historyQuery = null;
    historyRequest += 1;
    metricsRequest += 1;
    setHistoryLoading(false);
  }
  if (scope === "current") {
    renderOperations();
    return;
  }
  renderHistory();
  if (!historyInitialized) loadTradingHistory();
  if (scope === "closed") {
    window.requestAnimationFrame(() => metricCharts.forEach((chart) => chart.resize()));
  }
}

function activateView(view) {
  const titles = {
    overview: "Resumen", trading: "Trading", financial: "Performance financiera",
    execution: "Performance de ejecución", activity: "Actividad",
  };
  setText(document.getElementById("page-title"), titles[view]);
  document.querySelectorAll(".view-tab").forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".dashboard-view").forEach((panel) => {
    const panelView = ["financial", "execution"].includes(view) ? "trading" : view;
    panel.hidden = panel.id !== `${panelView}-view`;
    if (!panel.hidden) panel.setAttribute("aria-labelledby", `tab-${view}`);
  });
  activeView = view;
  if (["trading", "financial", "execution"].includes(view)) {
    activateTradingScope({ trading: "current", financial: "closed", execution: "registry" }[view]);
  }
  else if (activeView === "activity") renderActivity();
  else {
    renderChart(lastHistory, latestIntervalSeconds);
    refreshEaRanking();
    window.requestAnimationFrame(() => accountChart?.resize());
  }
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

function viewFromRoute(route) {
  const aliases = {
    operations: "trading", history: "execution",
    "trading/current": "trading", "trading/closed": "financial", "trading/registry": "execution",
  };
  const view = aliases[route] || route;
  return ["overview", "trading", "financial", "execution", "activity"].includes(view) ? view : "overview";
}

window.addEventListener("hashchange", () => activateView(viewFromRoute(location.hash.slice(1))));

let chartResizeFrame = null;
window.addEventListener("resize", () => {
  if (chartResizeFrame !== null) window.cancelAnimationFrame(chartResizeFrame);
  chartResizeFrame = window.requestAnimationFrame(() => {
    metricCharts.forEach((chart) => chart.resize());
    if (accountChart && activeView === "overview") accountChart.resize();
    chartResizeFrame = null;
  });
});

document.getElementById("secondary-metrics").addEventListener("toggle", (event) => {
  if (event.currentTarget.open) window.requestAnimationFrame(() => metricCharts.forEach((chart) => chart.resize()));
});

new MutationObserver(() => {
  if (historyMetrics) renderMetricCharts(historyMetrics.series);
  if (activeView === "overview") renderChart(lastHistory, latestIntervalSeconds);
}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!document.documentElement.dataset.theme) {
    if (historyMetrics) renderMetricCharts(historyMetrics.series);
    if (activeView === "overview") renderChart(lastHistory, latestIntervalSeconds);
  }
});
const FILTER_STORE = "tradinglab-dashboard-filters";

function loadStoredFilters(scope) {
  currentFilterScope = scope;
  accountHistoryRequest += 1;
  accountHistoryWindow = null;
  accountHistoryData = null;
  accountChartWindowKey = null;
  document.getElementById("account-history-period").value = "live";
  document.getElementById("account-chart-status").textContent = "Evolución reciente";
  expandedOperationTickets.clear();
  expandedRegistryRecords.clear();
  selectedEaMagics.clear();
  comparedEaMagics.clear();
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
historyFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  document.getElementById("ea-selector").open = false;
  loadTradingHistory();
});
historyReset.addEventListener("click", () => {
  historyPeriod.value = "7";
  historyMagic.value = "";
  historyMagic.setCustomValidity("");
  selectedEaMagics.clear();
  comparedEaMagics.clear();
  document.getElementById("history-end-date").value = "";
  renderComparisonOptions();
  updateEaSelectionLabel();
  loadTradingHistory();
});
historyEntity.addEventListener("change", () => {
  historyRecords = [];
  historyNextCursor = null;
  historyNextCursors = { deals: null, orders: null };
  historyCoverageByEntity = {};
  historyInitialized = false;
  historyQuery = null;
  historyRequest += 1;
  setHistoryLoading(false);
  loadTradingHistory();
});
historyMore.addEventListener("click", () => loadTradingHistory({ append: true }));
function scheduleRefresh() {
  window.setTimeout(() => {
    refresh().finally(scheduleRefresh);
  }, latestIntervalSeconds * 1000 * retryMultiplier);
}

function initializeDashboard() {
  activateView(viewFromRoute(location.hash.slice(1)));
  refresh().finally(scheduleRefresh);
}
loadRuntimeConfig().finally(initializeDashboard);
