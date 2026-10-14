"use strict";

const ids = [
  "status", "freshness", "source", "account", "server", "currency", "balance",
  "equity", "profit", "margin-free", "margin-level", "positions", "orders", "margin"
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const statusDot = document.getElementById("status-dot");
const errorBox = document.getElementById("error");
const profitCard = document.getElementById("profit-card");
const chartEmpty = document.getElementById("chart-empty");
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

function money(value, currency) {
  if (!Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat("es-ES", { style: "currency", currency }).format(value);
  } catch (_) {
    return `${value.toFixed(2)} ${currency}`;
  }
}

function number(value) {
  return Number.isFinite(value) ? new Intl.NumberFormat("es-ES").format(value) : "—";
}

function renderState(state) {
  elements.status.textContent = state.status === "connected" ? "Conectado" : "Lectura degradada";
  statusDot.className = `status-dot ${state.status}`;
  errorBox.hidden = !state.error;
  errorBox.textContent = state.error || "";
  if (!state.latest) return;

  const value = state.latest;
  elements.source.textContent = value.source.toUpperCase();
  elements.account.textContent = value.account_reference;
  elements.server.textContent = value.server;
  elements.currency.textContent = value.currency || "—";
  elements.balance.textContent = money(value.balance, value.currency);
  elements.equity.textContent = money(value.equity, value.currency);
  elements.profit.textContent = money(value.floating_profit, value.currency);
  elements["margin-free"].textContent = money(value.margin_free, value.currency);
  elements["margin-level"].textContent = value.margin_level === null
    ? "Nivel —"
    : `Nivel ${number(value.margin_level)}%`;
  elements.positions.textContent = number(value.open_positions);
  elements.orders.textContent = number(value.active_orders);
  elements.margin.textContent = money(value.margin, value.currency);
  elements.freshness.textContent = `Última lectura ${new Date(value.observed_at).toLocaleTimeString("es-ES")}`;
  profitCard.classList.toggle("positive", value.floating_profit >= 0);
  profitCard.classList.toggle("negative", value.floating_profit < 0);
  latestOperations = Array.isArray(value.operations) ? value.operations : [];
  latestCurrency = value.currency || "USD";
  renderOperations();
  renderChart(state.history);
}

function renderOperations() {
  const filter = magicFilter.value.trim();
  const filtered = latestOperations.filter((operation) => (
    !filter || String(operation.magic_number).includes(filter)
  ));
  const magicNumbers = [...new Set(latestOperations.map((item) => String(item.magic_number)))];
  magicNumbers.sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  magicOptions.replaceChildren(...magicNumbers.map((magic) => {
    const option = document.createElement("option");
    option.value = magic;
    return option;
  }));

  operationsBody.replaceChildren(...filtered.map(operationRow));
  operationsEmpty.hidden = filtered.length > 0;
  operationsEmpty.textContent = latestOperations.length === 0
    ? "MT5 no informa operaciones activas."
    : "Ninguna operaciÃ³n coincide con ese magic number.";
  operationsBadge.textContent = number(latestOperations.length);
  visibleOperations.textContent = number(filtered.length);
  visiblePositions.textContent = number(filtered.filter((item) => item.kind === "position").length);
  visibleOrders.textContent = number(filtered.filter((item) => item.kind === "order").length);
  clearFilter.disabled = !filter;
}

function operationRow(operation) {
  const row = document.createElement("tr");
  const kind = operation.kind === "position" ? "PosiciÃ³n" : "Orden";
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
    profit.textContent = money(operation.floating_profit, latestCurrency);
    profit.classList.add(operation.floating_profit >= 0 ? "positive" : "negative");
  } else {
    profit.textContent = "—";
  }
  row.appendChild(profit);
  row.appendChild(textCell(operation.opened_at
    ? new Date(operation.opened_at).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "medium" })
    : "—"));
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
  cell.append(strong, small);
  return cell;
}

function decimal(value) {
  return Number.isFinite(value)
    ? new Intl.NumberFormat("es-ES", { maximumFractionDigits: 4 }).format(value)
    : "—";
}

function price(value) {
  return Number.isFinite(value)
    ? new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(value)
    : "—";
}

function renderChart(history) {
  if (history.length < 2) {
    chartEmpty.hidden = false;
    balanceLine.setAttribute("points", "");
    equityLine.setAttribute("points", "");
    return;
  }
  chartEmpty.hidden = true;
  const values = history.flatMap((item) => [item.balance, item.equity]);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
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
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderState(await response.json());
  } catch (_) {
    elements.status.textContent = "Sin conexión local";
    statusDot.className = "status-dot degraded";
    errorBox.hidden = false;
    errorBox.textContent = "No se pudo consultar el servicio local.";
  }
}

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
  });
});
magicFilter.addEventListener("input", renderOperations);
clearFilter.addEventListener("click", () => {
  magicFilter.value = "";
  magicFilter.focus();
  renderOperations();
});
refresh();
window.setInterval(refresh, 2000);
