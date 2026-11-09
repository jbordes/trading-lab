"""Loopback-only fault injection for supervised collector access tests.

Never admits messages, authenticates credentials, forwards data or opens storage.
"""

from __future__ import annotations

from collections.abc import Callable
from http.server import BaseHTTPRequestHandler

from tradinglab.telemetry.http_server import BoundedTelemetryServer


def create_access_probe(
    port: int, status: int, *, report: Callable[[str, int], None] | None = None
) -> BoundedTelemetryServer:
    """Reject bounded POST bodies; port zero is reserved for isolated tests."""
    if status not in {401, 403} or not 0 <= port <= 65535:
        raise ValueError("Use HTTP 401/403 y un puerto válido")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/api/account-state", "/api/trading-events"}:
                self.send_error(404)
                return
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get_all("Transfer-Encoding"):
                self.send_error(400)
                return
            try:
                size = int(lengths[0])
            except ValueError:
                self.send_error(400)
                return
            if not 0 < size <= 1_048_576:
                self.send_error(413)
                return
            # Drain before replying so MT5 observes HTTP, not a reset socket.
            # No decoding, logging, persistence or inspection of Authorization.
            remaining = size
            while remaining:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    self.send_error(400)
                    return
                remaining -= len(chunk)
            body = b'{"error":"supervised_access_probe"}'
            if report is not None:
                report(self.path, status)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    return BoundedTelemetryServer(
        ("127.0.0.1", port), Handler, max_connections=4, request_timeout=2
    )
