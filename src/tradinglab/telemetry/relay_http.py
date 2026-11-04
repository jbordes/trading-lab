"""Opt-in loopback ingress. A local ACK means only that the outbox committed."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler

from tradinglab.telemetry.admission_v2 import (
    V2AuthenticationError,
    V2AuthorizationError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.contract import MAX_BODY_BYTES, TelemetryValidationError
from tradinglab.telemetry.http_server import BoundedTelemetryServer
from tradinglab.telemetry.relay import RelayIngress
from tradinglab.telemetry.relay_queue import RelayConflict, RelayStorageError


@contextmanager
def relay_listeners(
    ingress: RelayIngress, ports: Sequence[int]
) -> Iterator[tuple[BoundedTelemetryServer, ...]]:
    """Bind every socket before accepting; close all owned listeners on exit.

    Zero requests an ephemeral port for isolated tests. Nonzero ports must be
    unique; the CLI only accepts explicit ports in 1..65535.
    """
    if not 1 <= len(ports) <= 8 or any(
        type(port) is not int or not 0 <= port <= 65535 for port in ports
    ):
        raise ValueError("Configure entre uno y ocho puertos válidos")
    explicit = [port for port in ports if port != 0]
    if len(set(explicit)) != len(explicit):
        raise ValueError("Los puertos del relay no pueden repetirse")
    with ExitStack() as stack:
        servers = []
        for port in ports:
            server = create_relay_server(ingress, port=port)
            stack.callback(server.server_close)
            servers.append(server)
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            stack.callback(thread.join, timeout=6)
            stack.callback(server.shutdown)
        yield tuple(servers)


def create_relay_server(ingress: RelayIngress, *, port: int) -> BoundedTelemetryServer:
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Puerto del relay inválido")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            try:
                super().handle()
            except TimeoutError, OSError:
                self.close_connection = True

        def _allowed_host(self) -> bool:
            hosts = self.headers.get_all("Host", [])
            return (
                len(hosts) == 1
                and hosts[0]
                in {
                    f"127.0.0.1:{self.server.server_port}",
                    f"localhost:{self.server.server_port}",
                }
                and not self.headers.get_all("Origin")
            )

        def do_GET(self) -> None:  # noqa: N802
            if not self._allowed_host():
                self._json(403, {"error": "host_not_allowed"})
            elif self.path != "/health":
                self._json(404, {"error": "not_found"})
            else:
                try:
                    self._json(
                        200,
                        {
                            "storage": "relay-outbox",
                            "ack_scope": "local",
                            **ingress.queue.status(now=time.time()),
                        },
                    )
                except RelayStorageError, sqlite3.Error:
                    self._json(503, {"error": "storage_unavailable"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._allowed_host():
                self._json(403, {"error": "host_not_allowed"})
                return
            if self.path not in {"/v1/telemetry", "/v2/telemetry"}:
                self._json(404, {"error": "not_found"})
                return
            if (
                self.headers.get_all("Transfer-Encoding")
                or len(self.headers.get_all("Content-Length", [])) != 1
                or len(self.headers.get_all("Authorization", [])) != 1
            ):
                self._json(400, {"error": "ambiguous_framing"})
                return
            if self.headers.get_content_type() != "application/json":
                self._json(415, {"error": "content_type"})
                return
            try:
                size = int(self.headers["Content-Length"])
            except ValueError:
                size = 0
            if not 1 <= size <= MAX_BODY_BYTES:
                self._json(413, {"error": "body_size"})
                return
            body = self.rfile.read(size)
            if len(body) != size:
                self._json(400, {"error": "incomplete_body"})
                return
            version = self.path.split("/")[1]
            try:
                new, gap, out_of_order = ingress.accept(
                    version, body, self.headers["Authorization"], now=time.time()
                )
            except V2AuthenticationError:
                self._json(401, {"error": "unauthorized"})
                return
            except V2AuthorizationError:
                self._json(403, {"error": "source_not_allowed"})
                return
            except RelayConflict:
                self._json(409, {"error": "idempotency_conflict"})
                return
            except V2StaleSequenceError:
                self._json(409, {"error": "stale_sequence"})
                return
            except TelemetryValidationError:
                self._json(400, {"error": "invalid_message"})
                return
            except RelayStorageError, sqlite3.Error:
                self._json(503, {"error": "storage_unavailable"})
                return
            result = {"status": "accepted" if new else "duplicate", "sequence_gap": gap}
            if version == "v2":
                result["out_of_order"] = out_of_order
            self._json(202 if new else 200, result)

        def _json(self, status: int, payload: object) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.close_connection = True
            self.send_response(status)
            for name, value in {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(data)),
                "Connection": "close",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return BoundedTelemetryServer(
        ("127.0.0.1", port), Handler, max_connections=8, request_timeout=5
    )
