from __future__ import annotations

import socket
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch

from test_mt5_telemetry import TOKEN, encoded, snapshot_message

from tradinglab.telemetry.contract import TelemetryValidationError, parse_envelope
from tradinglab.telemetry.ingest import (
    TelemetryBuffer,
    TelemetryStaleError,
    create_telemetry_server,
)


class BufferLimitsTest(unittest.TestCase):
    def test_sessions_and_indexes_remain_bounded_under_churn(self) -> None:
        buffer = TelemetryBuffer(max_messages=3)
        for index in range(100):
            message = snapshot_message()
            message["session_id"] = f"session-{index}"
            message["event_id"] = f"session-{index}:1"
            buffer.accept(parse_envelope(encoded(message)))
        self.assertEqual(buffer.state()["retained_sessions"], 3)
        self.assertEqual(len(buffer._fingerprints), 3)
        self.assertEqual(len(buffer._event_fingerprints), 3)
        self.assertEqual(len(buffer._message_sizes), 3)

    def test_byte_budget_evicts_and_does_not_retain_oversize_message(self) -> None:
        envelope = parse_envelope(encoded(snapshot_message()))
        size = len(envelope.canonical_bytes())
        buffer = TelemetryBuffer(max_retained_bytes=size)
        buffer.accept(envelope)
        message = snapshot_message(sequence=2)
        buffer.accept(parse_envelope(encoded(message)))
        self.assertEqual(buffer.state()["retained"], 1)
        self.assertEqual(buffer.state()["retained_bytes"], size)
        message = snapshot_message(sequence=3)
        message["payload"]["positions"][0]["comment"] = "larger"
        with self.assertRaises(TelemetryValidationError):
            buffer.accept(parse_envelope(encoded(message)))
        self.assertEqual(buffer.state()["accepted"], 2)
        self.assertEqual(buffer.state()["latest"]["sequence"], 2)

    def test_replay_policy_after_partial_and_complete_session_eviction(self) -> None:
        buffer = TelemetryBuffer(max_messages=1)
        first = parse_envelope(encoded(snapshot_message()))
        buffer.accept(first)
        buffer.accept(parse_envelope(encoded(snapshot_message(sequence=2))))
        with self.assertRaises(TelemetryStaleError):
            buffer.accept(first)
        other = snapshot_message()
        other.update(session_id="new-session", event_id="new-session:1")
        buffer.accept(parse_envelope(encoded(other)))
        # Once all memory of a session has expired, it is treated as unseen.
        self.assertEqual(buffer.accept(first).status, "accepted")
        self.assertEqual(buffer.state()["retained_sessions"], 1)

    def test_caller_cannot_mutate_owned_payload_or_bypass_budget(self) -> None:
        buffer = TelemetryBuffer()
        envelope = parse_envelope(encoded(snapshot_message()))
        buffer.accept(envelope)
        envelope.payload["positions"].clear()
        view = buffer.state()
        view["latest"]["payload"]["positions"].clear()
        self.assertEqual(len(buffer.state()["latest"]["payload"]["positions"]), 1)
        self.assertIsNone(buffer.state(include_latest=False)["latest"])

    def test_invalid_limits_fail_before_binding(self) -> None:
        for value in (0, -1, True, 33):
            with self.subTest(connections=value), self.assertRaises(ValueError):
                create_telemetry_server(
                    TelemetryBuffer(), token=TOKEN, port=0, max_connections=value
                )
        for value in (0, float("inf"), float("nan"), "5", True):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                create_telemetry_server(
                    TelemetryBuffer(), token=TOKEN, port=0, request_timeout=value
                )
        for value in (0, -1, True, 65 * 1024 * 1024):
            with self.assertRaises(ValueError):
                TelemetryBuffer(max_retained_bytes=value)


class NetworkLimitsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.buffer = TelemetryBuffer()
        self.server = create_telemetry_server(
            self.buffer, token=TOKEN, port=0, max_connections=1, request_timeout=0.2
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.clients: list[socket.socket] = []

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        for client in self.clients:
            client.close()
        self.thread.join(timeout=2)

    def connect(self) -> socket.socket:
        client = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2)
        self.clients.append(client)
        return client

    def wait_active(self, count: int) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.server.connection_state()["active_connections"] == count:
                return
            threading.Event().wait(0.005)
        self.fail(f"active connections did not become {count}")

    def test_incomplete_body_and_headers_release_workers(self) -> None:
        requests = (
            b"GET /health HTTP/1.0\r\nX-Incomplete:",
            (
                f"POST /v1/telemetry HTTP/1.0\r\nAuthorization: Bearer {TOKEN}\r\n"
                "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{"
            ).encode(),
        )
        for request in requests:
            client = self.connect()
            client.sendall(request)
            try:
                while client.recv(4096):
                    pass
            except ConnectionError:
                pass
            self.wait_active(0)
        self.assertEqual(self.buffer.state()["accepted"], 0)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/health", timeout=2
        ) as response:
            self.assertEqual(response.status, 200)

    def test_admission_limit_and_absolute_deadline_are_independent_of_progress(self) -> None:
        # Drive the absolute timer explicitly; do not race the short inactivity test timeout.
        self.server._request_timeout = 1
        ready = threading.Event()
        timers = []

        class ControlledTimer:
            ident = None
            daemon = True

            def __init__(self, interval, callback, args):
                self.callback, self.args = callback, args
                self.cancelled = False
                timers.append(self)

            def start(self):
                ready.set()

            def cancel(self):
                self.cancelled = True

        with patch("tradinglab.telemetry.http_server.threading.Timer", ControlledTimer):
            client = self.connect()
            self.assertTrue(ready.wait(2))
            client.sendall(b"GET /health HTTP/1.0\r\nX-Slow: ")
            extra = self.connect()
            self.assertEqual(extra.recv(1), b"")
            self.assertEqual(self.server.connection_state()["rejected_connections"], 1)
            self.assertEqual(len(timers), 1)  # excess connection created no worker/timer
            client.sendall(b"still-progressing")
            timers[0].callback(*timers[0].args)  # absolute deadline expires, independent of reads
            try:
                while client.recv(4096):
                    pass
            except ConnectionError:
                pass
            self.wait_active(0)
            self.assertTrue(timers[0].cancelled)
        self.assertEqual(self.server.connection_state()["expired_connections"], 1)

    def test_server_close_closes_peer_and_workers_exit_within_timeout(self) -> None:
        client = self.connect()
        self.wait_active(1)
        self.server.shutdown()
        self.server.server_close()
        self.assertEqual(client.recv(1), b"")
        self.wait_active(0)

    def test_thread_creation_failure_releases_slot(self) -> None:
        left, right = socket.socketpair()
        try:
            with patch(
                "tradinglab.telemetry.http_server.ThreadingHTTPServer.process_request",
                side_effect=RuntimeError("simulated thread failure"),
            ):
                with self.assertRaises(RuntimeError):
                    self.server.process_request(left, ("127.0.0.1", 0))
            self.assertEqual(self.server.connection_state()["active_connections"], 0)
            right.settimeout(2)
            self.assertEqual(right.recv(1), b"")
        finally:
            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()
