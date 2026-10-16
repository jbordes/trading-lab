"""Loopback-only HTTP ingestion boundary for the MT5 telemetry spike."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tradinglab.telemetry.contract import (
    MAX_BODY_BYTES,
    TelemetryEnvelope,
    TelemetryValidationError,
    parse_envelope,
)


class TelemetryConflictError(RuntimeError):
    """Raised when a sequence or event id is reused with different content."""


class TelemetryStaleError(RuntimeError):
    """Raised when an unseen message arrives behind the accepted sequence."""


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    status: str
    sequence_gap: int


class TelemetryBuffer:
    """Bounded, thread-safe and idempotent in-memory buffer for the spike."""

    def __init__(self, *, max_messages: int = 500) -> None:
        if not 1 <= max_messages <= 10_000:
            raise ValueError("max_messages debe estar entre 1 y 10000")
        self._messages: deque[TelemetryEnvelope] = deque(maxlen=max_messages)
        self._fingerprints: dict[tuple[str, str, int], str] = {}
        self._event_fingerprints: dict[tuple[str, str], str] = {}
        self._last_sequences: dict[tuple[str, str], int] = {}
        self._accepted = 0
        self._duplicates = 0
        self._gaps = 0
        self._lock = threading.Lock()

    def accept(self, envelope: TelemetryEnvelope) -> IngestOutcome:
        fingerprint = hashlib.sha256(envelope.canonical_bytes()).hexdigest()
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
            self._messages.append(envelope)
            self._fingerprints[sequence_key] = fingerprint
            self._event_fingerprints[event_key] = fingerprint
            self._last_sequences[session_key] = envelope.sequence
            self._accepted += 1
            self._gaps += gap
            self._prune_fingerprints()
            return IngestOutcome(status="accepted", sequence_gap=gap)

    def state(self) -> dict[str, Any]:
        with self._lock:
            latest = self._messages[-1].as_dict() if self._messages else None
            return {
                "status": "ready",
                "accepted": self._accepted,
                "duplicates": self._duplicates,
                "missing_sequences": self._gaps,
                "retained": len(self._messages),
                "latest": latest,
            }

    def _prune_fingerprints(self) -> None:
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
    buffer: TelemetryBuffer,
    *,
    token: str,
    port: int,
    max_body_bytes: int = MAX_BODY_BYTES,
) -> ThreadingHTTPServer:
    """Create a receiver bound exclusively to IPv4 loopback."""

    if not 0 <= port <= 65535:
        raise ValueError("Puerto fuera de rango")
    if len(token) < 24 or not token.isascii() or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError(
            "El token debe tener al menos 24 caracteres ASCII sin espacios ni controles"
        )
    if not 1 <= max_body_bytes <= MAX_BODY_BYTES:
        raise ValueError("Límite de cuerpo fuera de rango")

    expected_authorization = f"Bearer {token}"

    class TelemetryHandler(BaseHTTPRequestHandler):
        server_version = "TradingLabTelemetrySpike/0.1"

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                health = buffer.state()
                health.pop("latest")
                self._send_json(HTTPStatus.OK, health)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/v1/telemetry":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            authorization = self.headers.get("Authorization", "")
            if (
                len(self.headers.get_all("Authorization", [])) != 1
                or not authorization.isascii()
                or not hmac.compare_digest(authorization, expected_authorization)
            ):
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

        def _method_not_allowed(self) -> None:
            self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})

        def _send_json(self, status: HTTPStatus, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

    return ThreadingHTTPServer(("127.0.0.1", port), TelemetryHandler)
