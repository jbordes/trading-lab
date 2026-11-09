"""Small cross-platform guards and status records for scheduled telemetry jobs."""

from __future__ import annotations

import errno
import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO


class JobAlreadyRunningError(RuntimeError):
    """The OS lock is held by another execution, not a failed job."""


@contextmanager
def exclusive_job_lock(path: Path) -> Iterator[None]:
    """Hold an OS-backed non-blocking lock; crashes release it automatically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        _lock(stream)
        try:
            # Windows byte locks also block reads: acquire before inspecting the byte.
            stream.seek(0)
            if stream.read(1) == b"":
                stream.write(b"0")
                stream.flush()
            yield
        finally:
            _unlock(stream)
    finally:
        stream.close()


def write_job_status(path: Path, *, job: str, state: str, detail: str) -> None:
    """Atomically replace a bounded, secret-free operational status record."""

    if state not in {"running", "succeeded", "failed", "partial", "deferred"}:
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
    """Rotate a closed log; callers must serialize writers and release handles first."""

    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (max_bytes, copies)
    ):
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


def run_logged(
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    max_bytes: int = 5 * 1024 * 1024,
    copies: int = 3,
) -> int:
    """Drain one child's merged output with bounded memory and live log rotation.

    The caller owns the job lock. Only this supervisor writes the log, and all
    file handles are closed before rotation (required by Windows).
    """
    rotate_log(log_path, max_bytes=max_bytes, copies=copies)
    # Check permissions before starting the child, even if it never emits output.
    with log_path.open("ab") as log:
        size = log.tell()
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False
    )
    try:
        assert process.stdout is not None
        while block := process.stdout.read1(65536):
            offset = 0
            while offset < len(block):
                if size >= max_bytes:
                    rotate_log(log_path, max_bytes=max_bytes, copies=copies)
                    size = 0
                end = min(len(block), offset + max_bytes - size)
                # Closing each bounded append flushes it and avoids renaming open files.
                with log_path.open("ab") as log:
                    log.write(block[offset:end])
                size += end - offset
                offset = end
        return process.wait()
    except BaseException:
        # A failed sink must not leave a child blocked forever on a full stdout pipe.
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()


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
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise JobAlreadyRunningError("Ya existe una ejecución activa de este job") from exc
        raise


def _unlock(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
