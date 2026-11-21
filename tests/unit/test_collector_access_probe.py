from __future__ import annotations

import http.client
import runpy
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tradinglab.telemetry.access_probe import create_access_probe


class AccessProbeTests(unittest.TestCase):
    def test_cli_closes_servers_on_timeout_interrupt_and_partial_bind_failure(self) -> None:
        main = runpy.run_path(
            str(Path(__file__).resolve().parents[2] / "scripts/collector_access_probe.py")
        )["main"]
        for scenario in ("timeout", "interrupt", "bind_failure"):
            with self.subTest(scenario=scenario):
                servers = []

                def factory(
                    port: int,
                    status: int,
                    *,
                    scenario: str = scenario,
                    servers: list = servers,
                    **kwargs: object,
                ) -> object:
                    if scenario == "bind_failure" and servers:
                        raise OSError("synthetic occupied port")
                    server = create_access_probe(0, status)
                    servers.append(server)
                    return server

                wait = Mock(side_effect=KeyboardInterrupt if scenario == "interrupt" else None)
                controlled_threads = SimpleNamespace(
                    Thread=threading.Thread, Event=lambda wait=wait: SimpleNamespace(wait=wait)
                )
                with (
                    patch("tradinglab.telemetry.access_probe.create_access_probe", factory),
                    patch.dict(main.__globals__, threading=controlled_threads),
                    patch("builtins.print"),
                ):
                    self.assertEqual(
                        main(["--status", "401"]), 1 if scenario == "bind_failure" else 0
                    )
                self.assertTrue(servers)
                self.assertTrue(all(server.socket.fileno() == -1 for server in servers))

    def request(self, status: int, path: str, body: bytes) -> tuple[int, bytes]:
        reports = []
        server = create_access_probe(0, status, report=lambda *args: reports.append(args))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with closing(
                http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            ) as conn:
                conn.request("POST", path, body)
                response = conn.getresponse()
                result = response.status, response.read()
            if result[0] in {401, 403}:
                self.assertEqual(reports, [(path, status)])
            else:
                self.assertEqual(reports, [])
            return result
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_both_codes_and_paths_reject_without_ack(self) -> None:
        for status in (401, 403):
            for path in ("/api/account-state", "/api/trading-events"):
                with self.subTest(status=status, path=path):
                    code, body = self.request(status, path, b"synthetic-not-even-json")
                    self.assertEqual(code, status)
                    self.assertEqual(body, b'{"error":"supervised_access_probe"}')

    def test_unknown_path_is_not_reported_as_access_rejection(self) -> None:
        self.assertEqual(self.request(401, "/other", b"x")[0], 404)

    def test_empty_body_is_not_reported_as_access_rejection(self) -> None:
        self.assertEqual(self.request(401, "/api/account-state", b"")[0], 413)

    def test_invalid_configuration(self) -> None:
        for port, status in ((-1, 401), (65536, 403), (0, 200)):
            with self.subTest(port=port, status=status), self.assertRaises(ValueError):
                create_access_probe(port, status)
