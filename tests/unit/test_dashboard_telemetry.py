from __future__ import annotations

import sys
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from tradinglab.dashboard.service import LiveDashboardService  # noqa: E402
from tradinglab.dashboard.snapshot import DashboardReadError  # noqa: E402
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
    def __init__(self, item: TelemetryEnvelope) -> None:
        self.item = item

    def latest(self) -> TelemetryEnvelope:
        return self.item


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


if __name__ == "__main__":
    unittest.main()
