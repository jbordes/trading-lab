"""Thread-safe polling state for the local dashboard."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from tradinglab.dashboard.snapshot import LiveSnapshot, SnapshotSource


class LiveDashboardService:
    """Poll a read-only source and retain only a bounded in-memory history."""

    def __init__(
        self,
        source: SnapshotSource,
        *,
        interval_seconds: float = 5.0,
        history_limit: int = 720,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds < 2.0:
            raise ValueError("El intervalo mínimo es de 2 segundos")
        if history_limit < 2:
            raise ValueError("El historial debe admitir al menos dos muestras")
        self._source = source
        self._interval_seconds = interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._history: deque[dict[str, object]] = deque(maxlen=history_limit)
        self._latest: LiveSnapshot | None = None
        self._status = "starting"
        self._error: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> None:
        """Perform one controlled read, preserving the last valid sample on failure."""

        try:
            snapshot = self._source.collect(self._clock())
        except Exception as exc:  # the service boundary must survive source failures
            with self._lock:
                self._status = "degraded"
                self._error = _safe_message(exc)
            return
        with self._lock:
            self._history.append(snapshot.as_history_dict())
            self._latest = snapshot
            self._status = "connected"
            self._error = None

    def state(self) -> dict[str, object]:
        """Return an immutable JSON-ready copy of the current dashboard state."""

        with self._lock:
            history = [dict(sample) for sample in self._history]
            latest = self._latest.as_dict() if self._latest else None
            return {
                "schema_version": "live-dashboard-state-v2",
                "status": self._status,
                "error": self._error,
                "latest": latest,
                "history": history,
                "interval_seconds": self._interval_seconds,
            }

    def start(self) -> None:
        """Start one background poller; repeated calls are harmless."""

        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.poll_once()
        self._thread = threading.Thread(
            target=self._run,
            name="tradinglab-dashboard-poller",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the owned poller."""

        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval_seconds + 1.0)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self.poll_once()


def _safe_message(exc: Exception) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    return (text or type(exc).__name__)[:240]
