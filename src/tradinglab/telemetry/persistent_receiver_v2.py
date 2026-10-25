"""Opt-in durable receiver backend for two explicitly provisioned v2 producers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.admission_v2 import (
    ProducerRegistration,
    ProducerRole,
    V2ProducerDirectory,
)
from tradinglab.telemetry.sqlite_store_v2 import (
    StoredV2Message,
    V2StorageError,
    open_v2_registry,
)


class PersistentV2TelemetryReceiver:
    """Authorize two role-specific credentials and commit before acknowledging."""

    def __init__(
        self,
        database: Path,
        *,
        account_id: str,
        live_token: str,
        activity_token: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._context = open_v2_registry(database, cross_thread=True)
        self._registry = self._context.__enter__()
        try:
            evidence = self._registry.account_evidence(account_id)
            sources = {source.role: source.source_id for source in evidence.sources}
            if set(sources) != {ProducerRole.LIVE, ProducerRole.ACTIVITY}:
                raise ValueError("La cuenta v2 requiere fuentes live y activity provisionadas")
            self._directory = V2ProducerDirectory(
                (
                    ProducerRegistration(
                        account_id,
                        sources[ProducerRole.LIVE],
                        ProducerRole.LIVE,
                        evidence.identity,
                        live_token,
                    ),
                    ProducerRegistration(
                        account_id,
                        sources[ProducerRole.ACTIVITY],
                        ProducerRole.ACTIVITY,
                        evidence.identity,
                        activity_token,
                    ),
                )
            )
        except BaseException:
            self._context.__exit__(None, None, None)
            raise
        self._accepted = 0
        self._duplicates = 0
        self._out_of_order = 0
        self._gaps = 0
        self._closed = False

    def accept(self, body: bytes, authorization: str) -> StoredV2Message:
        with self._lock:
            self._require_open()
            authorized = self._directory.authorize(body, authorization)
            stored = self._registry.store_authorized(authorized, received_at=self._clock())
            if stored.disposition.value == "duplicate":
                self._duplicates += 1
            else:
                self._accepted += 1
                self._out_of_order += int(stored.out_of_order)
                self._gaps += stored.sequence_gap
            return stored

    def state(self) -> dict[str, int | str]:
        with self._lock:
            self._require_open()
            return {
                "status": "ready",
                "storage": "sqlite-v2",
                "accepted": self._accepted,
                "duplicates": self._duplicates,
                "out_of_order": self._out_of_order,
                "missing_sequences": self._gaps,
            }

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._context.__exit__(None, None, None)

    def _require_open(self) -> None:
        if self._closed:
            raise V2StorageError("El receptor SQLite v2 está cerrado")
