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
    AuthorizationRejection,
    V2AuthenticationError,
    V2AuthorizationError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.contract import MAX_BODY_BYTES, TelemetryValidationError
from tradinglab.telemetry.http_server import BoundedTelemetryServer
from tradinglab.telemetry.relay import RelayIngress
from tradinglab.telemetry.relay_queue import RelayConflict, RelayStorageError

_VALIDATION_REJECTIONS = {
    "El cuerpo no es JSON UTF-8 válido": "invalid_json",
    "Ventana de actividad inválida": "invalid_activity_window",
    "Registro fuera de la ventana": "row_outside_window",
    "Estado y conteos inconsistentes": "invalid_collection_counts",
    "Volúmenes de orden inconsistentes": "invalid_order_volumes",
    "Orden completada antes de su creación": "invalid_order_times",
    "Colección limitada a 200 registros": "collection_limit",
    "Cursores de página inconsistentes": "invalid_page_cursors",
    "Página de actividad vacía o demasiado grande": "invalid_page_size",
    "Estado de página inconsistente": "invalid_page_status",
    "Schema v2 no admitido": "invalid_schema",
    "event_id no corresponde a sesión y secuencia": "invalid_event_id",
}


def _validation_rejection(error: TelemetryValidationError) -> str:
    """Return only fixed codes, never values or field names from untrusted input."""
    message = str(error)
    if message.startswith(("Faltan campos en ", "Campos no admitidos en ")):
        return "invalid_fields"
    return _VALIDATION_REJECTIONS.get(message, "invalid_message")


class RelayDiagnostics:
    """Fixed-cardinality process counters; never retain request data."""

    _REASONS = (
        frozenset(
            {
                "host_missing",
                "host_multiple",
                "host_not_allowed",
                "origin_not_allowed",
                "unauthorized",
                "invalid_message",
                "invalid_fields",
                "ambiguous_framing",
                "incomplete_body",
                "malformed_http",
            }
        )
        | frozenset(reason.value for reason in AuthorizationRejection)
        | frozenset(_VALIDATION_REJECTIONS.values())
    )

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def reject(self, reason: str) -> None:
        if reason not in self._REASONS:
            raise ValueError("Motivo de diagnóstico no admitido")
        with self._lock:
            self._counts[reason] = min(self._counts.get(reason, 0) + 1, 2**63 - 1)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


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
        diagnostics = RelayDiagnostics()
        servers = []
        for port in ports:
            server = create_relay_server(ingress, port=port, diagnostics=diagnostics)
            stack.callback(server.server_close)
            servers.append(server)
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            stack.callback(thread.join, timeout=6)
            stack.callback(server.shutdown)
        yield tuple(servers)


def create_relay_server(
    ingress: RelayIngress, *, port: int, diagnostics: RelayDiagnostics | None = None
) -> BoundedTelemetryServer:
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Puerto del relay inválido")
    counters = diagnostics if diagnostics is not None else RelayDiagnostics()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def send_error(
            self, code: int, message: str | None = None, explain: str | None = None
        ) -> None:
            if code == 400:
                counters.reject("malformed_http")
            super().send_error(code, message, explain)

        def handle(self) -> None:
            try:
                super().handle()
            except TimeoutError, OSError:
                self.close_connection = True

        def _allowed_host(self) -> bool:
            hosts = self.headers.get_all("Host", [])
            reason = None
            if not hosts:
                reason = "host_missing"
            elif len(hosts) != 1:
                reason = "host_multiple"
            elif hosts[0] not in {
                # MT5 WebRequest omits the port from Host on this pilot.
                # Only exact loopback literals are accepted; Origin is still denied.
                "127.0.0.1",
                "localhost",
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }:
                reason = "host_not_allowed"
            elif self.headers.get_all("Origin"):
                reason = "origin_not_allowed"
            if reason is not None:
                counters.reject(reason)
                return False
            return True

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
                            "diagnostics_version": 2,
                            "ingress_rejections": counters.snapshot(),
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
                counters.reject("ambiguous_framing")
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
                counters.reject("incomplete_body")
                self._json(400, {"error": "incomplete_body"})
                return
            version = self.path.split("/")[1]
            try:
                new, gap, out_of_order = ingress.accept(
                    version, body, self.headers["Authorization"], now=time.time()
                )
            except V2AuthenticationError:
                counters.reject("unauthorized")
                self._json(401, {"error": "unauthorized"})
                return
            except V2AuthorizationError as exc:
                counters.reject(exc.reason.value)
                self._json(403, {"error": "source_not_allowed"})
                return
            except RelayConflict:
                self._json(409, {"error": "idempotency_conflict"})
                return
            except V2StaleSequenceError:
                self._json(409, {"error": "stale_sequence"})
                return
            except TelemetryValidationError as exc:
                counters.reject(_validation_rejection(exc))
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
