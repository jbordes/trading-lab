from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from test_mt5_telemetry import encoded
from test_telemetry_history import history_message

from tradinglab.telemetry.sqlite_store import (
    DealHistoryCursor,
    MessageAdmissionError,
    TelemetryStorageError,
    create_database,
    open_registry,
)


class DealHistoryQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "history.sqlite3"
        create_database(self.path)
        self.now = datetime(2026, 10, 20, 12, tzinfo=UTC)
        with open_registry(self.path) as registry:
            registry.register_account("a", "Demo A", "DEMO-SERVER", "USD", created_at=self.now)
            registry.register_account("b", "Demo B", "DEMO-SERVER", "USD", created_at=self.now)
            registry.register_source("demo-terminal-01", "a", created_at=self.now)
            registry.register_source("other-source", "b", created_at=self.now)

    def store(self, message: dict[str, object]) -> None:
        with open_registry(self.path) as registry:
            registry.store_message(encoded(message), received_at=self.now)

    def test_filters_account_period_and_magic_and_keeps_latest_correction(self) -> None:
        self.store(history_message())
        corrected = history_message(2)
        corrected["payload"]["history"]["deals"][1]["commission"] = -0.75
        self.store(corrected)

        other = history_message()
        other.update(source_id="other-source", event_id="other:1")
        self.store(other)

        with open_registry(self.path) as registry:
            page = registry.deal_history("a", from_msc=999_000, to_msc=1_000_000)
            filtered = registry.deal_history(
                "a", from_msc=999_000, to_msc=1_000_000, magic_number="0"
            )
            outside = registry.deal_history("a", from_msc=1, to_msc=999_000)

        self.assertEqual([deal.ticket for deal in page.deals], ["2", "1"])
        self.assertEqual(page.deals[0].commission, -0.75)
        self.assertTrue(all(deal.account_id == "a" for deal in page.deals))
        self.assertEqual(filtered.deals, ())
        self.assertEqual(outside.deals, ())

    def test_keyset_pagination_orders_uint64_tickets_without_gaps(self) -> None:
        message = history_message()
        prototype = message["payload"]["history"]["deals"][0]
        tickets = ["2", "9", "10", "18446744073709551615"]
        deals = [dict(prototype, ticket=ticket, time_msc="999001") for ticket in tickets]
        message["payload"]["history"].update(deals=deals, total=len(deals))
        self.store(message)

        with open_registry(self.path) as registry:
            first = registry.deal_history("a", from_msc=999_000, to_msc=1_000_000, limit=2)
            second = registry.deal_history(
                "a",
                from_msc=999_000,
                to_msc=1_000_000,
                limit=2,
                cursor=first.next_cursor,
            )

        self.assertEqual([deal.ticket for deal in first.deals], ["18446744073709551615", "10"])
        self.assertEqual(first.next_cursor, DealHistoryCursor(999_001, "10"))
        self.assertEqual([deal.ticket for deal in second.deals], ["9", "2"])
        self.assertIsNone(second.next_cursor)
        self.assertEqual(DealHistoryCursor.decode(first.next_cursor.encode()), first.next_cursor)

    def test_rejects_invalid_boundaries_cursor_and_unknown_account(self) -> None:
        with open_registry(self.path) as registry:
            invalid_calls = (
                lambda: registry.deal_history("a", from_msc=1, to_msc=1),
                lambda: registry.deal_history("a", from_msc=1, to_msc=2, limit=101),
                lambda: registry.deal_history("a", from_msc=1, to_msc=2, magic_number="01"),
            )
            for call in invalid_calls:
                with self.subTest(call=call), self.assertRaises(ValueError):
                    call()
            with self.assertRaises(MessageAdmissionError):
                registry.deal_history("unknown", from_msc=1, to_msc=2)
        for cursor in ("", "1", "01.2", "1.0", "x.2", "1.02"):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                DealHistoryCursor.decode(cursor)
        with self.assertRaises(ValueError):
            DealHistoryCursor(-1, "2")

    def test_detects_tampered_selected_message(self) -> None:
        self.store(history_message())
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE telemetry_messages SET content_sha256 = ?", ("0" * 64,))
            connection.commit()
        with open_registry(self.path) as registry:
            with self.assertRaises(TelemetryStorageError):
                registry.deal_history("a", from_msc=999_000, to_msc=1_000_000)


if __name__ == "__main__":
    unittest.main()
