"""Thread-safe polling state for the local dashboard."""

from __future__ import annotations

import threading
import time
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
        timer: Callable[[], float] | None = None,
    ) -> None:
        if interval_seconds < 2.0:
            raise ValueError("El intervalo mínimo es de 2 segundos")
        if history_limit < 2:
            raise ValueError("El historial debe admitir al menos dos muestras")
        self._source = source
        self._interval_seconds = interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timer = timer or time.perf_counter
        self._history: deque[dict[str, object]] = deque(maxlen=history_limit)
        self._latest: LiveSnapshot | None = None
        self._status = "starting"
        self._error: str | None = None
        self._attempt_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._consecutive_failures = 0
        self._last_attempt_at: str | None = None
        self._last_success_at: str | None = None
        self._last_duration_ms: float | None = None
        self._max_duration_ms = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> None:
        """Perform one controlled read, preserving the last valid sample on failure."""

        attempted_at = self._clock()
        started = self._timer()
        try:
            snapshot = self._source.collect(attempted_at)
        except Exception as exc:  # the service boundary must survive source failures
            duration_ms = _milliseconds(self._timer() - started)
            with self._lock:
                self._status = "degraded"
                self._error = _safe_message(exc)
                self._record_attempt(attempted_at, duration_ms, succeeded=False)
            return
        duration_ms = _milliseconds(self._timer() - started)
        with self._lock:
            self._history.append(snapshot.as_history_dict())
            self._latest = snapshot
            self._status = "connected"
            self._error = None
            self._record_attempt(attempted_at, duration_ms, succeeded=True)

    def state(self) -> dict[str, object]:
        """Return an immutable JSON-ready copy of the current dashboard state."""

        with self._lock:
            history = [dict(sample) for sample in self._history]
            latest = self._latest.as_dict() if self._latest else None
            return {
                "schema_version": "live-dashboard-state-v3",
                "status": self._status,
                "error": self._error,
                "latest": latest,
                "history": history,
                "interval_seconds": self._interval_seconds,
                "capture": {
                    "attempt_count": self._attempt_count,
                    "success_count": self._success_count,
                    "failure_count": self._failure_count,
                    "consecutive_failures": self._consecutive_failures,
                    "last_attempt_at": self._last_attempt_at,
                    "last_success_at": self._last_success_at,
                    "last_duration_ms": self._last_duration_ms,
                    "max_duration_ms": self._max_duration_ms,
                },
            }

    def _record_attempt(
        self, attempted_at: datetime, duration_ms: float, *, succeeded: bool
    ) -> None:
        self._attempt_count += 1
        self._last_attempt_at = _utc_iso(attempted_at)
        self._last_duration_ms = duration_ms
        self._max_duration_ms = max(self._max_duration_ms, duration_ms)
        if succeeded:
            self._success_count += 1
            self._consecutive_failures = 0
            self._last_success_at = _utc_iso(attempted_at)
        else:
            self._failure_count += 1
            self._consecutive_failures += 1

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


def _milliseconds(seconds: float) -> float:
    return round(max(0.0, seconds) * 1000, 3)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("El reloj debe incluir zona horaria")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
