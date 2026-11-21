"""Resolve MT5 identities at capture and persist routing alongside the durable outbox."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from urllib.error import HTTPError, URLError

from pydantic import ValidationError

from tradinglab.multi_catalog import Observed, valid_credential
from tradinglab.multi_config import api_request
from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole, V2AuthenticationError
from tradinglab.telemetry.contract import TelemetryValidationError
from tradinglab.telemetry.relay import RelayForwarder, RelayIngress, RelayProducer
from tradinglab.telemetry.relay_queue import RelayQueue, RelayStorageError


class MultiRelay(RelayIngress):
    def __init__(self, queue: RelayQueue, api: str, keys: dict):
        self.queue = queue
        self.api = api
        self.keys = keys
        self.destination = hashlib.sha256(keys["account-state"].encode()).hexdigest()
        self.lock = threading.RLock()
        self.routes = {}
        for stream, encoded in queue.bindings():
            data = json.loads(encoded)
            if data["destination"] != self.destination:
                raise ValueError("El destino de los lotes guardados difiere de la API configurada")
            self.routes[stream] = self.producer(data["contract"], data["account"])

    def producer(self, contract: str, row: dict) -> RelayProducer:
        role = ProducerRole.SNAPSHOT if contract == "account-state" else ProducerRole.ACTIVITY
        account = row["account_id"]
        return RelayProducer(
            contract,
            f"{account}-{role.value}",
            account,
            role,
            ProducerIdentity(row["login_masked"], row["server"], row["currency"]),
            f"{self.api}/accounts/{account}/api/{contract}",
            self.keys["terminal_master"],
            self.keys[contract],
        )

    def terminal_token(self, authorization: str, contract: str) -> str:
        scheme, _, token = authorization.partition(" ")
        if (
            scheme != "Bearer"
            or not token.isascii()
            or not (
                valid_credential(token, self.keys["terminal_master"], contract)
                or valid_credential(token, self.keys[contract], "mt5/" + contract)
            )
        ):
            raise V2AuthenticationError("Terminal sin autorización")
        return token

    def resolve(
        self, contract: str, body: bytes, authorization: str, *, raw: bool = False
    ) -> tuple[int, object]:
        self.terminal_token(authorization, contract)
        try:
            identity = Observed.model_validate_json(body)
        except ValidationError:
            return 400, "invalid_identity"
        try:
            account = api_request(
                self.api + "/resolve/" + contract + ("-raw" if raw else ""),
                self.keys[contract],
                identity.model_dump(),
            )
        except HTTPError as exc:
            if exc.code == 404:
                try:
                    error = json.loads(exc.read(4096))
                except ValueError, OSError:
                    error = None
                if error == {"detail": "unknown_account"}:
                    reason = exc.headers.get("X-TradingLab-Reason")
                    if reason in {"identity_not_registered", "mode_mismatch", "empty_catalog"}:
                        return 404, reason
                    return 404, "unknown_account"
            return 503, "api_unavailable"
        except OSError, URLError, ValueError:
            return 503, "api_unavailable"
        producer = self.producer(contract, account)
        with self.lock:
            self.queue.bind(
                producer.stream,
                json.dumps(
                    {"destination": self.destination, "account": account, "contract": contract},
                    sort_keys=True,
                ),
            )
            self.routes[producer.stream] = producer
        return 200, producer.source_id + "|" + str(account["history_from"])

    def accept(
        self, contract: str, body: bytes, authorization: str, *, now: float
    ) -> tuple[bool, int, bool]:
        terminal_credential = self.terminal_token(authorization, contract)
        try:
            source = json.loads(body)["source_id"]
            if not isinstance(source, str):
                raise ValueError
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            raise TelemetryValidationError("Mensaje inválido") from exc
        with self.lock:
            producer = self.routes.get(contract + ":" + source)
        if producer is None:
            raise RelayStorageError("La fuente necesita resolución")
        return self.store(
            replace(producer, local_token=terminal_credential),
            contract,
            body,
            authorization,
            now=now,
        )

    def forward(self, stop: threading.Event) -> None:
        while not stop.is_set():
            with self.lock:
                producers = tuple(self.routes.values())
            RelayForwarder(self.queue, producers).run_once()
            stop.wait(0.25)
