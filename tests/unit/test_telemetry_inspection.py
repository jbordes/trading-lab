from __future__ import annotations

import io
import json
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from storage_fixtures import SnapshotTestPlan  # noqa: E402

from tradinglab.telemetry.admission_v2 import (  # noqa: E402
    ProducerIdentity,
    ProducerRegistration,
    ProducerRole,
    TradingEventsProducerDirectory,
)
from tradinglab.telemetry.inspection import InspectionPlan  # noqa: E402
from tradinglab.telemetry.inspection import _summarize as summarize  # noqa: E402
from tradinglab.telemetry.sqlite_store import open_registry  # noqa: E402
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry  # noqa: E402


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
        "schema_version": "mt5-account-state-v1",
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
    @staticmethod
    def events_document(name: str) -> dict[str, Any]:
        fixture = Path(__file__).parents[1] / "fixtures/telemetry_v2" / f"{name}.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        document["payload"]["identity"]["server"] = "DEMO"
        return document

    def store_events(self, document: dict[str, Any], account: str = "demo-account") -> None:
        identity = ProducerIdentity("****1234", "DEMO", "USD")
        role = ProducerRole.ACTIVITY if "activity" in document["source_id"] else ProducerRole.LIVE
        credential = "synthetic-inspection-credential-safe-length"
        directory = TradingEventsProducerDirectory(
            (ProducerRegistration(account, document["source_id"], role, identity, credential),)
        )
        authorized = directory.authorize(json.dumps(document).encode(), f"Bearer {credential}")
        with open_v2_registry(self.database) as registry:
            if account != "demo-account":
                registry.register_account(account, "Other", identity, created_at=self.now)
            registry.register_source(document["source_id"], account, role, created_at=self.now)
            registry.store_authorized(authorized, received_at=self.now + timedelta(days=2))

    def test_activity_only_database_reports_trading_messages_entities_and_magics(self) -> None:
        self.store_events(self.events_document("activity-position-reconcile"))
        before = self.database.read_bytes()
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect(verify=True)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual((summary.message_count, summary.session_count), (1, 1))
        self.assertEqual(
            (summary.account_state_message_count, summary.trading_events_message_count), (0, 1)
        )
        self.assertEqual((summary.snapshot_count, summary.activity_batch_count), (0, 1))
        self.assertEqual(
            (summary.unique_historical_deals, summary.unique_historical_orders), (2, 2)
        )
        self.assertEqual(summary.magic_numbers, ("11122",))
        self.assertIsNotNone(summary.first_captured_at)
        self.assertEqual((summary.latest_positions, summary.latest_orders), (0, 0))

    def test_mixed_channels_deduplicate_same_account_deal_and_include_live_magics(self) -> None:
        activity = self.events_document("activity-truncated")
        ticket = activity["payload"]["deals"]["items"][0]["ticket"]
        with open_registry(self.database) as registry:
            registry.store_message(
                message(1, self.now, magic="222", ticket=ticket), received_at=self.now
            )
        self.store_events(activity)
        live = self.events_document("live-empty")
        live["payload"]["orders"] = json.loads(message(1, self.now, magic="-7", ticket="1"))[
            "payload"
        ]["orders"]
        live["payload"]["orders_total"] = 1
        self.store_events(live)
        self.store_events(self.events_document("heartbeat"))
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        self.assertEqual((summary.message_count, summary.session_count), (4, 3))
        self.assertEqual(
            (summary.account_state_message_count, summary.trading_events_message_count), (1, 3)
        )
        self.assertEqual(
            (
                summary.live_snapshot_count,
                summary.activity_batch_count,
                summary.trading_heartbeat_count,
            ),
            (1, 1, 1),
        )
        self.assertEqual(summary.unique_historical_deals, 1)
        self.assertEqual(summary.magic_numbers, ("-7", "222", "11122"))
        self.assertEqual(summary.latest_orders, 1)  # account-state only, never added to live.
        self.assertTrue(summary.first_captured_at.startswith("2026-10-21"))
        self.assertTrue(summary.last_captured_at.startswith("2026-10-22"))

    def test_activity_history_deduplicates_revisions_but_not_accounts_or_large_tickets(
        self,
    ) -> None:
        first = self.events_document("activity-truncated")
        first["payload"]["deals"]["items"][0]["ticket"] = "18446744073709551615"
        self.store_events(first)
        repeated = self.events_document("activity-truncated")
        repeated["payload"]["deals"]["items"][0]["ticket"] = "18446744073709551615"
        repeated.update(session_id="second-session", event_id="second-session:3")
        self.store_events(repeated)
        other = self.events_document("activity-truncated")
        other["payload"]["deals"]["items"][0]["ticket"] = "18446744073709551615"
        other["source_id"] = "other-activity"
        self.store_events(other, "other-account")
        different = self.events_document("activity-truncated")
        different["payload"]["deals"]["items"][0]["ticket"] = "18446744073709551614"
        different.update(session_id="third-session", event_id="third-session:3")
        self.store_events(different)
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        self.assertEqual(summary.message_count, 4)
        self.assertEqual(summary.unique_historical_deals, 3)

    def test_canceled_order_is_observed_without_creating_a_deal(self) -> None:
        self.store_events(self.events_document("activity-canceled-order"))
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        self.assertEqual(
            (summary.unique_historical_orders, summary.unique_historical_deals), (1, 0)
        )
        self.assertEqual(summary.magic_numbers, ("11122",))

    def test_heartbeat_counts_remain_explicit_per_contract(self) -> None:
        heartbeat = json.loads(message(1, self.now, magic="11122", ticket="1"))
        heartbeat.update(kind="heartbeat", payload={"status": "ok"})
        with open_registry(self.database) as registry:
            registry.store_message(json.dumps(heartbeat).encode(), received_at=self.now)
        self.store_events(self.events_document("heartbeat"))
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        self.assertEqual(summary.message_count, 2)
        self.assertEqual((summary.heartbeat_count, summary.trading_heartbeat_count), (1, 1))
        self.assertEqual(
            (summary.snapshot_count, summary.live_snapshot_count, summary.activity_batch_count),
            (0, 0, 0),
        )
        self.assertEqual(summary.unique_historical_deals, 0)
        self.assertEqual(summary.magic_numbers, ())

    def test_cli_describes_both_channels_without_printing_raw_records(self) -> None:
        self.store_events(self.events_document("activity-position-reconcile"))
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        main = runpy.run_path(str(Path(__file__).parents[2] / "scripts/inspect_telemetry_db.py"))[
            "main"
        ]
        output = io.StringIO()
        with patch.object(InspectionPlan, "inspect", return_value=summary), redirect_stdout(output):
            self.assertEqual(main(["--filename", "pilot.sqlite3"]), 0)
        text = output.getvalue()
        self.assertIn("Account-state: 0 mensajes", text)
        self.assertIn("Trading-events: 1 mensajes", text)
        self.assertIn("ambos contratos", text)
        for private in (
            "****1234",
            "demo-account",
            "700000000000000001",
            "profit",
            "synthetic-inspection-credential",
        ):
            self.assertNotIn(private, text)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 10, 21, 12, tzinfo=UTC)
        self.database = SnapshotTestPlan(
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
        self.assertEqual(
            (summary.account_state_message_count, summary.trading_events_message_count), (0, 0)
        )
        self.assertEqual(
            (
                summary.live_snapshot_count,
                summary.activity_batch_count,
                summary.trading_heartbeat_count,
                summary.unique_historical_orders,
            ),
            (0, 0, 0, 0),
        )
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

    def test_deals_are_deduplicated_across_observations(self) -> None:
        with open_registry(self.database) as registry:
            registry.store_message(
                message(1, self.now, magic="11122", ticket="500"), received_at=self.now
            )
            registry.store_message(
                message(
                    2,
                    self.now,
                    magic="11122",
                    ticket="500",
                    source_id="demo-source",
                ),
                received_at=self.now,
            )
        summary = InspectionPlan(self.root, "pilot.sqlite3").inspect()
        self.assertEqual(summary.source_ids, ("demo-source",))
        self.assertEqual(summary.session_count, 1)
        self.assertEqual(summary.latest_orders, 1)
        self.assertEqual(summary.unique_historical_deals, 1)

    def test_same_deal_ticket_remains_distinct_between_accounts(self) -> None:
        with open_registry(self.database) as registry:
            registry.register_account(
                "second-account",
                "Second demo",
                "DEMO",
                "USD",
                login_masked="****1234",
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
