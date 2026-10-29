"""Loopback-only HTTP boundary for opt-in telemetry v2 ingestion."""

from __future__ import annotations

import hmac
import json
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from tradinglab.telemetry.admission_v2 import (
    V2AuthenticationError,
    V2AuthorizationError,
    V2ConflictError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.contract import MAX_BODY_BYTES, TelemetryValidationError
from tradinglab.telemetry.http_server import BoundedTelemetryServer
from tradinglab.telemetry.sqlite_store_v2 import (
    StoredV2Message,
    V2ActivityPage,
    V2CoverageReport,
    V2PositionCycleItem,
    V2PositionCyclePage,
    V2StorageError,
)


class V2TelemetryBackend(Protocol):
    def accept(self, body: bytes, authorization: str) -> StoredV2Message: ...

    def state(self) -> dict[str, object]: ...

    def activity_history(
        self,
        entity_type: str,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[V2ActivityPage, V2CoverageReport]: ...

    def position_cycles(
        self,
        *,
        owner_magic: str | None = None,
        owner_magics: tuple[str, ...] = (),
        limit: int = 50,
        cursor: str | None = None,
    ) -> V2PositionCyclePage: ...

    def position_cycle_magics(self) -> tuple[str, ...]: ...


def create_v2_telemetry_server(
    backend: V2TelemetryBackend,
    *,
    port: int,
    max_body_bytes: int = MAX_BODY_BYTES,
    max_connections: int = 8,
    request_timeout: float = 5.0,
    read_authorization: str,
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
    if (
        not isinstance(read_authorization, str)
        or not 24 <= len(read_authorization) <= 256
        or not read_authorization.isascii()
        or any(not 33 <= ord(character) <= 126 for character in read_authorization)
    ):
        raise ValueError("La credencial de lectura v2 no cumple el formato requerido")
    expected_read_authorization = f"Bearer {read_authorization}"

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
            if target.path == "/health" and not target.query:
                try:
                    state = backend.state()
                except V2StorageError:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"}
                    )
                    return
                state.update(self.server.connection_state())
                self._send_json(HTTPStatus.OK, state)
                return
            if target.path not in {
                "/v2/activity",
                "/v2/position-cycles",
                "/v2/position-cycle-magics",
            }:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not self._is_read_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            if target.path == "/v2/position-cycle-magics":
                if target.query:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_query"})
                    return
                try:
                    magics = backend.position_cycle_magics()
                except V2StorageError:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": "storage_unavailable"},
                    )
                    return
                self._send_json(HTTPStatus.OK, {"magics": list(magics)})
                return
            if target.path == "/v2/position-cycles":
                try:
                    query = self._position_cycles_query(target.query)
                    page = backend.position_cycles(**query)
                except ValueError:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_position_cycles_query"},
                    )
                    return
                except V2StorageError:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": "storage_unavailable"},
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "account_id": page.account_id,
                        "owner_magic": page.owner_magic,
                        "items": [self._position_cycle_item(item) for item in page.items],
                        "next_cursor": page.next_cursor,
                    },
                )
                return
            try:
                query = self._activity_query(target.query)
                page, coverage = backend.activity_history(**query)
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_activity_query"})
                return
            except V2StorageError:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"})
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "account_id": page.account_id,
                    "entity_type": page.entity_type,
                    "from_msc": query["from_msc"],
                    "to_msc": query["to_msc"],
                    "magic_number": query["magic_number"],
                    "items": [asdict(item) for item in page.items],
                    "next_cursor": page.next_cursor,
                    "coverage": {
                        "complete_ranges": [
                            {"from_msc": start, "to_msc": end}
                            for start, end in coverage.complete_ranges
                        ],
                        "incomplete_batches": coverage.incomplete_batches,
                    },
                },
            )

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

        def _is_read_authorized(self) -> bool:
            values = self.headers.get_all("Authorization", [])
            return (
                len(values) == 1
                and values[0].isascii()
                and hmac.compare_digest(values[0], expected_read_authorization)
            )

        @staticmethod
        def _activity_query(query: str) -> dict[str, Any]:
            values = parse_qs(
                query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=6,
            )
            required = {"entity", "from_msc", "to_msc"}
            allowed = required | {"magic_number", "limit", "cursor"}
            if not required <= set(values) or not set(values) <= allowed:
                raise ValueError("Parámetros de actividad inválidos")
            if any(len(items) != 1 for items in values.values()):
                raise ValueError("Parámetros de actividad repetidos")
            entity = values["entity"][0]
            if entity not in {"deal", "order"}:
                raise ValueError("Entidad de actividad inválida")

            def integer(name: str, default: str | None = None) -> int:
                value = values.get(name, [default])[0]
                if value is None or not value.isascii() or not value.isdecimal():
                    raise ValueError("Entero de actividad inválido")
                parsed = int(value)
                if str(parsed) != value:
                    raise ValueError("Entero de actividad inválido")
                return parsed

            return {
                "entity_type": entity,
                "from_msc": integer("from_msc"),
                "to_msc": integer("to_msc"),
                "magic_number": values.get("magic_number", [None])[0],
                "limit": integer("limit", "50"),
                "cursor": values.get("cursor", [None])[0],
            }

        @staticmethod
        def _position_cycles_query(query: str) -> dict[str, Any]:
            values = parse_qs(
                query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=4,
            )
            if not set(values) <= {"owner_magic", "owner_magics", "limit", "cursor"}:
                raise ValueError("Parámetros de ciclos inválidos")
            if any(len(items) != 1 for items in values.values()):
                raise ValueError("Parámetros de ciclos repetidos")
            limit = values.get("limit", ["50"])[0]
            if not limit.isascii() or not limit.isdecimal() or str(int(limit)) != limit:
                raise ValueError("Límite de ciclos inválido")
            owner_magic = values.get("owner_magic", [None])[0]
            owner_magics_text = values.get("owner_magics", [None])[0]
            if owner_magic is not None and owner_magics_text is not None:
                raise ValueError("Filtros Magic incompatibles")
            owner_magics = () if owner_magics_text is None else tuple(owner_magics_text.split(","))
            if (
                len(owner_magics) > 12
                or len(set(owner_magics)) != len(owner_magics)
                or any(not item for item in owner_magics)
            ):
                raise ValueError("Selección Magic inválida")
            return {
                "owner_magic": owner_magic,
                "owner_magics": owner_magics,
                "limit": int(limit),
                "cursor": values.get("cursor", [None])[0],
            }

        @staticmethod
        def _position_cycle_item(item: V2PositionCycleItem) -> dict[str, object]:
            cycle = item.cycle
            return {
                "message_id": item.message_id,
                "source_id": item.source_id,
                "captured_at": item.captured_at,
                "details": item.details,
                "cycle": {
                    "account_id": cycle.account_id,
                    "position_id": cycle.position_id,
                    "owner_magic": cycle.owner_magic,
                    "observed_magics": cycle.observed_magics,
                    "started_at_msc": cycle.started_at_msc,
                    "last_event_at_msc": cycle.last_event_at_msc,
                    "lifecycle": cycle.lifecycle.value,
                    "remaining_signed_volume": str(cycle.remaining_signed_volume),
                    "observed_net_result": str(cycle.observed_net_result),
                    "deal_tickets": cycle.deal_tickets,
                    "exclusions": tuple(reason.value for reason in cycle.exclusions),
                    "eligible_for_autonomous_metrics": (cycle.eligible_for_autonomous_metrics),
                },
            }

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
