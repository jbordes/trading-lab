"""Dependency-free localhost HTTP boundary for the live dashboard."""

from __future__ import annotations

import gzip
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from tradinglab.dashboard.service import LiveDashboardService

STATIC_ROOT = Path(__file__).with_name("static")
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
}

_STATIC_CACHE: dict[str, tuple[int, int, bytes, str]] = {}


def _read_static(filename: str) -> tuple[bytes, str]:
    """Read a static file from disk, caching bytes and a size+mtime ETag."""
    path = STATIC_ROOT / filename
    stat = path.stat()
    cached = _STATIC_CACHE.get(filename)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2], cached[3]
    data = path.read_bytes()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    _STATIC_CACHE[filename] = (stat.st_mtime_ns, stat.st_size, data, etag)
    return data, etag


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
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            try:
                super().handle()
            except TimeoutError, ConnectionError, OSError:
                # Browser disconnects and controlled shutdowns are normal network events.
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            path, _, raw_query = self.path.partition("?")
            query = parse_qs(raw_query)
            if path == "/api/state":
                since = (query.get("since") or [None])[0]
                self._send_json(service.state(history_since=since))
                return
            if path == "/health":
                state = service.state()
                self._send_json({"status": state["status"]})
                return
            static = STATIC_ROUTES.get(path)
            if static:
                filename, content_type = static
                data, etag = _read_static(filename)
                if self.headers.get("If-None-Match") == etag:
                    self._send_not_modified(etag)
                    return
                self._send_bytes(data, content_type, etag=etag, cache_control="no-cache")
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_HEAD(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            static = STATIC_ROUTES.get(path)
            if not static:
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            filename, content_type = static
            data, etag = _read_static(filename)
            self._send_bytes(
                data, content_type, etag=etag, cache_control="no-cache", head_only=True
            )

        def do_POST(self) -> None:  # noqa: N802
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Dashboard de solo lectura")

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _send_json(self, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self._send_bytes(data, "application/json; charset=utf-8")

        def _send_not_modified(self, etag: str) -> None:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Vary", "Accept-Encoding")
            self.end_headers()

        def _send_bytes(
            self,
            data: bytes,
            content_type: str,
            *,
            etag: str | None = None,
            cache_control: str = "no-store",
            head_only: bool = False,
        ) -> None:
            self.send_response(HTTPStatus.OK)
            accept_encoding = self.headers.get("Accept-Encoding", "")
            if len(data) > 1024 and "gzip" in accept_encoding:
                compressed = gzip.compress(data)
                if len(compressed) < len(data):
                    data = compressed
                    self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Vary", "Accept-Encoding")
            if etag:
                self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                "script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            if not head_only:
                self.wfile.write(data)

    return ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
