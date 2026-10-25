from __future__ import annotations

import gzip
import http.client
import http.cookiejar
import json
import shutil
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from tradinglab.dashboard.service import LiveDashboardService  # noqa: E402
from tradinglab.dashboard.snapshot import (  # noqa: E402
    DemoSnapshotSource,
    LiveSnapshot,
    Mt5SnapshotSource,
    ReceiverHealth,
    SourceHealth,
)
from tradinglab.dashboard.telemetry import (  # noqa: E402
    TelemetryDeal,
    TelemetryDealPage,
    TelemetryPerformance,
)
from tradinglab.dashboard.web import create_server  # noqa: E402
from tradinglab.metrics import calculate_closed_deal_metrics  # noqa: E402

Account = namedtuple(
    "Account",
    "login server currency balance equity profit margin margin_free margin_level",
)
Position = namedtuple(
    "Position",
    "ticket magic symbol type volume price_open price_current sl tp profit time comment",
)
Order = namedtuple(
    "Order",
    "ticket magic symbol type volume_current price_open price_current sl tp time_setup comment",
)
Deal = namedtuple(
    "Deal",
    "ticket order position_id magic symbol type entry volume price profit commission swap fee time_msc time comment",
)
HistoricalOrder = namedtuple(
    "HistoricalOrder",
    "ticket position_id magic symbol type state volume_initial price_open time_done_msc time_done time_setup_msc time_setup comment",
)
ACCESS = "example-dashboard-token-not-for-production"


def authenticated_opener(base_url: str) -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    request = urllib.request.Request(
        f"{base_url}/login",
        data=urllib.parse.urlencode({"token": ACCESS}).encode(),
    )
    with opener.open(request, timeout=2) as response:
        if response.geturl() != f"{base_url}/dashboard":
            raise AssertionError("El login no redirigió al dashboard")
    return opener


class FakeHealthProvider:
    def __init__(self, *, fail: bool = False, receiver: ReceiverHealth | None = None) -> None:
        self.fail = fail
        self.receiver = receiver
        self.calls = 0

    def health(self, observed_at: datetime) -> SourceHealth:
        self.calls += 1
        if self.fail:
            raise RuntimeError("salud rota")
        return SourceHealth(
            availability="available",
            source_id="demo-terminal-01",
            collector_version="0.1.0",
            checked_at="2026-10-14T19:30:05Z",
            error=None,
            receiver=self.receiver,
        )


class FakeDealHistoryProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.performance_calls: list[dict[str, object]] = []

    def deal_history(self, **query: object) -> TelemetryDealPage:
        self.calls.append(query)
        deal = TelemetryDeal(
            account_id="account-demo",
            source_id="demo-terminal-01",
            message_id=1,
            captured_at="2026-10-20T12:00:00.000000Z",
            ticket="2",
            order_id="50",
            position_id="42",
            magic_number="11122",
            time_msc=999002,
            deal_type=1,
            entry=1,
            symbol="XAUUSD",
            volume=0.1,
            price=10.0,
            profit=1.0,
            commission=-0.1,
            swap=-0.2,
            fee=-0.01,
        )
        return TelemetryDealPage(
            account_id="account-demo",
            source_id="demo-terminal-01",
            from_msc=int(query["from_msc"]),
            to_msc=int(query["to_msc"]),
            magic_number=query["magic_number"],
            deals=(deal,),
            next_cursor=None,
        )

    def performance_metrics(self, **query: object) -> TelemetryPerformance:
        self.performance_calls.append(query)
        page = self.deal_history(limit=50, cursor=None, **query)
        return TelemetryPerformance(
            account_id=page.account_id,
            source_id=page.source_id,
            from_msc=page.from_msc,
            to_msc=page.to_msc,
            magic_number=page.magic_number,
            selection=calculate_closed_deal_metrics(page.deals),
        )


class FakeMt5:
    def __init__(self) -> None:
        self.shutdown_called = False
        self.fail_positions = False
        self.invalid_magic = False
        self.fail_history = False
        self.history_ranges: list[tuple[datetime, datetime]] = []

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> object:
        return (0, "ok")

    def account_info(self) -> Account:
        return Account(12345678, "DEMO-SERVER", "USD", 10_000, 10_025, 25, 500, 9_525, 2005)

    def positions_get(self) -> tuple[Position, ...] | None:
        if self.fail_positions:
            return None
        magic = "not-a-number" if self.invalid_magic else 11122
        return (
            Position(
                1, magic, "EURUSD", 0, 0.1, 1.08, 1.09, 1.04, 1.12, 10, 1_797_096_600, "alpha"
            ),
            Position(2, 11122, "GBPUSD", 1, 0.2, 1.26, 1.25, 0, 1.2, 15, 1_797_096_601, "beta"),
        )

    def orders_get(self) -> tuple[Order, ...]:
        return (
            Order(
                3,
                987654321012345678,
                "XAUUSD",
                2,
                0.05,
                2600,
                2670,
                2550,
                2800,
                1_797_096_602,
                "pending",
            ),
        )

    def history_deals_get(self, date_from: datetime, date_to: datetime) -> tuple[Deal, ...] | None:
        self.history_ranges.append((date_from, date_to))
        if self.fail_history:
            return None
        occurred_at = datetime(2026, 10, 14, 19, 29, tzinfo=UTC)
        return (
            Deal(
                20,
                10,
                30,
                987654321012345678,
                "XAUUSD",
                1,
                1,
                0.05,
                2670,
                12.5,
                -0.7,
                -0.2,
                0.0,
                int(occurred_at.timestamp() * 1000),
                int(occurred_at.timestamp()),
                "close",
            ),
        )

    def history_orders_get(
        self, date_from: datetime, date_to: datetime
    ) -> tuple[HistoricalOrder, ...]:
        self.history_ranges.append((date_from, date_to))
        occurred_at = datetime(2026, 10, 14, 19, 28, tzinfo=UTC)
        timestamp = int(occurred_at.timestamp())
        return (
            HistoricalOrder(
                10,
                30,
                987654321012345678,
                "XAUUSD",
                1,
                4,
                0.05,
                2670,
                timestamp * 1000,
                timestamp,
                timestamp * 1000,
                timestamp,
                "filled",
            ),
        )


class LiveDashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.observed_at = datetime(2026, 10, 14, 19, 30, tzinfo=UTC)

    def test_mt5_snapshot_uses_only_read_data_and_masks_account(self) -> None:
        client = FakeMt5()

        snapshot = Mt5SnapshotSource(client).collect(self.observed_at)

        self.assertTrue(client.shutdown_called)
        self.assertEqual(snapshot.account_reference, "****5678")
        self.assertEqual(snapshot.balance, 10_000)
        self.assertEqual(snapshot.equity, 10_025)
        self.assertEqual(snapshot.open_positions, 2)
        self.assertEqual(snapshot.active_orders, 1)
        self.assertEqual(snapshot.observed_at, "2026-10-14T19:30:00Z")
        self.assertEqual(len(snapshot.operations), 3)
        self.assertEqual(snapshot.operations[0].magic_number, "11122")
        self.assertEqual(snapshot.operations[0].operation_type, "buy")
        self.assertEqual(snapshot.operations[1].stop_loss, None)
        self.assertEqual(snapshot.operations[2].ticket, "3")
        self.assertEqual(snapshot.operations[2].magic_number, "987654321012345678")
        self.assertEqual(snapshot.operations[2].operation_type, "buy_limit")
        self.assertEqual(len(snapshot.recent_activity), 2)
        self.assertEqual(snapshot.recent_activity[0].category, "deal")
        self.assertEqual(snapshot.recent_activity[0].event_type, "sell_out")
        self.assertEqual(snapshot.recent_activity[0].profit, 12.5)
        self.assertEqual(snapshot.recent_activity[1].event_state, "filled")

    def test_activity_uses_incremental_overlap_and_periodic_reconciliation(self) -> None:
        client = FakeMt5()
        source = Mt5SnapshotSource(client)

        source.collect(self.observed_at)
        source.collect(self.observed_at + timedelta(seconds=5))
        source.collect(self.observed_at + timedelta(minutes=5))

        deal_ranges = client.history_ranges[::2]
        self.assertEqual(deal_ranges[0], (self.observed_at - timedelta(hours=24), self.observed_at))
        self.assertEqual(
            deal_ranges[1],
            (self.observed_at - timedelta(minutes=2), self.observed_at + timedelta(seconds=5)),
        )
        full_refresh_at = self.observed_at + timedelta(minutes=5)
        self.assertEqual(
            deal_ranges[2],
            (full_refresh_at - timedelta(hours=24), full_refresh_at),
        )

    def test_mt5_read_failure_still_closes_connection(self) -> None:
        client = FakeMt5()
        client.fail_positions = True

        with self.assertRaisesRegex(RuntimeError, "posiciones"):
            Mt5SnapshotSource(client).collect(self.observed_at)

        self.assertTrue(client.shutdown_called)

    def test_invalid_operation_identifier_is_rejected(self) -> None:
        client = FakeMt5()
        client.invalid_magic = True

        with self.assertRaisesRegex(RuntimeError, "magic number"):
            Mt5SnapshotSource(client).collect(self.observed_at)

        self.assertTrue(client.shutdown_called)

    def test_capture_state_records_read_failure(self) -> None:
        client = FakeMt5()
        client.fail_history = True
        timer_values = iter([4.0, 4.025])
        service = LiveDashboardService(
            Mt5SnapshotSource(client),
            interval_seconds=5,
            clock=lambda: self.observed_at,
            timer=lambda: next(timer_values),
        )

        service.poll_once()

        state = service.state()
        self.assertEqual(state["status"], "degraded")
        self.assertEqual(state["capture"]["attempt_count"], 1)
        self.assertEqual(state["capture"]["failure_count"], 1)
        self.assertEqual(state["capture"]["consecutive_failures"], 1)
        self.assertEqual(state["capture"]["last_duration_ms"], 25.0)

    def test_service_retains_bounded_deterministic_history(self) -> None:
        instants = iter(
            [self.observed_at, self.observed_at + timedelta(seconds=5), self.observed_at]
        )
        timer_values = iter([10.0, 10.012, 20.0, 20.019])
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            history_limit=2,
            clock=lambda: next(instants),
            timer=lambda: next(timer_values),
        )

        service.poll_once()
        service.poll_once()

        state = service.state()
        self.assertEqual(state["status"], "connected")
        self.assertEqual(len(state["history"]), 2)
        self.assertEqual(state["latest"]["equity"], 100_042.0)
        self.assertEqual(state["latest"]["operations"][0]["magic_number"], "11122")
        self.assertNotIn("operations", state["history"][0])
        self.assertNotIn("recent_activity", state["history"][0])
        self.assertEqual(state["capture"]["attempt_count"], 2)
        self.assertEqual(state["capture"]["success_count"], 2)
        self.assertEqual(state["capture"]["last_duration_ms"], 19.0)
        self.assertEqual(state["capture"]["consecutive_failures"], 0)

    def test_state_filters_history_since_observed_at(self) -> None:
        instants = iter(
            [
                self.observed_at,
                self.observed_at + timedelta(seconds=5),
                self.observed_at + timedelta(seconds=10),
            ]
        )
        timer_values = iter([10.0, 10.012, 20.0, 20.019, 30.0, 30.023])
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            clock=lambda: next(instants),
            timer=lambda: next(timer_values),
        )
        service.poll_once()
        service.poll_once()
        service.poll_once()

        state = service.state(history_since="2026-10-14T19:30:00Z")

        self.assertTrue(state["history_truncated"])
        self.assertEqual(len(state["history"]), 2)
        self.assertEqual(state["history"][0]["observed_at"], "2026-10-14T19:30:05Z")

    def test_state_compares_fractional_instants_and_rejects_invalid_since(self) -> None:
        instants = iter([self.observed_at, self.observed_at + timedelta(milliseconds=500)])
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            clock=lambda: next(instants),
        )
        service.poll_once()
        service.poll_once()

        state = service.state(history_since="2026-10-14T19:30:00Z")

        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["history"][0]["observed_at"], "2026-10-14T19:30:00.500000Z")
        with self.assertRaisesRegex(ValueError, "history_since"):
            service.state(history_since="not-an-instant")

    def test_statics_serve_etag_and_304(self) -> None:
        service = LiveDashboardService(DemoSnapshotSource(), interval_seconds=5)
        server = create_server(service, port=0, dashboard_token=ACCESS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(f"{base_url}/assets/app.js", timeout=2) as response:
                body = response.read()
                etag = response.headers["ETag"]
                self.assertTrue(body.startswith(b'"use strict"'))
                self.assertIn("no-cache", response.headers["Cache-Control"])
            second = urllib.request.Request(
                f"{base_url}/assets/app.js", headers={"If-None-Match": etag}
            )
            try:
                urllib.request.urlopen(second, timeout=2)
                self.fail("Se esperaba un 304 Not Modified")
            except urllib.error.HTTPError as error:
                try:
                    self.assertEqual(error.code, 304)
                    self.assertEqual(error.headers["Vary"], "Accept-Encoding")
                finally:
                    error.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_head_and_gzip_on_statics(self) -> None:
        service = LiveDashboardService(DemoSnapshotSource(), interval_seconds=5)
        server = create_server(service, port=0, dashboard_token=ACCESS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            head = urllib.request.Request(f"{base_url}/assets/app.js", method="HEAD")
            with urllib.request.urlopen(head, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b"")
                self.assertIn("ETag", response.headers)
            gzipped = urllib.request.Request(
                f"{base_url}/assets/app.js", headers={"Accept-Encoding": "gzip"}
            )
            with urllib.request.urlopen(gzipped, timeout=2) as response:
                self.assertEqual(response.headers["Content-Encoding"], "gzip")
                self.assertEqual(response.headers["Vary"], "Accept-Encoding")
                payload = gzip.decompress(response.read())
                self.assertTrue(payload.startswith(b'"use strict"'))
            for asset, content_type in (
                ("vendor/echarts-6.1.0.min.js", "text/javascript; charset=utf-8"),
                ("logo_black.png", "image/png"),
                ("logo_white.png", "image/png"),
                ("favicon-black.ico", "image/x-icon"),
                ("favicon-white.ico", "image/x-icon"),
                ("tradinglab-favicon-black-32.png", "image/png"),
                ("tradinglab-favicon-white-32.png", "image/png"),
                ("tradinglab-apple-touch-icon-black.png", "image/png"),
                ("tradinglab-apple-touch-icon-white.png", "image/png"),
                ("nav-icons.svg", "image/svg+xml"),
            ):
                with urllib.request.urlopen(f"{base_url}/assets/{asset}", timeout=2) as response:
                    self.assertEqual(response.headers["Content-Type"], content_type)
                    self.assertGreater(len(response.read()), 100)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_activity_renderer_handles_a_monetary_event(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js no está disponible para el smoke test del frontend")
        app_js = Path(__file__).parents[2] / "src/tradinglab/dashboard/static/app.js"
        smoke_test = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`No se encontró ${name}`);
  const body = source.indexOf("{", start);
  let depth = 0;
  for (let index = body; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`Función incompleta: ${name}`);
}
eval(`${functionSource("buildActivityContent")}`);
function nodeStub() {
  return {
    children: [], className: "", textContent: "", value: "", checked: false,
    classList: { add() {}, toggle() {}, remove() {} },
    setAttribute() {}, appendChild(child) { this.children.push(child); },
    append(...children) { this.children.push(...children); },
  };
}
globalThis.document = { createElement: () => nodeStub() };
globalThis.telemetryMode = false;
globalThis.toDate = (value) => new Date(value);
globalThis.dateTimeFormatter = { format: () => "15/10/2026, 01:00:00" };
globalThis.activityTypes = { sell_out: "Venta · salida" };
globalThis.activityStates = {};
globalThis.latestCurrency = "USD";
globalThis.textCell = () => nodeStub();
globalThis.money = (value) => String(value);
const nodes = buildActivityContent([{
  occurred_at: "2026-10-15T01:00:00Z", category: "deal",
  event_type: "sell_out", event_state: null, ticket: "1", magic_number: "11122",
  symbol: "EURUSD", comment: "", volume: 0.1, price: 1.1, profit: 10,
}]);
const table = nodes.find((node) => node.tagName === "table") || nodes[1];
const tbody = table.children[2];
const row = tbody.children[0];
if (row.children.length !== 5) throw new Error("La fila de actividad quedó incompleta");
if (row.children[4].textContent !== "10") throw new Error("El resultado no quedó en la fila");
"""

        result = subprocess.run(
            [node, "-e", smoke_test, str(app_js)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_chart_uses_observation_time_and_breaks_capture_gaps(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js no está disponible para el smoke test del frontend")
        app_js = Path(__file__).parents[2] / "src/tradinglab/dashboard/static/app.js"
        smoke_test = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function accountChartSeries(");
const body = source.indexOf("{", start);
let depth = 0;
let definition = "";
for (let index = body; index < source.length; index += 1) {
  if (source[index] === "{") depth += 1;
  if (source[index] === "}") depth -= 1;
  if (depth === 0) { definition = source.slice(start, index + 1); break; }
}
if (!definition) throw new Error("No se encontró accountChartSeries");
eval(definition);
const timeline = [
  { at: new Date("2026-10-17T10:00:00Z"), balance: 100 },
  { at: new Date("2026-10-17T10:00:05Z"), balance: 101 },
  { at: new Date("2026-10-17T10:02:00Z"), balance: 102 },
  { at: new Date("2026-10-17T10:02:05Z"), balance: 103 },
];
const result = accountChartSeries(timeline, "balance", 12500);
if (result.gaps !== 1) throw new Error(`Cantidad de gaps incorrecta: ${result.gaps}`);
if (result.data.filter((point) => point[1] === null).length !== 1) {
  throw new Error("La serie no corta visualmente la interrupción");
}
if (result.data[0][0] !== timeline[0].at.getTime()) {
  throw new Error("La serie no conserva el tiempo observado");
}
"""

        result = subprocess.run(
            [node, "-e", smoke_test, str(app_js)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_state_keeps_v3_contract_and_adds_source_health(self) -> None:
        service = LiveDashboardService(
            DemoSnapshotSource(), interval_seconds=5, clock=lambda: self.observed_at
        )
        service.poll_once()

        state = service.state()

        self.assertEqual(state["schema_version"], "live-dashboard-state-v3")
        self.assertIn("status", state)
        self.assertIn("latest", state)
        self.assertIn("history", state)
        self.assertIn("capture", state)
        health = state["source_health"]
        self.assertEqual(health["availability"], "not_applicable")
        self.assertIsNone(health["source_id"])
        self.assertIsNone(health["collector_version"])
        self.assertIsNone(health["checked_at"])
        self.assertIsNone(health["error"])
        self.assertIsNone(health["receiver"])

    def test_health_failure_does_not_degrade_capture(self) -> None:
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            clock=lambda: self.observed_at,
            health_provider=FakeHealthProvider(fail=True),
        )
        service.poll_once()

        state = service.state()

        self.assertEqual(state["status"], "connected")
        self.assertEqual(state["source_health"]["availability"], "unavailable")
        self.assertIsNone(state["source_health"]["receiver"])

    def test_capture_failure_still_publishes_health(self) -> None:
        class FailingSource(DemoSnapshotSource):
            def collect(self, observed_at: datetime) -> LiveSnapshot:
                raise RuntimeError("captura rota")

        receiver = ReceiverHealth(
            accepted=5,
            duplicates=0,
            missing_sequences=0,
            retained=1,
            retained_sessions=1,
            history_status="complete",
        )
        service = LiveDashboardService(
            FailingSource(),
            interval_seconds=5,
            clock=lambda: self.observed_at,
            health_provider=FakeHealthProvider(receiver=receiver),
        )
        service.poll_once()

        state = service.state()

        self.assertEqual(state["status"], "degraded")
        self.assertEqual(state["source_health"]["availability"], "available")
        self.assertEqual(state["source_health"]["receiver"]["accepted"], 5)

    def test_health_is_polled_independently_every_cycle(self) -> None:
        provider = FakeHealthProvider()
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            clock=lambda: self.observed_at,
            health_provider=provider,
        )

        service.poll_once()
        service.poll_once()

        self.assertEqual(provider.calls, 2)

    def test_http_state_includes_source_health(self) -> None:
        service = LiveDashboardService(
            DemoSnapshotSource(), interval_seconds=5, clock=lambda: self.observed_at
        )
        service.poll_once()
        server = create_server(service, port=0, dashboard_token=ACCESS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            opener = authenticated_opener(base_url)
            with opener.open(f"{base_url}/api/state", timeout=2) as response:
                payload = json.loads(response.read())
                self.assertEqual(payload["schema_version"], "live-dashboard-state-v3")
                self.assertEqual(payload["source_health"]["availability"], "not_applicable")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_proxies_history_only_for_authenticated_sessions(self) -> None:
        service = LiveDashboardService(
            DemoSnapshotSource(), interval_seconds=5, clock=lambda: self.observed_at
        )
        provider = FakeDealHistoryProvider()
        server = create_server(
            service,
            port=0,
            dashboard_token=ACCESS,
            history_provider=provider,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        route = f"{base_url}/api/deals?from_msc=999000&to_msc=1000000&magic_number=11122"
        try:
            with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                urllib.request.urlopen(route, timeout=2)
            self.assertEqual(unauthorized.exception.code, 401)
            unauthorized.exception.close()

            opener = authenticated_opener(base_url)
            with opener.open(route, timeout=2) as response:
                payload = json.loads(response.read())
            self.assertEqual(payload["deals"][0]["ticket"], "2")
            self.assertEqual(payload["magic_number"], "11122")
            self.assertEqual(provider.calls[0]["limit"], 50)
            metrics_route = (
                f"{base_url}/api/metrics?from_msc=999000&to_msc=1000000&magic_number=11122"
            )
            with opener.open(metrics_route, timeout=2) as response:
                metrics = json.loads(response.read())
            self.assertEqual(metrics["formula_version"], "partner-workbook-v1")
            self.assertEqual(metrics["trade_count"], 1)
            self.assertAlmostEqual(metrics["net_profit"], 0.69)
            self.assertEqual(provider.performance_calls[0]["magic_number"], "11122")
            with self.assertRaises(urllib.error.HTTPError) as invalid:
                opener.open(f"{base_url}/api/deals?from_msc=1&to_msc=1", timeout=2)
            self.assertEqual(invalid.exception.code, 400)
            invalid.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_hidden_attribute_wins_over_responsive_layout(self) -> None:
        styles = (ROOT / "src" / "tradinglab" / "dashboard" / "static" / "styles.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("[hidden] { display: none !important; }", styles)

    def test_project_and_dashboard_routes_serve_their_pages(self) -> None:
        service = LiveDashboardService(DemoSnapshotSource(), interval_seconds=5)
        server = create_server(service, port=0, dashboard_token=ACCESS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(f"{base_url}/", timeout=2) as response:
                self.assertIn("text/html", response.headers["Content-Type"])
                self.assertIn(b"TradingLab", response.read())
            with urllib.request.urlopen(f"{base_url}/dashboard", timeout=2) as response:
                self.assertEqual(response.geturl(), f"{base_url}/login")
                self.assertIn(b"Acceder al panel", response.read())
            opener = authenticated_opener(base_url)
            with opener.open(f"{base_url}/dashboard/", timeout=2) as response:
                self.assertIn(b"Panel de la cuenta", response.read())
            with urllib.request.urlopen(f"{base_url}/assets/theme.js", timeout=2) as response:
                self.assertIn("javascript", response.headers["Content-Type"])
                self.assertIn(b"data-theme-toggle", response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_theme_script_precedes_stylesheet_without_inline(self) -> None:
        static = ROOT / "src" / "tradinglab" / "dashboard" / "static"
        for name in ("index.html", "dashboard.html"):
            with self.subTest(name=name):
                text = (static / name).read_text(encoding="utf-8")
                theme_at = text.index('<script src="/assets/theme.js"></script>')
                css_at = text.index('<link rel="stylesheet" href="/assets/styles.css">')
                self.assertLess(theme_at, css_at)
                self.assertNotRegex(text, r"<script(?! src=)")
                self.assertNotRegex(text, r"\son\w+=")
                self.assertNotIn("style=", text)

    def test_dashboard_markup_exposes_mobile_and_keyboard_controls(self) -> None:
        dashboard = (
            ROOT / "src" / "tradinglab" / "dashboard" / "static" / "dashboard.html"
        ).read_text(encoding="utf-8")

        self.assertIn('class="skip-link"', dashboard)
        self.assertIn('id="kind-filter"', dashboard)
        self.assertIn('class="technical-health"', dashboard)
        self.assertIn('<select id="magic-filter">', dashboard)
        self.assertIn("Todos los bots", dashboard)
        self.assertIn('id="operations-note" role="status"', dashboard)
        self.assertIn('id="history-period"', dashboard)
        self.assertIn('id="history-magic"', dashboard)
        self.assertIn('id="history-more"', dashboard)
        self.assertIn('id="history-metrics"', dashboard)
        self.assertIn('id="chart-cumulative"', dashboard)
        self.assertIn('id="chart" class="account-chart"', dashboard)
        self.assertNotIn('<svg id="chart"', dashboard)
        self.assertIn('src="/assets/vendor/echarts-6.1.0.min.js"', dashboard)
        self.assertNotIn('id="freshness" aria-live', dashboard)
        self.assertLess(dashboard.index("</nav>"), dashboard.index("<main "))
        self.assertLess(
            dashboard.index('id="activity-content"'),
            dashboard.index('class="technical-health"'),
        )
        for view in ("overview", "operations", "history", "activity"):
            self.assertIn(f'aria-controls="{view}-view"', dashboard)
            self.assertIn(f'id="{view}-view"', dashboard)

        app = (ROOT / "src" / "tradinglab" / "dashboard" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        styles = (ROOT / "src" / "tradinglab" / "dashboard" / "static" / "styles.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("Los filtros solo abarcan el detalle recibido", app)
        self.assertIn("/api/deals?", app)
        self.assertIn("/api/metrics?", app)
        self.assertIn('getPropertyValue("--chart-grid")', app)
        self.assertIn("emphasis: { disabled: true }", app)
        self.assertIn('type: "time"', app)
        self.assertIn("connectNulls: false", app)
        self.assertIn("markLine:", app)
        self.assertIn("--chart-grid: #3a4038", styles)
        self.assertIn("grid-template-columns: 192px minmax(0, 1fr)", styles)
        self.assertIn(".site-nav .logout-form { position: fixed", styles)
        self.assertIn("HISTORY_CLIENT_LIMIT = 500", app)

    def test_local_server_exposes_read_only_state_and_security_headers(self) -> None:
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            clock=lambda: self.observed_at,
        )
        service.poll_once()
        server = create_server(service, port=0, dashboard_token=ACCESS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                urllib.request.urlopen(f"{base_url}/api/state", timeout=2)
            self.assertEqual(unauthorized.exception.code, 401)
            unauthorized.exception.close()

            opener = authenticated_opener(base_url)
            with opener.open(f"{base_url}/api/state", timeout=2) as response:
                payload = json.loads(response.read())
                self.assertEqual(payload["status"], "connected")
                self.assertEqual(payload["schema_version"], "live-dashboard-state-v3")
                self.assertEqual(len(payload["latest"]["operations"]), 6)
                self.assertEqual(len(payload["latest"]["recent_activity"]), 2)
                self.assertNotIn("operations", payload["history"][0])
                self.assertEqual(payload["capture"]["success_count"], 1)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

            with opener.open(f"{base_url}/dashboard", timeout=2) as response:
                page = response.read().decode()
                self.assertIn('id="operations-view"', page)
                self.assertIn('id="magic-filter"', page)
                self.assertIn('id="history-view"', page)
                self.assertIn('id="activity-view"', page)

            request = urllib.request.Request(f"{base_url}/api/state", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(request, timeout=2)
            self.assertEqual(raised.exception.code, 405)
            raised.exception.close()

            with self.assertRaises(urllib.error.HTTPError) as invalid_since:
                opener.open(f"{base_url}/api/state?since=invalid", timeout=2)
            self.assertEqual(invalid_since.exception.code, 400)
            invalid_since.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_login_logout_and_host_validation_protect_dashboard_data(self) -> None:
        service = LiveDashboardService(DemoSnapshotSource(), interval_seconds=5)
        service.poll_once()
        server = create_server(service, port=0, dashboard_token=ACCESS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            encoded_access = urllib.parse.urlencode({"token": ACCESS})
            connection.request(
                "POST",
                "/login",
                body=encoded_access,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            login_response = connection.getresponse()
            cookie_header = login_response.getheader("Set-Cookie", "")
            self.assertEqual(login_response.status, 303)
            self.assertIn("HttpOnly", cookie_header)
            self.assertIn("SameSite=Strict", cookie_header)
            self.assertNotIn(ACCESS, cookie_header)
            login_response.read()
            connection.close()

            invalid = urllib.request.Request(
                f"{base_url}/login",
                data=urllib.parse.urlencode(
                    {"token": "example-invalid-token-with-safe-length"}
                ).encode(),
            )
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(invalid, timeout=2)
            self.assertEqual(rejected.exception.code, 401)
            self.assertNotIn("Set-Cookie", rejected.exception.headers)
            rejected.exception.close()

            opaque_origin = urllib.request.Request(
                f"{base_url}/login",
                data=urllib.parse.urlencode(
                    {"token": "example-invalid-token-with-safe-length"}
                ).encode(),
                headers={"Origin": "null"},
            )
            with self.assertRaises(urllib.error.HTTPError) as invalid_opaque_login:
                urllib.request.urlopen(opaque_origin, timeout=2)
            self.assertEqual(invalid_opaque_login.exception.code, 401)
            invalid_opaque_login.exception.close()

            foreign_host = urllib.request.Request(
                f"{base_url}/api/state", headers={"Host": "untrusted.example"}
            )
            with self.assertRaises(urllib.error.HTTPError) as rejected_host:
                urllib.request.urlopen(foreign_host, timeout=2)
            self.assertEqual(rejected_host.exception.code, 421)
            rejected_host.exception.close()

            opener = authenticated_opener(base_url)
            logout = urllib.request.Request(f"{base_url}/logout", data=b"")
            with opener.open(logout, timeout=2) as response:
                self.assertEqual(response.geturl(), f"{base_url}/login")
            with self.assertRaises(urllib.error.HTTPError) as logged_out:
                opener.open(f"{base_url}/api/state", timeout=2)
            self.assertEqual(logged_out.exception.code, 401)
            logged_out.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
