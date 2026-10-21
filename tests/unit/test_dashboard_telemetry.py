from __future__ import annotations

import sys
import threading
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from tradinglab.dashboard.service import LiveDashboardService  # noqa: E402
from tradinglab.dashboard.snapshot import (  # noqa: E402
    DashboardReadError,
    ReceiverHealth,
)
from tradinglab.dashboard.telemetry import (  # noqa: E402
    LoopbackTelemetryClient,
    TelemetrySnapshotSource,
)
from tradinglab.telemetry.contract import TelemetryEnvelope  # noqa: E402
from tradinglab.telemetry.ingest import (  # noqa: E402
    TelemetryBuffer,
    create_telemetry_server,
)

TOKEN = "example-local-token-with-at-least-24-characters"


def envelope(
    *,
    captured_at: str = "2026-10-16T12:00:00Z",
    source_id: str = "demo-terminal-01",
) -> TelemetryEnvelope:
    return TelemetryEnvelope(
        schema_version="mt5-telemetry-v1",
        collector_version="0.1.0",
        source_id=source_id,
        session_id="session-1",
        sequence=1,
        event_id="session-1:1",
        captured_at=captured_at,
        kind="account_snapshot",
        payload={
            "reason": "timer",
            "account": {
                "login_masked": "****1234",
                "server": "DEMO-SERVER",
                "currency": "USD",
                "balance": 100_000.0,
                "equity": 99_950.0,
                "profit": -50.0,
                "margin": 500.0,
                "margin_free": 99_450.0,
                "margin_level": 19_990.0,
            },
            "positions_total": 1,
            "orders_total": 1,
            "positions": [
                {
                    "ticket": "9223372036854775000",
                    "magic_number": "11122",
                    "symbol": "XAUUSD",
                    "profit": -50.0,
                    "position_id": "9223372036854775000",
                    "operation_type": 0,
                    "volume": 0.1,
                    "price_open": 2700.0,
                    "price_current": 2695.0,
                    "stop_loss": 0.0,
                    "take_profit": 2750.0,
                    "swap": -0.5,
                    "opened_at_msc": "1792100000000",
                    "comment": "alpha",
                }
            ],
            "orders": [
                {
                    "ticket": "18446744073709551615",
                    "magic_number": "0",
                    "symbol": "EURUSD",
                    "order_type": 2,
                    "volume": 0.1,
                    "price_open": 1.0,
                    "price_current": 1.1,
                    "stop_loss": 0.0,
                    "take_profit": 0.0,
                    "created_at_msc": "1792100000000",
                    "comment": "pending",
                }
            ],
        },
    )


class StubClient:
    def __init__(
        self, item: TelemetryEnvelope, health: ReceiverHealth | Exception | None = None
    ) -> None:
        self.item = item
        self.health_result = health

    def latest(self) -> TelemetryEnvelope:
        return self.item

    def health(self) -> ReceiverHealth:
        if isinstance(self.health_result, Exception):
            raise self.health_result
        if self.health_result is None:
            raise DashboardReadError("No se pudo leer el estado del receptor local")
        return self.health_result


class DashboardTelemetryTest(unittest.TestCase):
    def test_maps_account_and_operations_without_claiming_server_time_is_utc(self) -> None:
        source = TelemetrySnapshotSource(StubClient(envelope()), source_id="demo-terminal-01")

        snapshot = source.collect(datetime(2026, 10, 16, 12, 0, 5, tzinfo=UTC))

        self.assertEqual(snapshot.source, "mt5-telemetry")
        self.assertEqual(snapshot.account_reference, "****1234")
        self.assertEqual(snapshot.equity, 99_950.0)
        self.assertEqual(snapshot.open_positions, 1)
        self.assertEqual(snapshot.operations[0].kind, "position")
        self.assertEqual(snapshot.operations[0].magic_number, "11122")
        self.assertEqual(snapshot.operations[0].operation_type, "buy")
        self.assertIsNone(snapshot.operations[0].opened_at)
        self.assertEqual(snapshot.operations[1].operation_type, "buy_limit")
        self.assertEqual(snapshot.recent_activity, ())

    def test_rejects_stale_future_and_wrong_source_snapshots(self) -> None:
        observed_at = datetime(2026, 10, 16, 12, 1, tzinfo=UTC)
        cases = (
            (envelope(), "desactualizada"),
            (envelope(captured_at="2026-10-16T12:02:00Z"), "adelantado"),
            (envelope(captured_at="2026-10-16T12:01:00Z", source_id="other"), "otra fuente"),
        )
        for item, message in cases:
            with self.subTest(message=message):
                source = TelemetrySnapshotSource(
                    StubClient(item),
                    source_id="demo-terminal-01",
                    max_age=timedelta(seconds=30),
                )
                with self.assertRaisesRegex(DashboardReadError, message):
                    source.collect(observed_at)

    def test_marks_operation_detail_as_truncated_against_reported_totals(self) -> None:
        item = envelope()
        item.payload["positions_total"] = 2
        source = TelemetrySnapshotSource(StubClient(item), source_id="demo-terminal-01")

        snapshot = source.collect(datetime(2026, 10, 16, 12, 0, 5, tzinfo=UTC))

        self.assertEqual(snapshot.open_positions, 2)
        self.assertEqual(len(snapshot.operations), 2)
        self.assertTrue(snapshot.operations_truncated)
        self.assertTrue(snapshot.as_dict()["operations_truncated"])

    def test_loopback_client_reads_only_authenticated_validated_snapshot(self) -> None:
        buffer = TelemetryBuffer()
        buffer.accept(envelope())
        buffer.accept(envelope(source_id="demo-terminal-02"))
        server = create_telemetry_server(buffer, token=TOKEN, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = LoopbackTelemetryClient(
                token=TOKEN,
                source_id="demo-terminal-01",
                port=server.server_port,
            )
            self.assertEqual(client.latest().source_id, "demo-terminal-01")
            second = LoopbackTelemetryClient(
                token=TOKEN,
                source_id="demo-terminal-02",
                port=server.server_port,
            )
            self.assertEqual(second.latest().source_id, "demo-terminal-02")
            wrong = LoopbackTelemetryClient(
                token="x" * 24,
                source_id="demo-terminal-01",
                port=server.server_port,
            )
            with self.assertRaisesRegex(DashboardReadError, "autenticación"):
                wrong.latest()
            with self.assertRaisesRegex(ValueError, "source_id"):
                LoopbackTelemetryClient(
                    token=TOKEN,
                    source_id="invalid source",
                    port=server.server_port,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_loopback_client_rejects_redirects_without_contacting_destination(self) -> None:
        destination_requests: list[tuple[str, str | None]] = []

        class DestinationHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                destination_requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(204)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        destination = ThreadingHTTPServer(("127.0.0.1", 0), DestinationHandler)
        destination_thread = threading.Thread(target=destination.serve_forever, daemon=True)
        destination_thread.start()
        redirect_target = f"http://127.0.0.1:{destination.server_port}/captured"

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(302)
                self.send_header("Location", redirect_target)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        try:
            client = LoopbackTelemetryClient(
                token=TOKEN,
                source_id="demo-terminal-01",
                port=redirect.server_port,
            )
            with self.assertRaisesRegex(DashboardReadError, "redirección"):
                client.latest()
            with self.assertRaisesRegex(DashboardReadError, "redirección"):
                client.health()
            self.assertEqual(destination_requests, [])
        finally:
            redirect.shutdown()
            redirect.server_close()
            redirect_thread.join(timeout=2)
            destination.shutdown()
            destination.server_close()
            destination_thread.join(timeout=2)

    def test_loopback_client_disables_implicit_proxy_discovery(self) -> None:
        with patch(
            "urllib.request.getproxies",
            side_effect=AssertionError("proxy discovery must stay disabled"),
        ):
            LoopbackTelemetryClient(
                token=TOKEN,
                source_id="demo-terminal-01",
                port=8766,
            )

    def test_repeated_receiver_poll_does_not_inflate_chart_history(self) -> None:
        observed_at = datetime(2026, 10, 16, 12, 0, 5, tzinfo=UTC)
        service = LiveDashboardService(
            TelemetrySnapshotSource(StubClient(envelope()), source_id="demo-terminal-01"),
            interval_seconds=5,
            clock=lambda: observed_at,
        )

        service.poll_once()
        service.poll_once()

        state = service.state()
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["capture"]["success_count"], 2)

    def test_health_maps_receiver_counters_and_collector_version(self) -> None:
        observed_at = datetime(2026, 10, 16, 12, 0, 5, tzinfo=UTC)
        stub = StubClient(
            envelope(),
            health=ReceiverHealth(
                accepted=1084,
                duplicates=3,
                missing_sequences=0,
                retained=120,
                retained_sessions=1,
                history_status="complete",
            ),
        )
        source = TelemetrySnapshotSource(stub, source_id="demo-terminal-01")
        source.collect(observed_at)

        health = source.health(observed_at + timedelta(seconds=5))

        self.assertEqual(health.availability, "available")
        self.assertEqual(health.source_id, "demo-terminal-01")
        self.assertEqual(health.collector_version, "0.1.0")
        self.assertEqual(health.receiver.accepted, 1084)
        self.assertEqual(health.receiver.duplicates, 3)
        self.assertEqual(health.receiver.missing_sequences, 0)
        self.assertEqual(health.receiver.retained, 120)
        self.assertEqual(health.receiver.retained_sessions, 1)
        self.assertEqual(health.receiver.history_status, "complete")
        self.assertEqual(health.checked_at, "2026-10-16T12:00:10Z")

    def test_health_unavailable_preserves_identity_without_counters(self) -> None:
        observed_at = datetime(2026, 10, 16, 12, 0, 5, tzinfo=UTC)
        stub = StubClient(
            envelope(),
            health=DashboardReadError("No se pudo leer el estado del receptor local"),
        )
        source = TelemetrySnapshotSource(stub, source_id="demo-terminal-01")
        source.collect(observed_at)

        health = source.health(observed_at)

        self.assertEqual(health.availability, "unavailable")
        self.assertIsNone(health.receiver)
        self.assertEqual(health.source_id, "demo-terminal-01")
        self.assertEqual(health.collector_version, "0.1.0")
        self.assertIn("receptor", health.error)
        self.assertEqual(health.checked_at, "2026-10-16T12:00:05Z")

    def test_loopback_client_health_reads_counters_without_token(self) -> None:
        buffer = TelemetryBuffer()
        buffer.accept(envelope())
        buffer.accept(envelope())  # duplicate fingerprint: same session+sequence
        server = create_telemetry_server(buffer, token=TOKEN, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = LoopbackTelemetryClient(
                token=TOKEN,
                source_id="demo-terminal-01",
                port=server.server_port,
            )
            health = client.health()
            self.assertEqual(health.accepted, 1)
            self.assertEqual(health.duplicates, 1)
            self.assertEqual(health.missing_sequences, 0)
            self.assertEqual(health.retained, 1)
            self.assertEqual(health.retained_sessions, 1)
            self.assertEqual(health.history_status, "unavailable")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
