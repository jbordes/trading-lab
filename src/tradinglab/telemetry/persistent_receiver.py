"""Single-source SQLite receiver backend for the supervised local pilot."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradinglab.telemetry.contract import IDENTIFIER, TelemetryEnvelope
from tradinglab.telemetry.ingest import IngestOutcome
from tradinglab.telemetry.persisted_view import PersistedSnapshotView
from tradinglab.telemetry.sqlite_store import (
    DealHistoryCursor,
    DealHistoryPage,
    MessageAdmissionError,
    TelemetryStorageError,
    open_registry,
    read_account_history,
)


class PersistentTelemetryReceiver:
    """Serialize SQLite access from bounded HTTP workers; one token, one source.

    Construct only with a pre-existing, operator-provisioned database. Startup
    validates its schema and source before the HTTP listener can bind. A restored
    snapshot retains its original capture time and never increments live counters.
    """

    def __init__(
        self,
        database: Path,
        *,
        source_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(source_id, str) or not IDENTIFIER.fullmatch(source_id):
            raise ValueError("source_id inválido")
        self._source_id = source_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._database = database.resolve(strict=True)
        self._lock = threading.RLock()
        self._history_admission = threading.BoundedSemaphore(2)
        self._context = open_registry(database, cross_thread=True)
        self._registry = self._context.__enter__()
        try:
            self._account_id = self._registry.account_for_source(source_id)
            self._view = PersistedSnapshotView(self._registry, source_id=source_id)
        except BaseException:
            self._context.__exit__(None, None, None)
            raise
        self._accepted = 0
        self._duplicates = 0
        self._gaps = 0
        self._closed = False

    def accept(self, envelope: TelemetryEnvelope) -> IngestOutcome:
        if envelope.source_id != self._source_id:
            raise MessageAdmissionError("Fuente no autorizada por este receptor")
        with self._lock:
            self._require_open()
            result = self._view.store_message(envelope.canonical_bytes(), received_at=self._clock())
            if result.duplicate:
                self._duplicates += 1
            else:
                self._accepted += 1
                self._gaps += result.gap_count
            return IngestOutcome(
                status="duplicate" if result.duplicate else "accepted",
                sequence_gap=result.gap_count,
            )

    def latest_account_snapshot(self, source_id: str) -> dict[str, Any] | None:
        if source_id != self._source_id:
            raise MessageAdmissionError("Fuente no autorizada por este receptor")
        with self._lock:
            self._require_open()
            snapshot = self._view.snapshot()
            return snapshot.envelope.as_dict() if snapshot is not None else None

    def account_history(self, source_id: str, *, from_msc: int, to_msc: int) -> dict[str, Any]:
        if source_id != self._source_id:
            raise MessageAdmissionError("Fuente no autorizada por este receptor")
        with self._lock:
            self._require_open()
        if not self._history_admission.acquire(blocking=False):
            raise TelemetryStorageError("Hay demasiadas consultas históricas simultáneas")
        try:
            return read_account_history(
                self._database,
                source_id,
                from_msc=from_msc,
                to_msc=to_msc,
            )
        finally:
            self._history_admission.release()

    def deal_history(
        self,
        source_id: str,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: DealHistoryCursor | None = None,
    ) -> DealHistoryPage:
        """Read only the account authorized by this single-source receiver."""
        if source_id != self._source_id:
            raise MessageAdmissionError("Fuente no autorizada por este receptor")
        with self._lock:
            self._require_open()
            return self._registry.deal_history(
                self._account_id,
                from_msc=from_msc,
                to_msc=to_msc,
                magic_number=magic_number,
                limit=limit,
                cursor=cursor,
            )

    def state(self, *, include_latest: bool = True) -> dict[str, Any]:
        with self._lock:
            self._require_open()
            snapshot = self._view.snapshot()
            payload = snapshot.envelope.payload if snapshot is not None else {}
            history = payload.get("history")
            state: dict[str, Any] = {
                "status": "ready",
                "storage": "sqlite",
                "accepted": self._accepted,
                "duplicates": self._duplicates,
                "missing_sequences": self._gaps,
                "retained": int(snapshot is not None),
                "retained_sessions": int(snapshot is not None),
                "history_status": history["status"] if history else "unavailable",
                "history_retained": len(history["deals"]) if history else 0,
            }
            if include_latest:
                state["latest"] = snapshot.envelope.as_dict() if snapshot is not None else None
            return state

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._context.__exit__(None, None, None)

    def _require_open(self) -> None:
        if self._closed:
            raise TelemetryStorageError("El receptor SQLite está cerrado")
