"""Small cross-platform guards and status records for scheduled telemetry jobs."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO


@contextmanager
def exclusive_job_lock(path: Path) -> Iterator[None]:
    """Hold an OS-backed non-blocking lock; crashes release it automatically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        try:
            stream.seek(0)
            if stream.read(1) == b"":
                stream.write(b"0")
                stream.flush()
            _lock(stream)
        except OSError as exc:
            raise RuntimeError("Ya existe una ejecución activa de este job") from exc
        try:
            yield
        finally:
            _unlock(stream)
    finally:
        stream.close()


def write_job_status(path: Path, *, job: str, state: str, detail: str) -> None:
    """Atomically replace a bounded, secret-free operational status record."""

    if state not in {"running", "succeeded", "failed"}:
        raise ValueError("Estado operativo inválido")
    document = {
        "format": "tradinglab-job-status-v1",
        "job": job,
        "state": state,
        "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "detail": detail[:500],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _lock(stream: BinaryIO) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise RuntimeError("Ya existe una ejecución activa de este job") from exc


def _unlock(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
