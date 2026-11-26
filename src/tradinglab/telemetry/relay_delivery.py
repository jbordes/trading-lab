"""Replaceable HTTP transport and pure central-ACK contract."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from typing import Protocol
from urllib.parse import urlsplit


class DeliveryTarget(Protocol):
    @property
    def target(self) -> str: ...

    @property
    def central_token(self) -> str: ...


class RelayTransport(Protocol):
    def send(self, producer: DeliveryTarget, body: bytes) -> tuple[int, str, bytes]: ...


def unique_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Claves JSON duplicadas")
        result[key] = value
    return result


def validate_central_ack(status: int, content_type: str, body: bytes, *, contract: str) -> None:
    if contract not in {"account-state", "trading-events"}:
        raise ValueError("Contrato de ACK no admitido")
    if status not in {200, 202} or len(body) > 4096 or content_type != "application/json":
        raise ValueError("ACK inválido")
    result = json.loads(body, object_pairs_hook=unique_json_fields)
    keys = {"status", "sequence_gap"} | (
        {"out_of_order"} if contract == "trading-events" else set()
    )
    if (
        not isinstance(result, dict)
        or set(result) != keys
        or result["status"] != {200: "duplicate", 202: "accepted"}[status]
        or type(result["sequence_gap"]) is not int
        or result["sequence_gap"] < 0
        or (contract == "trading-events" and type(result["out_of_order"]) is not bool)
    ):
        raise ValueError("ACK inválido")


class HttpRelayTransport:
    def __init__(self, *, timeout: float = 3, keep_alive: bool = False):
        if isinstance(timeout, bool) or not 0.05 <= timeout <= 10:
            raise ValueError("Timeout del relay fuera de rango")
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._idle: http.client.HTTPConnection | None = None
        self._origin: tuple | None = None

    def close(self) -> None:
        if self._idle is not None:
            self._idle.close()
            self._idle = None

    def send(self, producer: DeliveryTarget, body: bytes) -> tuple[int, str, bytes]:
        target = urlsplit(producer.target)
        origin = (target.scheme, target.hostname, target.port)
        if self._origin != origin:
            self.close()
        connection = self._idle
        self._idle = None
        if connection is None:
            connection_type = (
                http.client.HTTPSConnection
                if target.scheme == "https"
                else http.client.HTTPConnection
            )
            connection = connection_type(target.hostname, target.port, timeout=self._timeout)
        timer = None
        reusable = False
        expires = time.monotonic() + self._timeout
        try:
            if connection.sock is None:
                connection.connect()
            sock = connection.sock
            remaining = expires - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Se agotó el plazo de entrega")

            def expire() -> None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()
            connection.request(
                "POST",
                target.path,
                body=body,
                headers={
                    "Authorization": f"Bearer {producer.central_token}",
                    "Content-Type": "application/json",
                    "Connection": "keep-alive" if self._keep_alive else "close",
                },
            )
            with connection.getresponse() as response:
                data = response.read(4097)
                if len(data) <= 4096 and response.length not in (None, 0):
                    raise http.client.IncompleteRead(data, response.length)
                if time.monotonic() >= expires:
                    raise TimeoutError("Se agotó el plazo de entrega")
                reusable = (
                    self._keep_alive
                    and not response.will_close
                    and response.isclosed()
                    and len(data) <= 4096
                    and response.length in (0, None)
                )
                return response.status, response.headers.get_content_type(), data
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            if reusable and time.monotonic() < expires:
                self._idle = connection
                self._origin = origin
            else:
                connection.close()
