"""Authenticated local ingestion and restart-safe forwarding to explicit targets."""

from __future__ import annotations

import hmac
import http.client
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

from tradinglab.telemetry.admission_v2 import (
    ProducerIdentity,
    ProducerRegistration,
    ProducerRole,
    V2AuthenticationError,
    V2AuthorizationError,
    V2ProducerDirectory,
)
from tradinglab.telemetry.contract import parse_envelope
from tradinglab.telemetry.relay_delivery import (
    HttpRelayTransport,
    RelayTransport,
    validate_central_ack,
)
from tradinglab.telemetry.relay_queue import RelayQueue


@dataclass(frozen=True)
class RelayProducer:
    version: str
    source_id: str
    account_id: str
    role: ProducerRole
    identity: ProducerIdentity
    target: str
    local_token: str = field(repr=False)
    central_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.version not in {"v1", "v2"}:
            raise ValueError("Versión de relay no admitida")
        # Reuse strict source/account/role and credential validation.
        ProducerRegistration(
            self.account_id, self.source_id, self.role, self.identity, self.local_token
        )
        ProducerRegistration(
            self.account_id, self.source_id, self.role, self.identity, self.central_token
        )
        if self.local_token == self.central_token:
            raise ValueError("El token central debe ser distinto del token local")
        if self.version == "v1" and self.role != ProducerRole.LIVE:
            raise ValueError("V1 requiere rol live")
        target = urlsplit(self.target)
        if (
            target.scheme not in {"http", "https"}
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target.query
            or target.fragment
            or target.path != f"/{self.version}/telemetry"
            or (target.scheme == "http" and target.hostname != "127.0.0.1")
        ):
            raise ValueError("Use HTTPS, o HTTP con 127.0.0.1 para pruebas")
        if target.port is not None and not 1 <= target.port <= 65535:
            raise ValueError("Puerto central inválido")

    @property
    def stream(self) -> str:
        return f"{self.version}:{self.source_id}"


class RelayIngress:
    def __init__(self, queue: RelayQueue, producers: tuple[RelayProducer, ...]):
        if not 1 <= len(producers) <= 16:
            raise ValueError("Configure entre 1 y 16 productores")
        if len({p.stream for p in producers}) != len(producers):
            raise ValueError("Fuente duplicada")
        tokens = [token for p in producers for token in (p.local_token, p.central_token)]
        if len(set(tokens)) != len(tokens):
            raise ValueError("Las credenciales deben ser distintas por productor y frontera")
        self.queue = queue
        self.producers = producers
        for producer in producers:
            queue.bind(
                producer.stream,
                json.dumps(
                    {
                        "account": producer.account_id,
                        "role": producer.role.value,
                        "identity": asdict(producer.identity),
                        "target": producer.target,
                    },
                    sort_keys=True,
                ),
            )

    def accept(
        self, version: str, body: bytes, authorization: str, *, now: float
    ) -> tuple[bool, int, bool]:
        if not authorization.isascii():
            raise V2AuthenticationError("Credencial inválida")
        producer = None
        for candidate in self.producers:
            if hmac.compare_digest(authorization, f"Bearer {candidate.local_token}"):
                producer = candidate
        if producer is None:
            raise V2AuthenticationError("Credencial inválida")
        if producer.version != version:
            raise V2AuthorizationError("Versión no autorizada")
        if version == "v2":
            directory = V2ProducerDirectory(
                (
                    ProducerRegistration(
                        producer.account_id,
                        producer.source_id,
                        producer.role,
                        producer.identity,
                        producer.local_token,
                    ),
                )
            )
            envelope = directory.authorize(body, authorization).envelope
        else:
            envelope = parse_envelope(body)
            if envelope.source_id != producer.source_id:
                raise V2AuthorizationError("Fuente no autorizada")
            if envelope.kind == "account_snapshot":
                account = envelope.payload["account"]
                identity = {key: account[key] for key in ("login_masked", "server", "currency")}
                if not producer.identity.matches(identity):
                    raise V2AuthorizationError("Cuenta no autorizada")
        return self.queue.enqueue(producer.stream, envelope, now=now)


class RelayForwarder:
    """One synchronous worker; other sources proceed if a source is rejected/backing off."""

    def __init__(
        self,
        queue: RelayQueue,
        producers: tuple[RelayProducer, ...],
        *,
        transport: RelayTransport | None = None,
    ):
        self._queue = queue
        self._producers = producers
        self._transport = transport if transport is not None else HttpRelayTransport()
        self._lock = threading.Lock()

    def run_once(self, *, now: float | None = None) -> None:
        with self._lock:
            for producer in self._producers:
                stamp = time.time() if now is None else now
                message = self._queue.next(producer.stream, now=stamp)
                if message is None:
                    continue
                self._queue.attempt(message, now=stamp)
                try:
                    status, content_type, body = self._transport.send(producer, message.body)
                except TimeoutError, OSError, http.client.HTTPException:
                    self._queue.finish(message, acked=False, error="network_failure")
                    continue
                if status not in {200, 202}:
                    self._queue.finish(
                        message,
                        acked=False,
                        error=(
                            f"rejected:{status}"
                            if 300 <= status < 500 and status not in {408, 429}
                            else "http_failure"
                        ),
                    )
                    continue
                try:
                    validate_central_ack(status, content_type, body, version=producer.version)
                except ValueError, UnicodeDecodeError, RecursionError:
                    self._queue.finish(message, acked=False, error="invalid_ack")
                else:
                    self._queue.finish(message, acked=True, now=stamp)
