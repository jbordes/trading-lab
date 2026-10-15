from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from tradinglab.telemetry.contract import (  # noqa: E402
    TelemetryValidationError,
    parse_envelope,
)
from tradinglab.telemetry.ingest import (  # noqa: E402
    TelemetryBuffer,
    TelemetryConflictError,
    TelemetryStaleError,
    create_telemetry_server,
)

TOKEN = "example-local-token-with-at-least-24-characters"


def snapshot_message(*, sequence: int = 1, event_id: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "mt5-telemetry-v1",
        "collector_version": "0.1.0",
        "source_id": "demo-terminal-01",
        "session_id": "session-20261015-001",
        "sequence": sequence,
        "event_id": event_id or f"session-20261015-001:{sequence}",
        "captured_at": "2026-10-15T21:30:00Z",
        "kind": "account_snapshot",
        "payload": {
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
            "orders_total": 0,
            "positions": [
                {
                    "ticket": "9223372036854775000",
                    "magic_number": "11122",
                    "symbol": "XAUUSD",
                    "profit": -50.0,
                }
            ],
            "orders": [],
        },
    }


def encoded(message: dict[str, object]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode()


class TelemetryContractTest(unittest.TestCase):
    def test_valid_snapshot_preserves_large_identifiers_as_text(self) -> None:
        envelope = parse_envelope(encoded(snapshot_message()))

        self.assertEqual(envelope.sequence, 1)
        self.assertEqual(envelope.payload["positions"][0]["ticket"], "9223372036854775000")

    def test_rejects_unmasked_account(self) -> None:
        message = snapshot_message()
        message["payload"]["account"]["login_masked"] = "12345678"  # type: ignore[index]

        with self.assertRaisesRegex(TelemetryValidationError, "enmascarado"):
            parse_envelope(encoded(message))

    def test_rejects_unknown_top_level_fields(self) -> None:
        message = snapshot_message()
        message["command"] = "close_positions"

        with self.assertRaisesRegex(TelemetryValidationError, "no admitidos"):
            parse_envelope(encoded(message))

    def test_rejects_non_finite_numbers(self) -> None:
        message = snapshot_message()
        message["payload"]["account"]["equity"] = float("nan")  # type: ignore[index]

        with self.assertRaisesRegex(TelemetryValidationError, "finito"):
            parse_envelope(encoded(message))


class TelemetryBufferTest(unittest.TestCase):
    def test_duplicate_is_idempotent(self) -> None:
        buffer = TelemetryBuffer()
        envelope = parse_envelope(encoded(snapshot_message()))

        first = buffer.accept(envelope)
        second = buffer.accept(envelope)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(buffer.state()["accepted"], 1)
        self.assertEqual(buffer.state()["duplicates"], 1)

    def test_sequence_gap_is_visible(self) -> None:
        buffer = TelemetryBuffer()

        outcome = buffer.accept(parse_envelope(encoded(snapshot_message(sequence=3))))

        self.assertEqual(outcome.sequence_gap, 2)
        self.assertEqual(buffer.state()["missing_sequences"], 2)

    def test_reused_sequence_with_other_content_is_conflict(self) -> None:
        buffer = TelemetryBuffer()
        buffer.accept(parse_envelope(encoded(snapshot_message())))
        changed = snapshot_message(event_id="different-event")

        with self.assertRaises(TelemetryConflictError):
            buffer.accept(parse_envelope(encoded(changed)))

    def test_unseen_old_sequence_is_stale(self) -> None:
        buffer = TelemetryBuffer()
        buffer.accept(parse_envelope(encoded(snapshot_message(sequence=2))))

        with self.assertRaises(TelemetryStaleError):
            buffer.accept(parse_envelope(encoded(snapshot_message(sequence=1))))


class TelemetryServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.buffer = TelemetryBuffer()
        self.server = create_telemetry_server(self.buffer, token=TOKEN, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_accepts_authenticated_json_and_reports_health(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/v1/telemetry",
            data=encoded(snapshot_message()),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=2) as response:
            result = json.loads(response.read())
            self.assertEqual(response.status, 202)
            self.assertEqual(result["status"], "accepted")
        with urllib.request.urlopen(f"{self.base_url}/health", timeout=2) as response:
            health = json.loads(response.read())
            self.assertEqual(health["accepted"], 1)
            self.assertNotIn("latest", health)

    def test_rejects_missing_token_without_echoing_secret(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/v1/telemetry",
            data=encoded(snapshot_message()),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)

        error = caught.exception
        try:
            self.assertEqual(error.code, 401)
            self.assertNotIn(TOKEN, error.read().decode())
        finally:
            error.close()

    def test_rejects_mutating_methods_other_than_ingestion_post(self) -> None:
        request = urllib.request.Request(f"{self.base_url}/health", data=b"", method="DELETE")

        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)

        error = caught.exception
        try:
            self.assertEqual(error.code, 405)
        finally:
            error.close()


class Mql5CollectorSafetyTest(unittest.TestCase):
    def test_collector_source_has_no_trading_or_dll_calls(self) -> None:
        source = (ROOT / "apps" / "mt5-telemetry-collector" / "TradingLabTelemetry.mq5").read_text(
            encoding="utf-8"
        )
        normalized = source.casefold().replace(" ", "")

        forbidden = ("ordersend(", "ctrade", "#import", "positionclose(", "orderdelete(")
        for pattern in forbidden:
            self.assertNotIn(pattern, normalized)
        self.assertIn("webrequest(", normalized)
        self.assertIn("ontradetransaction(", normalized)


if __name__ == "__main__":
    unittest.main()
