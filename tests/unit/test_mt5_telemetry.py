from __future__ import annotations

import http.client
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
                    "take_profit": 0.0,
                    "swap": -0.5,
                    "opened_at_msc": "1792100000000",
                    "comment": "",
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
                    "comment": "test",
                }
            ],
        },
    }


def encoded(message: dict[str, object]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode()


class TelemetryContractTest(unittest.TestCase):
    def test_rejects_duplicate_tickets_and_invalid_counts(self) -> None:
        message = snapshot_message()
        message["payload"]["positions"] *= 2
        message["payload"]["positions_total"] = 2
        with self.assertRaises(TelemetryValidationError):
            parse_envelope(encoded(message))
        for value in (True, -1, 2**63, "1"):
            message = snapshot_message()
            message["sequence"] = value
            with self.subTest(sequence=value), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))
            message = snapshot_message()
            message["payload"]["positions_total"] = value
            with self.subTest(total=value), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))

    def test_rejects_unhashable_reason_and_numeric_overflow(self) -> None:
        for value in ([], {}, None, True):
            message = snapshot_message()
            message["payload"]["reason"] = value
            with self.subTest(value=value), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))
        message = snapshot_message()
        message["payload"]["account"]["equity"] = 10**400
        with self.assertRaises(TelemetryValidationError):
            parse_envelope(encoded(message))

    def test_rejects_malformed_json_and_duplicate_keys(self) -> None:
        valid = encoded(snapshot_message())
        bodies = (
            b"\xff",
            b"{",
            b"[]",
            b"[" * 2000 + b"]" * 2000,
            b'{"sequence":' + b"9" * 5000 + b"}",
            valid.replace(b'"sequence":1', b'"sequence":1,"sequence":2'),
            valid.replace(b'"reason":"timer"', b'"reason":"timer","reason":"startup"'),
        )
        for body in bodies:
            with self.subTest(size=len(body)), self.assertRaises(TelemetryValidationError):
                parse_envelope(body)

    def test_rejects_invalid_unicode_before_fingerprinting(self) -> None:
        message = snapshot_message()
        message["payload"]["orders"][0]["comment"] = "\ud800"
        with self.assertRaises(TelemetryValidationError):
            parse_envelope(encoded(message))

    def test_operation_fields_are_required_and_typed(self) -> None:
        for collection in ("positions", "orders"):
            original = snapshot_message()["payload"][collection][0]
            for field in original:
                message = snapshot_message()
                del message["payload"][collection][0][field]
                with self.subTest(collection=collection, missing=field):
                    with self.assertRaises(TelemetryValidationError):
                        parse_envelope(encoded(message))
            for field, value in (
                ("ticket", "abc"),
                ("ticket", "0"),
                ("ticket", str(2**64)),
                ("magic_number", "incorrecto"),
                ("magic_number", 11122),
                ("magic_number", "１２"),
                ("volume", "banana"),
                ("volume", True),
                ("volume", -1),
                ("symbol", ""),
                ("comment", None),
                ("comment", "x" * 257),
                ("unexpected", 1),
                ("price_open", None),
            ):
                message = snapshot_message()
                message["payload"][collection][0][field] = value
                with self.subTest(collection=collection, field=field, value=value):
                    with self.assertRaises(TelemetryValidationError):
                        parse_envelope(encoded(message))
        for collection, field, value in (
            ("positions", "profit", "banana"),
            ("positions", "operation_type", True),
            ("positions", "operation_type", 2),
            ("positions", "position_id", "-1"),
            ("positions", "opened_at_msc", "yesterday"),
            ("orders", "order_type", 9),
            ("orders", "created_at_msc", "-1"),
        ):
            message = snapshot_message()
            message["payload"][collection][0][field] = value
            with self.subTest(field=field), self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))

    def test_valid_empty_truncated_and_signed_magic_snapshots(self) -> None:
        message = snapshot_message()
        message["payload"]["positions"][0]["magic_number"] = str(-(2**63))
        message["payload"]["positions_total"] = 100
        parse_envelope(encoded(message))
        message["payload"].update(positions=[], orders=[], positions_total=0, orders_total=0)
        parse_envelope(encoded(message))
        message["kind"] = "heartbeat"
        message["payload"] = {"status": "ok"}
        parse_envelope(encoded(message))

    def test_timestamp_preserves_subseconds_and_rejects_loose_formats(self) -> None:
        message = snapshot_message()
        message["captured_at"] = "2026-10-16T01:02:03.123456Z"
        self.assertEqual(parse_envelope(encoded(message)).captured_at, message["captured_at"])
        for value in ("20261016Z", "2026-10-16 01:02:03Z", "2026-02-30T00:00:00Z"):
            message["captured_at"] = value
            with self.assertRaises(TelemetryValidationError):
                parse_envelope(encoded(message))

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
        for value in (float("nan"), float("inf"), float("-inf")):
            for scope in ("account", "positions", "orders"):
                with self.subTest(value=value, scope=scope):
                    message = snapshot_message()
                    payload = message["payload"]
                    if scope == "account":
                        payload["account"]["equity"] = value
                    else:
                        payload[scope] = [{"ticket": "1", "magic_number": "2", "profit": value}]
                        payload[f"{scope}_total"] = 1
                    with self.assertRaisesRegex(TelemetryValidationError, "finito"):
                        parse_envelope(encoded(message))

    def test_real_zero_and_negative_values_are_preserved(self) -> None:
        message = snapshot_message()
        message["payload"]["account"]["equity"] = 0.0
        envelope = parse_envelope(encoded(message))
        self.assertEqual(envelope.payload["account"]["equity"], 0.0)
        self.assertEqual(envelope.payload["positions"][0]["profit"], -50.0)


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

    def test_recovery_after_outbox_loss_and_ambiguous_ack(self) -> None:
        buffer = TelemetryBuffer()
        first = parse_envelope(encoded(snapshot_message(sequence=1)))
        buffer.accept(first)
        # The response was lost: retry the identical message before later samples.
        self.assertEqual(buffer.accept(first).status, "duplicate")
        # Samples 2..13 were discarded during the outage; retained FIFO resumes.
        for sequence in range(14, 26):
            buffer.accept(parse_envelope(encoded(snapshot_message(sequence=sequence))))
        state = buffer.state()
        self.assertEqual(state["missing_sequences"], 12)
        self.assertEqual(state["duplicates"], 1)
        self.assertEqual(state["accepted"], 13)
        self.assertEqual(state["latest"]["sequence"], 25)

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
    def test_bad_inputs_are_controlled_and_do_not_mutate_buffer(self) -> None:
        reason = snapshot_message()
        reason["payload"]["reason"] = []
        overflow = snapshot_message()
        overflow["payload"]["account"]["equity"] = 10**400
        bad_row = snapshot_message()
        bad_row["payload"]["positions"][0]["profit"] = "banana"
        surrogate = snapshot_message()
        surrogate["payload"]["positions"][0]["comment"] = "\ud800"
        for body in (
            encoded(reason),
            encoded(overflow),
            encoded(bad_row),
            encoded(surrogate),
            b"[" * 2000 + b"]" * 2000,
        ):
            request = urllib.request.Request(
                f"{self.base_url}/v1/telemetry",
                data=body,
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=2)
            with caught.exception as response:
                self.assertEqual(response.code, 400)
                self.assertEqual(json.loads(response.read()), {"error": "invalid_message"})
            self.assertEqual(self.buffer.state()["accepted"], 0)
        self.test_accepts_authenticated_json_and_reports_health()

    def test_invalid_authorization_and_ambiguous_headers(self) -> None:
        cases = [
            ([("Authorization", "Bearer é")], 401),
            ([("Authorization", f"Bearer {TOKEN}"), ("Authorization", f"Bearer {TOKEN}")], 401),
            ([("Authorization", f"Bearer {TOKEN}"), ("Content-Length", "2")], 400),
            ([("Authorization", f"Bearer {TOKEN}"), ("Transfer-Encoding", "chunked")], 400),
        ]
        for headers, expected in cases:
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
            try:
                connection.putrequest("POST", "/v1/telemetry")
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", "2")
                for key, value in headers:
                    connection.putheader(key, value)
                connection.endheaders(b"{}")
                with connection.getresponse() as response:
                    self.assertEqual(response.status, expected)
                    response.read()
            finally:
                connection.close()
        self.assertEqual(self.buffer.state()["accepted"], 0)

    def test_rejects_invalid_token_configuration(self) -> None:
        for token in ("é" * 24, "x" * 24 + "\r\n", "x" * 24 + " "):
            with self.subTest(token_length=len(token)), self.assertRaises(ValueError):
                create_telemetry_server(TelemetryBuffer(), token=token, port=0)

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
    def test_pilot_guards_cover_capture_and_delivery(self) -> None:
        source = (ROOT / "apps/mt5-telemetry-collector/TradingLabTelemetry.mq5").read_text(
            encoding="utf-8"
        )
        timer = source.split("void OnTimer()", 1)[1].split("bool CheckPilotSafety()", 1)[0]
        self.assertLess(timer.index("CheckPilotSafety()"), timer.index("BuildSnapshot("))
        self.assertEqual(timer.count("CheckPilotSafety()"), 2)
        send = source.split("int SendMessage(", 1)[1].split("#endif", 1)[0]
        self.assertLess(send.index("CheckPilotSafety()"), send.index("WebRequest("))
        self.assertIn("!IsLoopbackIngestUrl(IngestUrl)", send)
        guard = source.split("bool CheckPilotSafety()", 1)[1].split("#endif", 1)[0]
        self.assertIn("GetLastError() == 0", guard)
        self.assertIn("safety_stopped = true;", guard)
        self.assertIn("EventKillTimer();", guard)
        self.assertIn('DropHead("pilot_guard")', guard)
        self.assertIn("mode == ACCOUNT_TRADE_MODE_DEMO", source)
        self.assertIn("login == expected_login && server == expected_server", source)

    def test_numeric_validity_propagates_through_all_snapshot_sections(self) -> None:
        source = (ROOT / "apps/mt5-telemetry-collector/TradingLabTelemetry.mq5").read_text(
            encoding="utf-8"
        )
        for section in ("BuildAccount", "BuildPositions", "BuildOrders"):
            self.assertIn(f"{section}(valid)", source)
            self.assertIn(f"string {section}(bool &valid)", source)
        calls = [line for line in source.splitlines() if "+ JsonNumber(" in line]
        self.assertTrue(calls)
        self.assertTrue(all(", valid)" in line for line in calls))
        self.assertIn("return FinalizeSnapshot(body, valid);", source)
        numeric = source.split("string JsonNumber(", 1)[1].split("string UnsignedIdentifier", 1)[0]
        self.assertIn("valid = false;", numeric)
        self.assertNotIn('return "0";', numeric)
        enqueue = source.split("void EnqueueSnapshot(", 1)[1].split("bool TrySendQueued", 1)[0]
        self.assertLess(
            enqueue.index('RecordDrop(sequence, "invalid_numeric")'),
            enqueue.index("outbox_count == OUTBOX_CAPACITY"),
        )

    def test_capture_precedes_delivery_without_pending_message_gate(self) -> None:
        source = (ROOT / "apps/mt5-telemetry-collector/TradingLabTelemetry.mq5").read_text(
            encoding="utf-8"
        )
        timer = source.split("void OnTimer()", 1)[1].split("void RemoveHead()", 1)[0]
        self.assertNotIn("pending_body", source)
        self.assertLess(timer.index("EnqueueSnapshot("), timer.index("TrySendQueued("))
        self.assertEqual(timer.count("TrySendQueued("), 2)
        self.assertNotIn("Sleep(", source)

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
