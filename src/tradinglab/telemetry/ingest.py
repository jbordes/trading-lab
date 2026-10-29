"""Loopback-only HTTP ingestion boundary for the MT5 telemetry spike."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qs, urlsplit

from tradinglab.telemetry.contract import (
    IDENTIFIER,
    MAX_BODY_BYTES,
    TelemetryEnvelope,
    TelemetryValidationError,
    parse_envelope,
)
from tradinglab.telemetry.http_server import BoundedTelemetryServer
from tradinglab.telemetry.sqlite_store import (
    DealHistoryCursor,
    DealHistoryPage,
    MessageAdmissionError,
    MessageConflictError,
    MessageStaleError,
    TelemetryStorageError,
)


class TelemetryConflictError(RuntimeError):
    """Raised when a sequence or event id is reused with different content."""


class TelemetryStaleError(RuntimeError):
    """Raised when an unseen message arrives behind the accepted sequence."""


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    status: str
    sequence_gap: int


class TelemetryBackend(Protocol):
    def accept(self, envelope: TelemetryEnvelope) -> IngestOutcome: ...

    def state(self, *, include_latest: bool = True) -> dict[str, Any]: ...

    def latest_account_snapshot(self, source_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class AccountHistoryBackend(Protocol):
    def account_history(self, source_id: str, *, from_msc: int, to_msc: int) -> dict[str, Any]: ...


@runtime_checkable
class DealHistoryBackend(Protocol):
    def deal_history(
        self,
        source_id: str,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: DealHistoryCursor | None = None,
    ) -> DealHistoryPage: ...


class TelemetryBuffer:
    """Bounded, thread-safe and idempotent in-memory buffer for the spike."""

    def __init__(
        self, *, max_messages: int = 500, max_retained_bytes: int = 16 * 1024 * 1024
    ) -> None:
        if (
            isinstance(max_messages, bool)
            or not isinstance(max_messages, int)
            or not 1 <= max_messages <= 10_000
        ):
            raise ValueError("max_messages debe estar entre 1 y 10000")
        if (
            isinstance(max_retained_bytes, bool)
            or not isinstance(max_retained_bytes, int)
            or not 1 <= max_retained_bytes <= 64 * 1024 * 1024
        ):
            raise ValueError("max_retained_bytes debe ser 1..67108864 bytes")
        self._max_messages = max_messages
        self._max_retained_bytes = max_retained_bytes
        self._retained_bytes = 0
        self._message_sizes: deque[int] = deque()
        self._messages: deque[TelemetryEnvelope] = deque()
        self._fingerprints: dict[tuple[str, str, int], str] = {}
        self._event_fingerprints: dict[tuple[str, str], str] = {}
        self._last_sequences: dict[tuple[str, str], int] = {}
        self._accepted = 0
        self._duplicates = 0
        self._gaps = 0
        self._lock = threading.Lock()

    def accept(self, envelope: TelemetryEnvelope) -> IngestOutcome:
        canonical = envelope.canonical_bytes()
        size = len(canonical)
        if size > self._max_retained_bytes:
            raise TelemetryValidationError("El mensaje supera la capacidad del buffer")
        fingerprint = hashlib.sha256(canonical).hexdigest()
        session_key = (envelope.source_id, envelope.session_id)
        sequence_key = (*session_key, envelope.sequence)
        event_key = (envelope.source_id, envelope.event_id)
        with self._lock:
            known_sequence = self._fingerprints.get(sequence_key)
            known_event = self._event_fingerprints.get(event_key)
            if known_sequence is not None or known_event is not None:
                if known_sequence == fingerprint and known_event == fingerprint:
                    self._duplicates += 1
                    return IngestOutcome(status="duplicate", sequence_gap=0)
                raise TelemetryConflictError("Secuencia o event_id reutilizado con otro contenido")

            previous = self._last_sequences.get(session_key, 0)
            if envelope.sequence <= previous:
                raise TelemetryStaleError("Secuencia anterior no reconocida")
            gap = max(envelope.sequence - previous - 1, 0)
            while self._messages and (
                len(self._messages) >= self._max_messages
                or self._retained_bytes + size > self._max_retained_bytes
            ):
                self._messages.popleft()
                self._retained_bytes -= self._message_sizes.popleft()
            # Keep ownership: callers cannot enlarge/mutate a retained payload.
            self._messages.append(deepcopy(envelope))
            self._message_sizes.append(size)
            self._retained_bytes += size
            self._fingerprints[sequence_key] = fingerprint
            self._event_fingerprints[event_key] = fingerprint
            self._last_sequences[session_key] = envelope.sequence
            self._accepted += 1
            self._gaps += gap
            self._prune_fingerprints()
            return IngestOutcome(status="accepted", sequence_gap=gap)

    def state(self, *, include_latest: bool = True) -> dict[str, Any]:
        with self._lock:
            latest = self._messages[-1].as_dict() if self._messages else None
            history = latest["payload"].get("history") if latest else None
            return {
                "status": "ready",
                "accepted": self._accepted,
                "duplicates": self._duplicates,
                "missing_sequences": self._gaps,
                "retained": len(self._messages),
                "latest": deepcopy(latest) if include_latest else None,
                "retained_bytes": self._retained_bytes,
                "max_retained_bytes": self._max_retained_bytes,
                "retained_sessions": len(self._last_sequences),
                "history_status": history["status"] if history else "unavailable",
                "history_retained": len(history["deals"]) if history else 0,
            }

    def recent_deals(self, source_id: str, *, magic_number: str | None = None) -> dict[str, Any]:
        """Project the latest window, never append overlapping executions or sum P/L.

        Source IDs must identify one approved account. This is a bounded in-memory
        view, not an archive; error/truncated windows remain visibly incomplete.
        """
        with self._lock:
            for envelope in reversed(self._messages):
                if envelope.source_id != source_id or envelope.kind != "account_snapshot":
                    continue
                history = envelope.payload.get("history")
                if history is None:
                    return {"status": "unavailable", "deals": []}
                result = deepcopy(history)
                result["captured_at"] = envelope.captured_at
                result["deals"] = [
                    deal
                    for deal in result["deals"]
                    if magic_number is None or deal["magic_number"] == magic_number
                ]
                return result
        return {"status": "unavailable", "deals": []}

    def latest_account_snapshot(self, source_id: str) -> dict[str, Any] | None:
        """Return an owned copy of the newest snapshot for exactly one source."""

        with self._lock:
            for envelope in reversed(self._messages):
                if envelope.source_id == source_id and envelope.kind == "account_snapshot":
                    return deepcopy(envelope.as_dict())
        return None

    def _prune_fingerprints(self) -> None:
        retained_sessions = {(item.source_id, item.session_id) for item in self._messages}
        self._last_sequences = {
            key: value for key, value in self._last_sequences.items() if key in retained_sessions
        }
        retained_sequences = {
            (item.source_id, item.session_id, item.sequence) for item in self._messages
        }
        retained_events = {(item.source_id, item.event_id) for item in self._messages}
        self._fingerprints = {
            key: value for key, value in self._fingerprints.items() if key in retained_sequences
        }
        self._event_fingerprints = {
            key: value for key, value in self._event_fingerprints.items() if key in retained_events
        }


def create_telemetry_server(
    buffer: TelemetryBackend,
    *,
    token: str,
    port: int,
    max_body_bytes: int = MAX_BODY_BYTES,
    max_connections: int = 8,
    request_timeout: float = 5.0,
) -> BoundedTelemetryServer:
    """Create a receiver bound exclusively to IPv4 loopback."""

    if not 0 <= port <= 65535:
        raise ValueError("Puerto fuera de rango")
    if len(token) < 24 or not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError(
            "El token debe tener al menos 24 caracteres ASCII sin espacios ni controles"
        )
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

    expected_authorization = f"Bearer {token}"

    class TelemetryHandler(BaseHTTPRequestHandler):
        server_version = "TradingLabTelemetrySpike/0.1"
        # Current MT5 builds may accept an HTTP/1.0 response body but report an
        # internal 1001/1003 result instead of its status code.  The collector
        # then cannot acknowledge the sample.  Use an explicit, bounded HTTP/1.1
        # response and close it after every request; the collector never needs a
        # persistent connection.
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            try:
                super().handle()
            except TimeoutError, ConnectionError, OSError:
                # A deadline, shutdown or peer disconnect is a normal network failure.
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            try:
                request_target = urlsplit(self.path)
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_target"})
                return
            path = request_target.path
            if path == "/health":
                try:
                    health = buffer.state(include_latest=False)
                except TelemetryStorageError:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"}
                    )
                    return
                health.pop("latest", None)
                health.update(self.server.connection_state())
                self._send_json(HTTPStatus.OK, health)
                return
            if path == "/v1/snapshot":
                if not self._is_authorized():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                source_id = self._snapshot_source_id(request_target.query)
                if source_id is None:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_source"})
                    return
                try:
                    latest = buffer.latest_account_snapshot(source_id)
                except MessageAdmissionError:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "snapshot_unavailable"})
                    return
                except TelemetryStorageError:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"}
                    )
                    return
                if latest is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "snapshot_unavailable"})
                    return
                self._send_json(HTTPStatus.OK, latest)
                return
            if path == "/v1/account-history":
                if not self._is_authorized():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if not isinstance(buffer, AccountHistoryBackend):
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "history_unavailable"})
                    return
                try:
                    values = parse_qs(
                        request_target.query,
                        strict_parsing=True,
                        keep_blank_values=True,
                        max_num_fields=3,
                    )
                    if set(values) != {"source_id", "from_msc", "to_msc"} or any(
                        len(v) != 1 for v in values.values()
                    ):
                        raise ValueError("Consulta inválida")
                    result = buffer.account_history(
                        values["source_id"][0],
                        from_msc=self._query_integer(values["from_msc"][0]),
                        to_msc=self._query_integer(values["to_msc"][0]),
                    )
                except MessageAdmissionError:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "history_unavailable"})
                    return
                except ValueError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_history_query"})
                    return
                except TelemetryStorageError:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"}
                    )
                    return
                self._send_json(HTTPStatus.OK, result)
                return
            if path == "/v1/deals":
                if not self._is_authorized():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if not isinstance(buffer, DealHistoryBackend):
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "history_unavailable"})
                    return
                try:
                    query = self._deal_history_query(request_target.query)
                except ValueError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_history_query"})
                    return
                try:
                    page = buffer.deal_history(**query)
                except MessageAdmissionError:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "history_unavailable"})
                    return
                except ValueError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_history_query"})
                    return
                except TelemetryStorageError:
                    self._send_json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"}
                    )
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "account_id": page.account_id,
                        "source_id": query["source_id"],
                        "from_msc": query["from_msc"],
                        "to_msc": query["to_msc"],
                        "magic_number": query["magic_number"],
                        "deals": [deal.as_dict() for deal in page.deals],
                        "next_cursor": (
                            page.next_cursor.encode() if page.next_cursor is not None else None
                        ),
                    },
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/v1/telemetry":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            content_type = self.headers.get_content_type()
            if content_type != "application/json":
                self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "content_type"})
                return
            if (
                self.headers.get_all("Transfer-Encoding")
                or len(self.headers.get_all("Content-Length", [])) > 1
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
                envelope = parse_envelope(body)
                outcome = buffer.accept(envelope)
            except TelemetryValidationError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_message"})
                return
            except TelemetryConflictError:
                self._send_json(HTTPStatus.CONFLICT, {"error": "idempotency_conflict"})
                return
            except TelemetryStaleError:
                self._send_json(HTTPStatus.CONFLICT, {"error": "stale_sequence"})
                return
            except MessageConflictError:
                self._send_json(HTTPStatus.CONFLICT, {"error": "idempotency_conflict"})
                return
            except MessageStaleError:
                self._send_json(HTTPStatus.CONFLICT, {"error": "stale_sequence"})
                return
            except MessageAdmissionError:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "source_not_allowed"})
                return
            except TelemetryStorageError:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "storage_unavailable"})
                return
            status = HTTPStatus.OK if outcome.status == "duplicate" else HTTPStatus.ACCEPTED
            self._send_json(
                status,
                {"status": outcome.status, "sequence_gap": outcome.sequence_gap},
            )

        def do_PUT(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_DELETE(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def do_PATCH(self) -> None:  # noqa: N802
            self._method_not_allowed()

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _is_authorized(self) -> bool:
            authorization = self.headers.get("Authorization", "")
            return (
                len(self.headers.get_all("Authorization", [])) == 1
                and authorization.isascii()
                and hmac.compare_digest(authorization, expected_authorization)
            )

        def _snapshot_source_id(self, query: str) -> str | None:
            try:
                values = parse_qs(
                    query,
                    keep_blank_values=True,
                    strict_parsing=True,
                    max_num_fields=2,
                )
            except ValueError:
                return None
            if set(values) != {"source_id"} or len(values["source_id"]) != 1:
                return None
            source_id = values["source_id"][0]
            return source_id if IDENTIFIER.fullmatch(source_id) else None

        def _deal_history_query(self, query: str) -> dict[str, Any]:
            values = parse_qs(
                query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=6,
            )
            required = {"source_id", "from_msc", "to_msc"}
            allowed = required | {"magic_number", "limit", "cursor"}
            if not required <= set(values) or not set(values) <= allowed:
                raise ValueError("Parámetros de historial inválidos")
            if any(len(items) != 1 for items in values.values()):
                raise ValueError("Parámetros de historial repetidos")
            source_id = values["source_id"][0]
            if not IDENTIFIER.fullmatch(source_id):
                raise ValueError("Fuente inválida")
            from_msc = self._query_integer(values["from_msc"][0])
            to_msc = self._query_integer(values["to_msc"][0])
            limit = self._query_integer(values.get("limit", ["50"])[0])
            magic_number = values.get("magic_number", [None])[0]
            cursor_text = values.get("cursor", [None])[0]
            cursor = DealHistoryCursor.decode(cursor_text) if cursor_text is not None else None
            # The registry owns the complete boundary validation.
            return {
                "source_id": source_id,
                "from_msc": from_msc,
                "to_msc": to_msc,
                "magic_number": magic_number,
                "limit": limit,
                "cursor": cursor,
            }

        @staticmethod
        def _query_integer(value: str) -> int:
            if not value or not value.isascii() or not value.isdecimal():
                raise ValueError("Entero de consulta inválido")
            parsed = int(value)
            if str(parsed) != value:
                raise ValueError("Entero de consulta inválido")
            return parsed

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
        TelemetryHandler,
        max_connections=max_connections,
        request_timeout=request_timeout,
    )
