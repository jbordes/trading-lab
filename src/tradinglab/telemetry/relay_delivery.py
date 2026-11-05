"""Replaceable HTTP transport and pure central-ACK contract."""

from __future__ import annotations

import http.client
import json
import socket
import threading
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
    def __init__(self, *, timeout: float = 3):
        if isinstance(timeout, bool) or not 0.05 <= timeout <= 10:
            raise ValueError("Timeout del relay fuera de rango")
        self._timeout = timeout

    def send(self, producer: DeliveryTarget, body: bytes) -> tuple[int, str, bytes]:
        target = urlsplit(producer.target)
        connection_type = (
            http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_type(target.hostname, target.port, timeout=self._timeout)
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

            deadline = threading.Timer(self._timeout, expire)
            deadline.daemon = True
            deadline.start()
            with connection.getresponse() as response:
                return response.status, response.headers.get_content_type(), response.read(4097)
        finally:
            if deadline is not None:
                deadline.cancel()
                deadline.join()
            connection.close()
