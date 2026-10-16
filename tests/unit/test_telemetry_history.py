from __future__ import annotations

import json
import unittest
import urllib.request

import test_mt5_telemetry
from test_mt5_telemetry import TOKEN, encoded, snapshot_message

from tradinglab.telemetry.contract import TelemetryValidationError, parse_envelope
from tradinglab.telemetry.ingest import TelemetryBuffer


def history_message(sequence: int = 1) -> dict:
    message = snapshot_message(sequence=sequence)
    message["payload"].update(positions=[], positions_total=0)
    rows = []
    for ticket, entry in (("1", 0), ("2", 1)):
        rows.append(
            {
                "ticket": ticket,
                "order_id": "50",
                "position_id": "42",
                "magic_number": "11122",
                "time_msc": str(999000 + int(ticket)),
                "deal_type": 0,
                "entry": entry,
                "symbol": "TEST",
                "volume": 0.1,
                "price": 10.0,
                "profit": 1.0 if entry else 0.0,
                "commission": -0.1,
                "swap": -0.2,
                "fee": -0.01,
            }
        )
    message["payload"]["history"] = {
        "status": "complete",
        "from_server_seconds": "900",
        "to_server_seconds": "1000",
        "total": 2,
        "deals": rows,
    }
    return message


class TelemetryHistoryTest(unittest.TestCase):
    def test_history_limits_required_fields_and_same_millisecond_tickets(self) -> None:
        message = history_message()
        history = message["payload"]["history"]
        history["deals"][1]["time_msc"] = history["deals"][0]["time_msc"]
        parse_envelope(encoded(message))
        for field in history["deals"][0]:
            malformed = history_message()
            del malformed["payload"]["history"]["deals"][0][field]
            with self.subTest(missing=field), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(malformed))
        history["deals"] = [dict(history["deals"][0], ticket=str(i + 1)) for i in range(200)]
        history["total"] = 200
        parse_envelope(encoded(message))
        history["deals"].append(dict(history["deals"][0], ticket="201"))
        history["total"] = 201
        with self.assertRaises(TelemetryValidationError):
            parse_envelope(encoded(message))

    def test_short_lived_position_is_recovered_and_overlap_is_not_appended(self) -> None:
        buffer = TelemetryBuffer()
        for sequence in (1, 2, 3):
            buffer.accept(parse_envelope(encoded(history_message(sequence))))
        view = buffer.recent_deals("demo-terminal-01")
        self.assertEqual([row["entry"] for row in view["deals"]], [0, 1])
        self.assertEqual(len(view["deals"]), 2)
        self.assertEqual(view["deals"][1]["fee"], -0.01)
        self.assertEqual(buffer.recent_deals("demo-terminal-01", magic_number="0")["deals"], [])
        self.assertEqual(buffer.recent_deals("another-account")["status"], "unavailable")

    def test_restart_and_full_window_corrections_replace_previous_view(self) -> None:
        buffer = TelemetryBuffer()
        buffer.accept(parse_envelope(encoded(history_message())))
        updated = history_message()
        updated["session_id"] = "restarted"
        updated["event_id"] = "restarted:1"
        updated["payload"]["history"]["deals"][1]["commission"] = -0.5
        buffer.accept(parse_envelope(encoded(updated)))
        view = buffer.recent_deals("demo-terminal-01")
        self.assertEqual(len(view["deals"]), 2)
        self.assertEqual(view["deals"][1]["commission"], -0.5)
        view["deals"].clear()
        self.assertEqual(len(buffer.recent_deals("demo-terminal-01")["deals"]), 2)
        restarted_receiver = TelemetryBuffer()
        restarted_receiver.accept(parse_envelope(encoded(updated)))
        self.assertEqual(
            restarted_receiver.recent_deals("demo-terminal-01"),
            buffer.recent_deals("demo-terminal-01"),
        )
        corrected = history_message(2)
        corrected["payload"]["history"].update(deals=[], total=0)
        buffer.accept(parse_envelope(encoded(corrected)))
        self.assertEqual(buffer.recent_deals("demo-terminal-01")["deals"], [])

    def test_failed_and_truncated_history_are_never_reported_complete(self) -> None:
        buffer = TelemetryBuffer()
        buffer.accept(parse_envelope(encoded(history_message())))
        message = history_message(2)
        message["payload"]["history"].update(status="error", total=0, deals=[])
        buffer.accept(parse_envelope(encoded(message)))
        self.assertEqual(buffer.recent_deals("demo-terminal-01")["status"], "error")
        self.assertEqual(buffer.recent_deals("demo-terminal-01")["deals"], [])
        message = history_message(3)
        message["payload"]["history"].update(status="truncated", total=500)
        buffer.accept(parse_envelope(encoded(message)))
        self.assertEqual(buffer.state()["history_status"], "truncated")
        self.assertEqual(buffer.state()["history_retained"], 2)
        buffer.accept(parse_envelope(encoded(history_message(4))))
        self.assertEqual(buffer.recent_deals("demo-terminal-01")["status"], "complete")

    def test_invalid_history_and_deal_fields_are_rejected(self) -> None:
        for field, value in (
            ("status", []),
            ("status", "ok"),
            ("total", 0),
            ("from_server_seconds", "1001"),
            ("deals", {}),
        ):
            message = history_message()
            message["payload"]["history"][field] = value
            with self.subTest(field=field), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))
        for field, value in (
            ("ticket", "abc"),
            ("entry", True),
            ("deal_type", 18),
            ("fee", "0"),
            ("profit", float("nan")),
            ("time_msc", "1"),
            ("position_id", "-1"),
            ("magic_number", "x"),
        ):
            message = history_message()
            message["payload"]["history"]["deals"][0][field] = value
            with self.subTest(field=field), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))
        message = history_message()
        message["payload"]["history"]["deals"][1]["ticket"] = "1"
        with self.assertRaises(TelemetryValidationError):
            parse_envelope(encoded(message))

    def test_non_trade_ledger_entry_allows_empty_symbol_and_zero_ids(self) -> None:
        message = history_message()
        message["payload"]["history"]["deals"][0].update(
            deal_type=2, symbol="", order_id="0", position_id="0", volume=0.0, magic_number="0"
        )
        parse_envelope(encoded(message))


class TelemetryHistoryHttpTest(unittest.TestCase):
    # Reuse only lifecycle helpers, not the other TestCase's test methods.
    setUp = test_mt5_telemetry.TelemetryServerTest.setUp
    tearDown = test_mt5_telemetry.TelemetryServerTest.tearDown

    def test_history_reconciliation_over_http_and_safe_health(self) -> None:
        for sequence in (1, 2):
            request = urllib.request.Request(
                f"{self.base_url}/v1/telemetry",
                data=encoded(history_message(sequence)),
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 202)
        self.assertEqual(len(self.buffer.recent_deals("demo-terminal-01")["deals"]), 2)
        with urllib.request.urlopen(f"{self.base_url}/health", timeout=2) as response:
            health = json.loads(response.read())
        self.assertEqual(health["history_status"], "complete")
        self.assertNotIn("latest", health)
        self.assertNotIn("deals", health)


if __name__ == "__main__":
    unittest.main()
