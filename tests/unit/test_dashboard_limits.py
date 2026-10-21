from __future__ import annotations

import socket
import threading
import time
import unittest
import urllib.request

from test_live_dashboard import ACCESS, DemoSnapshotSource

from tradinglab.dashboard.service import LiveDashboardService
from tradinglab.dashboard.web import create_server


class DashboardLimitsTest(unittest.TestCase):
    def setUp(self) -> None:
        service = LiveDashboardService(DemoSnapshotSource(), interval_seconds=5)
        self.server = create_server(
            service,
            port=0,
            dashboard_token=ACCESS,
            max_connections=1,
            request_timeout=0.2,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
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

    def test_slow_client_releases_worker_excess_is_rejected_and_server_recovers(self) -> None:
        slow = self.connect()
        slow.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: ")
        self.wait_active(1)

        excess = self.connect()
        self.assertEqual(excess.recv(1), b"")
        self.assertEqual(self.server.connection_state()["rejected_connections"], 1)

        try:
            while slow.recv(4096):
                pass
        except ConnectionError:
            pass
        self.wait_active(0)

        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/health", timeout=2
        ) as response:
            self.assertEqual(response.status, 200)

    def test_server_close_interrupts_active_client_and_releases_worker(self) -> None:
        client = self.connect()
        client.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: ")
        self.wait_active(1)

        self.server.shutdown()
        self.server.server_close()

        try:
            self.assertEqual(client.recv(1), b"")
        except ConnectionError:
            pass
        self.wait_active(0)

    def test_invalid_limits_fail_before_binding(self) -> None:
        service = LiveDashboardService(DemoSnapshotSource(), interval_seconds=5)
        for value in (0, -1, True, 33):
            with self.subTest(connections=value), self.assertRaises(ValueError):
                create_server(
                    service,
                    port=0,
                    dashboard_token=ACCESS,
                    max_connections=value,
                )
        for value in (0, float("inf"), float("nan"), "5", True):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                create_server(
                    service,
                    port=0,
                    dashboard_token=ACCESS,
                    request_timeout=value,
                )


if __name__ == "__main__":
    unittest.main()
