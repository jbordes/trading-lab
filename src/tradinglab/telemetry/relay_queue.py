"""Durable bounded outbox. No broker actions, credentials or implicit data deletion."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from tradinglab.telemetry.admission_v2 import V2StaleSequenceError
from tradinglab.telemetry.contract import MAX_BODY_BYTES, TelemetryEnvelope

SCHEMA = """
CREATE TABLE messages (
 id INTEGER PRIMARY KEY,
 stream TEXT NOT NULL,
 session TEXT NOT NULL,
 sequence TEXT NOT NULL,
 event_id TEXT NOT NULL,
 digest TEXT NOT NULL,
 body BLOB,
 state TEXT NOT NULL CHECK(state IN ('pending','acked','rejected')),
 attempts INTEGER NOT NULL DEFAULT 0,
 first_seen REAL NOT NULL,
 due REAL NOT NULL DEFAULT 0,
 last_sent REAL,
 confirmed_at REAL,
 error TEXT,
 UNIQUE(stream,session,sequence),
 UNIQUE(stream,event_id)
);
CREATE INDEX pending_stream ON messages(stream,id) WHERE state != 'acked';
CREATE TABLE bindings (stream TEXT PRIMARY KEY, identity TEXT NOT NULL);
CREATE TABLE usage (
 id INTEGER PRIMARY KEY CHECK(id=1),
 records INTEGER NOT NULL CHECK(records>=0),
 pending_bytes INTEGER NOT NULL CHECK(pending_bytes>=0)
);
INSERT INTO usage VALUES(1,0,0);
PRAGMA user_version = 1;
"""


class RelayStorageError(RuntimeError):
    """Outbox cannot accept or safely mutate data."""


class RelayConflict(ValueError):
    """A previously recorded identity was reused with another payload."""


@dataclass(frozen=True)
class PendingMessage:
    id: int
    stream: str
    body: bytes
    attempts: int


def create_relay_database(path: Path) -> None:
    """Create schema atomically at a new path; parent must already exist."""
    if path.suffix != ".sqlite3":
        raise ValueError("La cola debe usar extensión .sqlite3")
    with TemporaryDirectory(prefix=".relay-create-", dir=path.parent) as folder:
        staged = Path(folder) / "queue.sqlite3"
        with closing(sqlite3.connect(staged)) as connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(SCHEMA)
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RelayStorageError("No se pudo verificar la cola")
        os.link(staged, path)


class RelayQueue:
    """Serialize local commits; retain deduplication metadata after central ACK."""

    def __init__(self, path: Path, *, max_bytes: int = 64 * 1024**2, max_records: int = 100_000):
        if type(max_bytes) is not int or not MAX_BODY_BYTES <= max_bytes <= 1024**3:
            raise ValueError("max_bytes debe estar entre 256 KiB y 1 GiB")
        if type(max_records) is not int or not 1 <= max_records <= 1_000_000:
            raise ValueError("max_records fuera de rango")
        self._lock = threading.RLock()
        self._max_bytes = max_bytes
        self._max_records = max_records
        self._db = sqlite3.connect(
            path.resolve(strict=True).as_uri() + "?mode=rw",
            uri=True,
            check_same_thread=False,
            timeout=5,
        )
        try:
            self._db.execute("PRAGMA synchronous=FULL")
            if self._db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise RelayStorageError("Esquema de cola no admitido")
            if self._db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RelayStorageError("Cola inválida")
            with closing(sqlite3.connect(":memory:")) as reference:
                reference.executescript(SCHEMA)
                sql = "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
                if self._db.execute(sql).fetchall() != reference.execute(sql).fetchall():
                    raise RelayStorageError("El esquema de cola no coincide")
            actual = self._db.execute(
                "SELECT count(*),coalesce(sum(length(body)),0) FROM messages"
            ).fetchone()
            if (
                self._db.execute("SELECT records,pending_bytes FROM usage WHERE id=1").fetchone()
                != actual
            ):
                raise RelayStorageError("Los contadores de cola no coinciden")
        except BaseException:
            self._db.close()
            raise

    def bind(self, stream: str, identity: str) -> None:
        """Prevent reassigning old pending data to a different account or endpoint."""
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            previous = self._db.execute(
                "SELECT identity FROM bindings WHERE stream=?", (stream,)
            ).fetchone()
            if previous is not None and previous[0] != identity:
                raise RelayStorageError("La configuración no coincide con la fuente de la cola")
            self._db.execute("INSERT OR IGNORE INTO bindings VALUES (?,?)", (stream, identity))

    def enqueue(
        self, stream: str, envelope: TelemetryEnvelope, *, now: float
    ) -> tuple[bool, int, bool]:
        body = envelope.canonical_bytes()
        digest = hashlib.sha256(body).hexdigest()
        with self._lock, self._db:
            # Explicit write transaction also serializes independent processes.
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(
                "SELECT digest FROM messages WHERE stream=? AND "
                "((session=? AND sequence=?) OR event_id=?)",
                (stream, envelope.session_id, str(envelope.sequence), envelope.event_id),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise RelayConflict("Identidad del mensaje reutilizada con otro contenido")
                return False, 0, False
            previous = self._db.execute(
                "SELECT sequence FROM messages WHERE stream=? AND session=? "
                "ORDER BY length(sequence) DESC,sequence DESC LIMIT 1",
                (stream, envelope.session_id),
            ).fetchone()
            high = int(previous[0]) if previous else 0
            out_of_order = envelope.sequence <= high
            if out_of_order and envelope.kind != "activity_batch":
                raise V2StaleSequenceError("Secuencia antigua desconocida en flujo estricto")
            gap = max(0, envelope.sequence - high - 1)
            count, size = self._db.execute(
                "SELECT records,pending_bytes FROM usage WHERE id=1"
            ).fetchone()
            if count >= self._max_records or size + len(body) > self._max_bytes:
                raise RelayStorageError("Cola llena; el mensaje no fue confirmado")
            self._db.execute(
                "INSERT INTO messages(stream,session,sequence,event_id,digest,body,state,first_seen) "
                "VALUES (?,?,?,?,?,?,'pending',?)",
                (
                    stream,
                    envelope.session_id,
                    str(envelope.sequence),
                    envelope.event_id,
                    digest,
                    body,
                    now,
                ),
            )
            self._db.execute(
                "UPDATE usage SET records=records+1,pending_bytes=pending_bytes+? WHERE id=1",
                (len(body),),
            )
        return True, gap, out_of_order

    def next(self, stream: str, *, now: float) -> PendingMessage | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id,body,attempts,state,due FROM messages "
                "WHERE stream=? AND state!='acked' ORDER BY id LIMIT 1",
                (stream,),
            ).fetchone()
            if not row or row[3] != "pending" or row[4] > now:
                return None
            if (
                hashlib.sha256(row[1]).hexdigest()
                != self._db.execute("SELECT digest FROM messages WHERE id=?", (row[0],)).fetchone()[
                    0
                ]
            ):
                raise RelayStorageError("El mensaje pendiente no coincide con su hash")
            return PendingMessage(row[0], stream, row[1], row[2])

    def attempt(self, message: PendingMessage, *, now: float) -> None:
        # Commit the retry deadline before network I/O, including crash recovery.
        with self._lock, self._db:
            self._db.execute(
                "UPDATE messages SET attempts=attempts+1,last_sent=?,due=? "
                "WHERE id=? AND state='pending'",
                (now, now + min(300, 2 ** min(message.attempts, 8)), message.id),
            )

    def finish(
        self,
        message: PendingMessage,
        *,
        acked: bool,
        error: str | None = None,
        now: float | None = None,
    ) -> None:
        with self._lock, self._db:
            if acked:
                self._db.execute("BEGIN IMMEDIATE")
                size = self._db.execute(
                    "SELECT length(body) FROM messages WHERE id=? AND state='pending'",
                    (message.id,),
                ).fetchone()
                if size is None:
                    return
                self._db.execute(
                    "UPDATE messages SET state='acked',body=NULL,error=NULL,confirmed_at=? WHERE id=?",
                    (now, message.id),
                )
                self._db.execute(
                    "UPDATE usage SET pending_bytes=pending_bytes-? WHERE id=1", (size[0],)
                )
            else:
                self._db.execute(
                    "UPDATE messages SET state=?,error=? WHERE id=? AND state='pending'",
                    (
                        "rejected" if error and error.startswith("rejected:") else "pending",
                        error,
                        message.id,
                    ),
                )

    def retry_rejected(self, stream: str, *, apply: bool = False) -> int:
        """Explicit operator action after fixing a rejection; never change message identity."""
        with self._lock, self._db:
            count = self._db.execute(
                "SELECT count(*) FROM messages WHERE stream=? AND state='rejected'", (stream,)
            ).fetchone()[0]
            if apply:
                self._db.execute(
                    "UPDATE messages SET state='pending',due=0,error=NULL "
                    "WHERE stream=? AND state='rejected'",
                    (stream,),
                )
            return count

    def status(self, *, now: float) -> dict[str, object]:
        with self._lock:
            rows = self._db.execute(
                "SELECT state,count(*),coalesce(sum(length(body)),0),min(first_seen) "
                "FROM messages GROUP BY state"
            ).fetchall()
            oldest = [r[3] for r in rows if r[0] != "acked"]
            return {
                "states": {r[0]: r[1] for r in rows},
                "pending_bytes": sum(r[2] for r in rows),
                "oldest_pending_seconds": max(0, now - min(oldest)) if oldest else 0,
                "max_records": self._max_records,
                "max_bytes": self._max_bytes,
                "last_central_ack_at": self._db.execute(
                    "SELECT max(confirmed_at) FROM messages"
                ).fetchone()[0],
                "errors": dict(
                    self._db.execute(
                        "SELECT error,count(*) FROM messages WHERE error IS NOT NULL GROUP BY error"
                    ).fetchall()
                ),
            }

    def close(self) -> None:
        with self._lock:
            self._db.close()
