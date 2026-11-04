"""Authenticated local ingestion and restart-safe forwarding to explicit targets."""

from __future__ import annotations

import hmac
import http.client
import json
import socket
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
from tradinglab.telemetry.relay_queue import RelayQueue


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Claves JSON duplicadas")
        result[key] = value
    return result


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

    def __init__(self, ingress: RelayIngress, *, timeout: float = 3):
        if not 0.05 <= timeout <= 10:
            raise ValueError("Timeout del relay fuera de rango")
        self.ingress = ingress
        self.timeout = timeout
        self._lock = threading.Lock()

    def _send(self, producer: RelayProducer, body: bytes) -> tuple[int, str, bytes]:
        target = urlsplit(producer.target)
        connection_type = (
            http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_type(target.hostname, target.port, timeout=self.timeout)
        deadline = None
        try:
            connection.request(
                "POST",
                target.path,
                body=body,
                headers={
                    "Authorization": f"Bearer {producer.central_token}",
                    "Content-Type": "application/json",
                    "Connection": "close",
                },
            )
            sock = connection.sock

            def expire() -> None:
                try:
                    if sock is not None:
                        sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            # Bound the whole response, including trickling headers/body. http.client
            # neither consults proxy environment variables nor follows redirects.
            deadline = threading.Timer(self.timeout, expire)
            deadline.daemon = True
            deadline.start()
            with connection.getresponse() as response:
                return response.status, response.headers.get_content_type(), response.read(4097)
        finally:
            if deadline is not None:
                deadline.cancel()
                deadline.join()
            connection.close()

    def run_once(self, *, now: float | None = None) -> None:
        with self._lock:
            for producer in self.ingress.producers:
                stamp = time.time() if now is None else now
                message = self.ingress.queue.next(producer.stream, now=stamp)
                if message is None:
                    continue
                self.ingress.queue.attempt(message, now=stamp)
                try:
                    status, content_type, body = self._send(producer, message.body)
                except TimeoutError, OSError, http.client.HTTPException:
                    self.ingress.queue.finish(message, acked=False, error="network_failure")
                    continue
                if status not in {200, 202}:
                    self.ingress.queue.finish(
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
                    if (
                        status not in {200, 202}
                        or len(body) > 4096
                        or content_type != "application/json"
                    ):
                        raise ValueError("ACK inválido")
                    result = json.loads(body, object_pairs_hook=_unique_fields)
                    keys = {"status", "sequence_gap"} | (
                        {"out_of_order"} if producer.version == "v2" else set()
                    )
                    if (
                        not isinstance(result, dict)
                        or set(result) != keys
                        or result["status"] != {200: "duplicate", 202: "accepted"}.get(status)
                        or type(result["sequence_gap"]) is not int
                        or result["sequence_gap"] < 0
                        or (producer.version == "v2" and type(result["out_of_order"]) is not bool)
                    ):
                        raise ValueError("ACK inválido")
                except ValueError, UnicodeDecodeError:
                    self.ingress.queue.finish(message, acked=False, error="invalid_ack")
                else:
                    self.ingress.queue.finish(message, acked=True, now=stamp)
