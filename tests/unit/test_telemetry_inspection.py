from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.inspection import InspectionPlan  # noqa: E402
from tradinglab.telemetry.inspection import _summarize as summarize  # noqa: E402
from tradinglab.telemetry.provisioning import ProvisionPlan  # noqa: E402
from tradinglab.telemetry.sqlite_store import open_registry  # noqa: E402


def message(
    sequence: int,
    captured: datetime,
    *,
    magic: str,
    ticket: str,
    source_id: str = "demo-source",
) -> bytes:
    stamp = captured.isoformat(timespec="seconds").replace("+00:00", "Z")
    session_id = f"{source_id}-session"
    body = {
        "schema_version": "mt5-telemetry-v1",
        "collector_version": "0.1.0",
        "source_id": source_id,
        "session_id": session_id,
        "sequence": sequence,
        "event_id": f"{session_id}:{sequence}",
        "captured_at": stamp,
        "kind": "account_snapshot",
        "payload": {
            "reason": "timer",
            "account": {
                "login_masked": "****1234",
                "server": "DEMO",
                "currency": "USD",
                "balance": 1000.0,
                "equity": 1000.0,
                "profit": 0.0,
                "margin": 0.0,
                "margin_free": 1000.0,
                "margin_level": 0.0,
            },
            "positions_total": 0,
            "orders_total": 1,
            "positions": [],
            "orders": [
                {
                    "ticket": str(100 + sequence),
                    "magic_number": magic,
                    "symbol": "XAUUSD",
                    "order_type": 2,
                    "volume": 0.01,
                    "price_open": 1.0,
                    "price_current": 1.0,
                    "stop_loss": 0.0,
                    "take_profit": 0.0,
                    "created_at_msc": str(int(captured.timestamp() * 1000)),
                    "comment": "",
                }
            ],
            "history": {
                "status": "complete",
                "from_server_seconds": str(int(captured.timestamp()) - 60),
                "to_server_seconds": str(int(captured.timestamp())),
                "total": 1,
                "deals": [
                    {
                        "ticket": ticket,
                        "order_id": "1",
                        "position_id": "1",
                        "magic_number": magic,
                        "time_msc": str(int(captured.timestamp() * 1000)),
                        "deal_type": 0,
                        "entry": 0,
                        "symbol": "XAUUSD",
                        "volume": 0.01,
                        "price": 1.0,
                        "profit": 0.0,
                        "commission": 0.0,
                        "swap": 0.0,
                        "fee": 0.0,
                    }
                ],
            },
        },
    }
    return json.dumps(body, separators=(",", ":")).encode()


class TelemetryInspectionTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 10, 21, 12, tzinfo=UTC)
        self.database = ProvisionPlan(
            self.root,
            "pilot.sqlite3",
            "demo-account",
            "Demo",
            "DEMO",
            "USD",
            "demo-source",
        ).apply(clock=self.now)

    def test_summary_is_read_only_and_deduplicates_repeated_history(self) -> None:
        with open_registry(self.database) as registry:
            registry.store_message(
                message(1, self.now, magic="11122", ticket="500"), received_at=self.now
            )
            registry.store_message(
                message(2, self.now + timedelta(seconds=5), magic="222", ticket="500"),
                received_at=self.now + timedelta(seconds=5),
            )
        before = self.database.read_bytes()
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect(verify=True)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(summary.source_ids, ("demo-source",))
        self.assertEqual((summary.message_count, summary.snapshot_count), (2, 2))
        self.assertEqual(summary.heartbeat_count, 0)
        self.assertEqual(summary.session_count, 1)
        self.assertEqual((summary.latest_positions, summary.latest_orders), (0, 1))
        self.assertEqual(summary.latest_history_status, "complete")
        self.assertEqual(summary.unique_historical_deals, 1)
        self.assertEqual(summary.magic_numbers, ("222", "11122"))

    def test_empty_database_and_invalid_inputs_are_explicit(self) -> None:
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        self.assertEqual(summary.message_count, 0)
        self.assertIsNone(summary.first_captured_at)
        self.assertEqual(summary.magic_numbers, ())
        with self.assertRaises(ValueError):
            InspectionPlan(self.root, "../pilot.sqlite3")
        with self.assertRaises(FileNotFoundError):
            InspectionPlan(self.root, "missing.sqlite3").inspect()

    def test_summary_uses_one_explicit_read_transaction(self) -> None:
        def assert_transaction(connection, database, version):
            self.assertTrue(connection.in_transaction)
            return summarize(connection, database, version)

        with patch(
            "tradinglab.telemetry.inspection._summarize",
            side_effect=assert_transaction,
        ):
            summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()

        self.assertEqual(summary.message_count, 0)

    def test_latest_counts_ignore_a_capture_ahead_of_its_reception(self) -> None:
        plausible = json.loads(message(1, self.now, magic="11122", ticket="500"))
        plausible["payload"]["orders_total"] = 0
        plausible["payload"]["orders"] = []
        future = message(
            2,
            self.now + timedelta(days=1),
            magic="222",
            ticket="501",
        )
        with open_registry(self.database) as registry:
            registry.store_message(
                json.dumps(plausible, separators=(",", ":")).encode(),
                received_at=self.now,
            )
            registry.store_message(future, received_at=self.now + timedelta(seconds=5))

        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()

        self.assertEqual(summary.message_count, 2)
        self.assertEqual(summary.latest_orders, 0)

    def test_deals_are_deduplicated_by_account_across_sources(self) -> None:
        with open_registry(self.database) as registry:
            registry.register_source("second-source", "demo-account", created_at=self.now)
            registry.store_message(
                message(1, self.now, magic="11122", ticket="500"), received_at=self.now
            )
            registry.store_message(
                message(
                    1,
                    self.now,
                    magic="11122",
                    ticket="500",
                    source_id="second-source",
                ),
                received_at=self.now,
            )
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        self.assertEqual(summary.source_ids, ("demo-source", "second-source"))
        self.assertEqual(summary.session_count, 2)
        self.assertEqual(summary.latest_orders, 2)
        self.assertEqual(summary.unique_historical_deals, 1)

    def test_same_deal_ticket_remains_distinct_between_accounts(self) -> None:
        with open_registry(self.database) as registry:
            registry.register_account(
                "second-account",
                "Second demo",
                "DEMO",
                "USD",
                created_at=self.now,
            )
            registry.register_source("second-source", "second-account", created_at=self.now)
            registry.store_message(
                message(1, self.now, magic="11122", ticket="500"), received_at=self.now
            )
            registry.store_message(
                message(
                    1,
                    self.now,
                    magic="11122",
                    ticket="500",
                    source_id="second-source",
                ),
                received_at=self.now,
            )

        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()

        self.assertEqual(summary.unique_historical_deals, 2)


if __name__ == "__main__":
    unittest.main()
