"""Small cross-platform guards and status records for scheduled telemetry jobs."""

from __future__ import annotations

import json
import os
import subprocess
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


def rotate_log(path: Path, *, max_bytes: int = 5 * 1024 * 1024, copies: int = 3) -> None:
    """Rotate a bounded operational log before starting a new supervised process."""

    if max_bytes < 1 or copies < 1:
        raise ValueError("La rotación de logs requiere límites positivos")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size < max_bytes:
        return
    oldest = path.with_name(f"{path.name}.{copies}")
    oldest.unlink(missing_ok=True)
    for index in range(copies - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        if source.exists():
            source.replace(path.with_name(f"{path.name}.{index + 1}"))
    path.replace(path.with_name(f"{path.name}.1"))


def run_logged(command: list[str], *, cwd: Path, log_path: Path) -> int:
    """Run one fixed argv without a shell and append stdout/stderr to a local log."""

    rotate_log(log_path)
    with log_path.open("ab") as log:
        result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, shell=False)
    return result.returncode


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
