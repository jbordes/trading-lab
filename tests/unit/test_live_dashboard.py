from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from tradinglab.dashboard.service import LiveDashboardService  # noqa: E402
from tradinglab.dashboard.snapshot import (  # noqa: E402
    DemoSnapshotSource,
    Mt5SnapshotSource,
)
from tradinglab.dashboard.web import create_server  # noqa: E402

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


class FakeMt5:
    def __init__(self) -> None:
        self.shutdown_called = False
        self.fail_positions = False
        self.invalid_magic = False

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

    def test_service_retains_bounded_deterministic_history(self) -> None:
        instants = iter(
            [self.observed_at, self.observed_at + timedelta(seconds=5), self.observed_at]
        )
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            history_limit=2,
            clock=lambda: next(instants),
        )

        service.poll_once()
        service.poll_once()

        state = service.state()
        self.assertEqual(state["status"], "connected")
        self.assertEqual(len(state["history"]), 2)
        self.assertEqual(state["latest"]["equity"], 100_042.0)
        self.assertEqual(state["latest"]["operations"][0]["magic_number"], "11122")
        self.assertNotIn("operations", state["history"][0])

    def test_local_server_exposes_read_only_state_and_security_headers(self) -> None:
        service = LiveDashboardService(
            DemoSnapshotSource(),
            interval_seconds=5,
            clock=lambda: self.observed_at,
        )
        service.poll_once()
        server = create_server(service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(f"{base_url}/api/state", timeout=2) as response:
                payload = json.loads(response.read())
                self.assertEqual(payload["status"], "connected")
                self.assertEqual(payload["schema_version"], "live-dashboard-state-v2")
                self.assertEqual(len(payload["latest"]["operations"]), 3)
                self.assertNotIn("operations", payload["history"][0])
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

            with urllib.request.urlopen(base_url, timeout=2) as response:
                page = response.read().decode()
                self.assertIn('id="operations-view"', page)
                self.assertIn('id="magic-filter"', page)

            request = urllib.request.Request(f"{base_url}/api/state", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(raised.exception.code, 405)
            raised.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
