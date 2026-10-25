"""Loopback-only HTTP boundary for opt-in telemetry v2 ingestion."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Protocol
from urllib.parse import urlsplit

from tradinglab.telemetry.admission_v2 import (
    V2AuthenticationError,
    V2AuthorizationError,
    V2ConflictError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.contract import MAX_BODY_BYTES, TelemetryValidationError
from tradinglab.telemetry.http_server import BoundedTelemetryServer
from tradinglab.telemetry.sqlite_store_v2 import StoredV2Message, V2StorageError


class V2TelemetryBackend(Protocol):
    def accept(self, body: bytes, authorization: str) -> StoredV2Message: ...

    def state(self) -> dict[str, object]: ...


def create_v2_telemetry_server(
    backend: V2TelemetryBackend,
    *,
    port: int,
    max_body_bytes: int = MAX_BODY_BYTES,
    max_connections: int = 8,
    request_timeout: float = 5.0,
) -> BoundedTelemetryServer:
    """Create a v2-only receiver bound exclusively to IPv4 loopback."""
    if not 0 <= port <= 65535:
        raise ValueError("Puerto fuera de rango")
    if not 1 <= max_body_bytes <= MAX_BODY_BYTES:
        raise ValueError("Límite de cuerpo fuera de rango")
    if (
        isinstance(max_connections, bool)
        or not isinstance(max_connections, int)
        or not 1 <= max_connections <= 32
    ):
        raise ValueError("max_connections debe ser 1..32")
    if (
        isinstance(request_timeout, bool)
        or not isinstance(request_timeout, (int, float))
        or not 0.05 <= request_timeout <= 30
    ):
        raise ValueError("request_timeout debe ser 0.05..30 segundos")

    class V2TelemetryHandler(BaseHTTPRequestHandler):
        server_version = "TradingLabTelemetryV2/0.1"
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            try:
                super().handle()
            except TimeoutError, ConnectionError, OSError:
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            try:
                target = urlsplit(self.path)
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_target"})
                return
            if target.path != "/health" or target.query:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                state = backend.state()
            except V2StorageError:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"})
                return
            state.update(self.server.connection_state())
            self._send_json(HTTPStatus.OK, state)

        def do_POST(self) -> None:  # noqa: N802
            try:
                target = urlsplit(self.path)
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_target"})
                return
            if target.path != "/v2/telemetry" or target.query:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if self.headers.get_content_type() != "application/json":
                self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "content_type"})
                return
            if (
                self.headers.get_all("Transfer-Encoding")
                or len(self.headers.get_all("Content-Length", [])) > 1
                or len(self.headers.get_all("Authorization", [])) > 1
            ):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "ambiguous_framing"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                content_length = -1
            if content_length < 1:
                self._send_json(HTTPStatus.LENGTH_REQUIRED, {"error": "content_length"})
                return
            if content_length > max_body_bytes:
                self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too_large"})
                return
            body = self.rfile.read(content_length)
            if len(body) != content_length:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "incomplete_body"})
                return
            try:
                result = backend.accept(body, self.headers.get("Authorization", ""))
            except V2AuthenticationError:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            except V2AuthorizationError:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "source_not_allowed"})
                return
            except TelemetryValidationError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_message"})
                return
            except V2ConflictError:
                self._send_json(HTTPStatus.CONFLICT, {"error": "idempotency_conflict"})
                return
            except V2StaleSequenceError:
                self._send_json(HTTPStatus.CONFLICT, {"error": "stale_sequence"})
                return
            except V2StorageError:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"})
                return
            status = (
                HTTPStatus.OK if result.disposition.value == "duplicate" else HTTPStatus.ACCEPTED
            )
            self._send_json(
                status,
                {
                    "status": result.disposition.value,
                    "sequence_gap": result.sequence_gap,
                    "out_of_order": result.out_of_order,
                },
            )

        def do_PUT(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_DELETE(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_PATCH(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _method_not_allowed(self) -> None:
            self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})

        def _send_json(self, status: HTTPStatus, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

    return BoundedTelemetryServer(
        ("127.0.0.1", port),
        V2TelemetryHandler,
        max_connections=max_connections,
        request_timeout=request_timeout,
    )
