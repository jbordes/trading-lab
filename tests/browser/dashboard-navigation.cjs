/* Deterministic frontend checks: no browser, server, credentials or live account. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../src/tradinglab/dashboard/static/app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../../src/tradinglab/dashboard/static/dashboard.html'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../../src/tradinglab/dashboard/static/styles.css'), 'utf8');
assert.match(css, /\.comparison-sidebar\s*\{[^}]*position:\s*sticky;[^}]*top:\s*16px;/s);
assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.comparison-sidebar\s*\{\s*position:\s*static;/);
assert.ok(html.indexOf('id="summary-metrics"') < html.indexOf('id="chart-cumulative"'));
assert.ok(html.indexOf('id="chart-cumulative"') < html.indexOf('id="chart-drawdown"'));
assert.ok(html.indexOf('id="chart-drawdown"') < html.indexOf('id="secondary-metrics"'));
assert.ok(html.indexOf('id="secondary-metrics"') < html.indexOf('id="ea-comparison"'));
function definition(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from);
  return source.slice(from, to);
}
class Element {
  constructor(id = '') { this.id = id; this.children = []; this.attrs = {}; this.events = {}; }
  classList = { add() {}, toggle() {} };
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.append(node); }
  addEventListener(name, handler) { this.events[name] = handler; }
}
const tabs = ['overview', 'trading', 'financial', 'execution', 'activity'].map((view) => {
  const tab = new Element(); tab.dataset = { view }; return tab;
});
const panels = ['overview-view', 'trading-view', 'activity-view'].map((id) => new Element(id));
const nodes = new Map([['page-title', new Element()]]);
let selectedScope;
const context = vm.createContext({
  document: {
    createElement: () => new Element(),
    getElementById: (id) => nodes.get(id),
    querySelectorAll: (selector) => selector === '.view-tab' ? tabs : panels,
  },
  window: { requestAnimationFrame: (fn) => fn(), getSelection: () => null },
  setText: (node, text) => { node.textContent = text; },
  activateTradingScope: (scope) => { selectedScope = scope; },
  renderActivity() {}, renderChart() {}, accountChart: null, lastHistory: [], latestIntervalSeconds: 5,
});
vm.runInContext('let activeView = "overview";', context);
vm.runInContext(definition('function viewFromRoute(', 'window.addEventListener("hashchange"'), context);
vm.runInContext(definition('function activateView(', '\ndocument.querySelectorAll(".view-tab").forEach'), context);
for (const [route, view, scope] of [
  ['trading', 'trading', 'current'], ['financial', 'financial', 'closed'],
  ['execution', 'execution', 'registry'], ['trading/closed', 'financial', 'closed'],
  ['history', 'execution', 'registry'], ['operations', 'trading', 'current'],
]) {
  vm.runInContext(`activateView(viewFromRoute(${JSON.stringify(route)}))`, context);
  assert.equal(selectedScope, scope);
  assert.equal(panels[1].hidden, false);
  assert.equal(panels[1].attrs['aria-labelledby'], `tab-${view}`);
  assert.equal(tabs.filter((tab) => tab.attrs['aria-selected'] === 'true')[0].dataset.view, view);
}
assert.equal(vm.runInContext('viewFromRoute("unknown")', context), 'overview');
vm.runInContext(definition('function eaColor(', 'function renderEaComparison('), context);
const color = vm.runInContext('eaColor("11122")', context);
assert.equal(color, vm.runInContext('eaColor("11122")', context));
assert.notEqual(color, vm.runInContext('eaColor("11123")', context));
context.eaItems = [
  { magic_number: '3', net_profit: -7 }, { magic_number: '2', net_profit: 5 },
  { magic_number: '1', net_profit: 5 }, { magic_number: '4', net_profit: 0 },
];
assert.equal(vm.runInContext('rankedEas(eaItems).map(ea => ea.magic_number).join(",")', context), '1,2,4,3');
assert.equal(context.eaItems[0].magic_number, '3');
vm.runInContext(definition('function eaChartSeries(', 'function renderMetricCharts('), context);
context.chartItems = [
  { magic_number: '11122', series: [{ time_msc: 100, net_profit: 5, cumulative_profit: 5, drawdown: 0, rolling_average_20: 5 }] },
  { magic_number: '11123', series: [{ time_msc: 200, net_profit: -2, cumulative_profit: -2, drawdown: 2, rolling_average_20: -2 }] },
];
const trades = vm.runInContext('eaChartSeries(chartItems, "net_profit", 0)', context);
assert.equal(trades[0].type, 'bar');
assert.equal(trades[0].smooth, false);
assert.equal(trades[0].showSymbol, false);
assert.equal(trades[0].data[0].value[0], 100);
assert.equal(trades[1].data[0].value[0], 200);
assert.equal(trades[0].data[0].label.position, 'top');
assert.equal(trades[1].data[0].label.position, 'bottom');
assert.equal(vm.runInContext('eaChartSeries(chartItems, "net_profit", 0, true)[0].type', context), 'bar');
const curves = vm.runInContext('eaChartSeries(chartItems, "cumulative_profit", 0)', context);
assert.equal(curves[0].type, 'line');
assert.equal(curves[0].smooth, false);
assert.equal(curves[0].showSymbol, false);
assert.equal(curves[0].step, undefined);
assert.equal(curves[0].data[0][1], 0);
assert.equal(curves[0].itemStyle.color, trades[0].itemStyle.color);
assert.notEqual(curves[0].itemStyle.color, curves[1].itemStyle.color);
assert.equal(vm.runInContext('eaChartSeries(chartItems, "drawdown", 0)[1].data.at(-1)[1]', context), -2);
vm.runInContext(definition('function selectedTimeWindow(', 'async function loadTradingHistory('), context);
context.brokerUtcOffsetMinutes = 120;
context.now = Date.UTC(2026, 9, 28, 12);
assert.equal(vm.runInContext('selectedTimeWindow(365, "", false, now).fromMsc', context), Date.UTC(2025, 9, 28, 12));
assert.equal(vm.runInContext('selectedTimeWindow(7, "2026-10-20", false, now).toMsc', context), Date.UTC(2026, 9, 21));
assert.throws(() => vm.runInContext('selectedTimeWindow(7, "2026-02-30", false, now)', context));
assert.throws(() => vm.runInContext('selectedTimeWindow(7, "2027-01-01", false, now)', context));
assert.throws(() => vm.runInContext('selectedTimeWindow(999, "", false, now)', context));
vm.runInContext(definition('function accountChartSeries(', 'async function loadAccountHistory('), context);
context.timeline = [{ at: new Date(1000), balance: 10 }, { at: new Date(121000), balance: 12 }];
assert.equal(vm.runInContext('accountChartSeries(timeline, "balance", 150000, {fromMsc: 0, bucketMsc: 60000}).gaps', context), 1);
context.historyMetrics = { from_msc: 0, to_msc: 300, series: context.chartItems[0].series, by_ea: context.chartItems };
context.historyQuery = { magics: ['11122', '11123'] };
context.financialMode = 'summary';
context.MAX_COMPARISON_EAS = 5;
context.metricChartWindowKey = null;
context.METRIC_CHART_GROUP = 'financial-performance';
context.metricsStatus = new Element();
context.metricCharts = new Map();
context.resolvedChartTheme = () => ({ ink: '#111', grid: '#ddd', axis: '#999', surface: '#fff', accent: '#abc', profit: '#090', loss: '#900' });
context.operationalChartLabel = String;
context.renderEaComparison = () => {};
context.window.echarts = {
  connect(group) { context.connectedChartGroup = group; },
  init: () => ({ setOption(option) { this.option = option; }, dispatchAction() {}, getOption() { return this.option || {}; } }),
};
vm.runInContext(definition('function renderMetricCharts(', 'function renderHistory('), context);
vm.runInContext('renderMetricCharts()', context);
assert.equal(context.metricCharts.get('chart-cumulative').option.series.length, 1);
assert.equal(context.metricCharts.get('chart-cumulative').option.series[0].name, 'Conjunto seleccionado');
assert.equal(context.metricCharts.get('chart-cumulative').option.dataZoom.length, 1);
assert.equal(context.metricCharts.get('chart-drawdown').option.dataZoom.length, 2);
assert.equal(context.metricCharts.get('chart-profit').option.series[0].type, 'bar');
assert.equal(context.connectedChartGroup, 'financial-performance');
context.financialMode = 'compare';
vm.runInContext('renderMetricCharts()', context);
assert.equal(context.metricCharts.get('chart-cumulative').option.series.length, 2);
assert.equal(context.metricCharts.get('chart-profit').option.series[0].type, 'bar');
assert.equal(context.metricCharts.get('chart-cumulative').option.legend.show, false);
assert.equal(context.metricCharts.get('chart-drawdown').option.yAxis.max, 0);
context.historyQuery.magics = [];
vm.runInContext('renderMetricCharts()', context);
assert.equal(context.metricCharts.get('chart-cumulative').option.series.length, 0);
vm.runInContext(definition('function expandableRecordRows(', 'function textCell('), context);
const expanded = new Set();
const row = new Element(); row.append(new Element(), new Element());
context.row = row; context.expanded = expanded;
const pair = vm.runInContext('expandableRecordRows(row, [["Ticket", "123"]], "detail-123", expanded, "123")', context);
nodes.set('detail-123', pair[1]);
assert.equal(pair[1].hidden, true);
row.events.click();
assert.equal(pair[1].hidden, false);
assert.equal(row.attrs['aria-expanded'], 'true');
assert.ok(expanded.has('123'));
// A refreshed detail must inherit expansion and remain toggleable by the original row.
context.nextRow = new Element(); context.nextRow.append(new Element(), new Element());
const refreshed = vm.runInContext('expandableRecordRows(nextRow, [["Ticket", "123"]], "detail-123", expanded, "123")', context);
assert.equal(refreshed[1].hidden, false);
nodes.set('detail-123', refreshed[1]);
let prevented = false;
row.events.keydown({ key: 'Enter', repeat: false, preventDefault() { prevented = true; } });
assert.ok(prevented);
assert.equal(refreshed[1].hidden, true);
assert.equal(row.attrs['aria-expanded'], 'false');
assert.equal(expanded.size, 0);
row.events.keydown({ key: ' ', repeat: true, preventDefault() {} });
assert.equal(refreshed[1].hidden, true);
console.log('Dashboard navigation and expandable rows: OK');
