"""Per-source in-memory view backed by committed SQLite observations."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from tradinglab.telemetry.contract import IDENTIFIER, parse_envelope
from tradinglab.telemetry.sqlite_store import (
    MessageAdmissionError,
    RestoredSnapshot,
    StoredMessage,
    TelemetryRegistry,
    TelemetryStorageError,
)


class PersistedSnapshotView:
    """Cache one source's latest committed snapshot without claiming live capture.

    The caller owns the registry connection and must keep this view on the same
    thread. On startup the view restores its source. After every committed write,
    it reloads from SQLite. Reading never changes timestamps or capture counters.
    """

    def __init__(self, registry: TelemetryRegistry, *, source_id: str) -> None:
        if not isinstance(source_id, str) or not IDENTIFIER.fullmatch(source_id):
            raise ValueError("source_id inválido")
        self._registry = registry
        self._source_id = source_id
        self._snapshot: RestoredSnapshot | None = None
        self._synchronized = False
        self.refresh()

    def refresh(self) -> None:
        """Reconcile this view with the latest durable snapshot for its source."""
        self._synchronized = False
        snapshot = self._registry.latest_account_snapshot(self._source_id)
        self._snapshot = snapshot
        self._synchronized = True

    def store_message(self, body: bytes, *, received_at: datetime) -> StoredMessage:
        """Commit a message before publishing its source's refreshed view.

        A refresh failure after commit is reported as a failure. Retrying the same
        message then gets a durable duplicate and refreshes the view again.
        Authentication is still the responsibility of the future HTTP boundary.
        """
        envelope = parse_envelope(body)
        if envelope.source_id != self._source_id:
            raise MessageAdmissionError("El mensaje pertenece a otra fuente")
        result = self._registry.store_message(body, received_at=received_at)
        self.refresh()
        return result

    def snapshot(self) -> RestoredSnapshot | None:
        """Return a detached historical value, or None when no snapshot exists."""
        if not self._synchronized:
            raise TelemetryStorageError("La vista no está sincronizada con SQLite")
        return deepcopy(self._snapshot)
