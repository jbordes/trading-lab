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
  renderChart(state.history);
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
refresh();
window.setInterval(refresh, 2000);
