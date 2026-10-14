"""Dependency-free localhost HTTP boundary for the live dashboard."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tradinglab.dashboard.service import LiveDashboardService

STATIC_ROOT = Path(__file__).with_name("static")
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def create_server(
    service: LiveDashboardService,
    *,
    port: int,
) -> ThreadingHTTPServer:
    """Create a server bound exclusively to the IPv4 loopback interface."""

    if not 0 <= port <= 65535:
        raise ValueError("Puerto fuera de rango")

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "TradingLabDashboard/0.1"

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                self._send_json(service.state())
                return
            if path == "/health":
                state = service.state()
                self._send_json({"status": state["status"]})
                return
            static = STATIC_ROUTES.get(path)
            if static:
                filename, content_type = static
                self._send_bytes((STATIC_ROOT / filename).read_bytes(), content_type)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Dashboard de solo lectura")

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _send_json(self, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self._send_bytes(data, "application/json; charset=utf-8")

        def _send_bytes(self, data: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; img-src 'self'; "
                "script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

    return ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
