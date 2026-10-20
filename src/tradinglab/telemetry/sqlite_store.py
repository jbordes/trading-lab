"""Opt-in SQLite creation and registration, isolated from the live receiver."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.contract import IDENTIFIER, TelemetryEnvelope, parse_envelope

SCHEMA_VERSION = 1

_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY NOT NULL CHECK(length(account_id) BETWEEN 1 AND 128),
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 128),
    server TEXT NOT NULL CHECK(length(server) BETWEEN 1 AND 128),
    currency TEXT NOT NULL CHECK(length(currency) BETWEEN 1 AND 16),
    created_at_utc TEXT NOT NULL CHECK(length(created_at_utc) BETWEEN 20 AND 27)
) STRICT;
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY NOT NULL CHECK(length(source_id) BETWEEN 1 AND 128),
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    created_at_utc TEXT NOT NULL CHECK(length(created_at_utc) BETWEEN 20 AND 27)
) STRICT;
CREATE TRIGGER sources_no_reassignment
BEFORE UPDATE OF account_id ON sources
WHEN NEW.account_id != OLD.account_id
BEGIN
    SELECT RAISE(ABORT, 'source account is immutable');
END;
CREATE TABLE telemetry_messages (
    message_id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    session_id TEXT NOT NULL CHECK(length(session_id) BETWEEN 1 AND 128),
    sequence TEXT NOT NULL CHECK(
        length(sequence) BETWEEN 1 AND 19
        AND sequence NOT GLOB '*[^0-9]*'
        AND substr(sequence, 1, 1) BETWEEN '1' AND '9'
        AND (length(sequence) < 19 OR sequence <= '9223372036854775807')
    ),
    captured_at_utc TEXT NOT NULL CHECK(length(captured_at_utc) BETWEEN 20 AND 27),
    received_at_utc TEXT NOT NULL CHECK(length(received_at_utc) BETWEEN 20 AND 27),
    schema_version TEXT NOT NULL CHECK(length(schema_version) BETWEEN 1 AND 128),
    collector_version TEXT NOT NULL CHECK(length(collector_version) BETWEEN 1 AND 128),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    content_sha256 TEXT NOT NULL CHECK(
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    UNIQUE(source_id, session_id, sequence)
) STRICT;
CREATE INDEX telemetry_messages_source_capture
ON telemetry_messages(source_id, captured_at_utc, message_id);
PRAGMA user_version = 1;
COMMIT;
"""


class TelemetryStorageError(RuntimeError):
    """Storage setup failed; no success or automatic recovery is implied."""


class RegistrationConflictError(ValueError):
    """An existing identity cannot be silently edited or reassigned."""


class MessageConflictError(ValueError):
    """A stored message identity was reused with different content."""


class MessageAdmissionError(ValueError):
    """Unknown source, incompatible account, or unknown old sequence."""


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """Returned only after the transaction committed successfully."""

    message_id: int
    duplicate: bool
    sequence_gap: bool


@dataclass(frozen=True, slots=True)
class RestoredSnapshot:
    """A historical observation with its original capture and receipt times."""

    envelope: TelemetryEnvelope
    received_at: datetime
    message_id: int


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Identificador inválido")


def _text(value: str, limit: int) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(not character.isprintable() for character in value)
    ):
        raise ValueError("Metadato vacío, demasiado largo o con caracteres no admitidos")


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _schema_objects(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()


class TelemetryRegistry:
    """Local registration and durable messages; no authentication or MT5 access.

    Obtain instances through open_registry. Each instance belongs to its opening
    thread and must not escape that context. Registration returns True for a new
    row and False for an identical registration, without updating metadata.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def register_account(
        self, account_id: str, label: str, server: str, currency: str, *, created_at: datetime
    ) -> bool:
        """Register an operator-verified account; a repeat keeps its original time."""
        _identifier(account_id)
        for value, limit in ((label, 128), (server, 128), (currency, 16)):
            _text(value, limit)
        stamp = _timestamp(created_at)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT label, server, currency FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if row is not None:
                if row != (label, server, currency):
                    raise RegistrationConflictError("La cuenta ya tiene otros metadatos")
                return False
            connection.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
                (account_id, label, server, currency, stamp),
            )
            return True

    def register_source(self, source_id: str, account_id: str, *, created_at: datetime) -> bool:
        """Link one source to an existing account; never reassign it."""
        _identifier(source_id)
        _identifier(account_id)
        stamp = _timestamp(created_at)
        with self._transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
                ).fetchone()
                is None
            ):
                raise ValueError("La cuenta debe registrarse antes que la fuente")
            row = connection.execute(
                "SELECT account_id FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            if row is not None:
                if row[0] != account_id:
                    raise RegistrationConflictError("No se puede reasignar una fuente")
                return False
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?)", (source_id, account_id, stamp)
            )
            return True

    def store_message(self, body: bytes, *, received_at: datetime) -> StoredMessage:
        """Validate and persist one envelope, preserving original duplicate reception.

        Unknown older sequences in an existing session are rejected; known retries
        are checked first. A gap is diagnostic, never proof of history coverage.
        The caller must authorize the source before invoking this local API.
        """
        if not isinstance(body, bytes):
            raise ValueError("El mensaje debe ser bytes")
        envelope = parse_envelope(body)
        received = _timestamp(received_at)
        canonical = envelope.canonical_bytes().decode("utf-8")
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        captured = _timestamp(datetime.fromisoformat(envelope.captured_at))
        identity = (envelope.source_id, envelope.session_id, str(envelope.sequence))
        with self._transaction() as connection:
            account = connection.execute(
                """SELECT a.server, a.currency FROM sources s
                JOIN accounts a ON a.account_id = s.account_id WHERE s.source_id = ?""",
                (envelope.source_id,),
            ).fetchone()
            if account is None:
                raise MessageAdmissionError("Fuente no registrada")
            existing = connection.execute(
                """SELECT message_id, payload_json, content_sha256 FROM telemetry_messages
                WHERE source_id = ? AND session_id = ? AND sequence = ?""",
                identity,
            ).fetchone()
            if existing is not None:
                if existing[1:] != (canonical, digest):
                    raise MessageConflictError("Identidad de mensaje con contenido diferente")
                return StoredMessage(existing[0], duplicate=True, sequence_gap=False)
            if envelope.kind == "account_snapshot":
                observed = envelope.payload["account"]
                if (observed["server"], observed["currency"]) != account:
                    raise MessageAdmissionError("Metadatos incompatibles con la cuenta registrada")
            previous = connection.execute(
                """SELECT sequence FROM telemetry_messages
                WHERE source_id = ? AND session_id = ?
                ORDER BY length(sequence) DESC, sequence DESC LIMIT 1""",
                identity[:2],
            ).fetchone()
            last_sequence = int(previous[0]) if previous else 0
            if envelope.sequence <= last_sequence:
                raise MessageAdmissionError("Secuencia antigua desconocida")
            cursor = connection.execute(
                """INSERT INTO telemetry_messages
                (source_id, session_id, sequence, captured_at_utc, received_at_utc,
                 schema_version, collector_version, payload_json, content_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    *identity,
                    captured,
                    received,
                    envelope.schema_version,
                    envelope.collector_version,
                    canonical,
                    digest,
                ),
            )
            result = StoredMessage(
                int(cursor.lastrowid),
                duplicate=False,
                sequence_gap=envelope.sequence > last_sequence + 1,
            )
        return result

    def latest_account_snapshot(self, source_id: str) -> RestoredSnapshot | None:
        """Read one verified snapshot for a registered source.

        Capture time determines which observation is newest; insertion order only
        breaks ties. The returned timestamps are historical evidence, never an
        assertion that the collector is currently connected.
        """
        _identifier(source_id)
        try:
            if (
                self._connection.execute(
                    "SELECT 1 FROM sources WHERE source_id = ?", (source_id,)
                ).fetchone()
                is None
            ):
                raise MessageAdmissionError("Fuente no registrada")
            row = self._connection.execute(
                """SELECT message_id, session_id, sequence, captured_at_utc,
                          received_at_utc, schema_version, collector_version,
                          payload_json, content_sha256
                   FROM telemetry_messages
                   WHERE source_id = ?
                     AND json_extract(payload_json, '$.kind') = 'account_snapshot'
                   ORDER BY captured_at_utc DESC, message_id DESC LIMIT 1""",
                (source_id,),
            ).fetchone()
            if row is None:
                return None
            (
                message_id,
                session_id,
                sequence,
                captured,
                received,
                schema,
                collector,
                canonical,
                digest,
            ) = row
            payload = canonical.encode("utf-8")
            if hashlib.sha256(payload).hexdigest() != digest:
                raise TelemetryStorageError("El mensaje guardado no coincide con su hash")
            envelope = parse_envelope(payload)
            if (
                canonical != envelope.canonical_bytes().decode("utf-8")
                or (envelope.source_id, envelope.session_id, str(envelope.sequence))
                != (source_id, session_id, sequence)
                or _timestamp(datetime.fromisoformat(envelope.captured_at)) != captured
                or (envelope.schema_version, envelope.collector_version) != (schema, collector)
                or envelope.kind != "account_snapshot"
            ):
                raise TelemetryStorageError("Columnas y mensaje guardado no coinciden")
            received_at = datetime.fromisoformat(received)
            if received_at.tzinfo is None or _timestamp(received_at) != received:
                raise TelemetryStorageError("Hora de recepción guardada inválida")
            return RestoredSnapshot(envelope, received_at, message_id)
        except MessageAdmissionError:
            raise
        except (sqlite3.Error, UnicodeError, ValueError, TypeError) as exc:
            raise TelemetryStorageError("No se pudo recuperar el snapshot guardado") from exc

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
        except sqlite3.Error as exc:
            raise TelemetryStorageError("No se pudo completar la transacción local") from exc


@contextmanager
def open_registry(path: Path) -> Iterator[TelemetryRegistry]:
    """Open an existing exact v1 schema, without creating or migrating a database.

    The file and its parent must be under operator control. Authentication and
    source authorization are separate, future receiver responsibilities.
    """
    if path.suffix != ".sqlite3":
        raise ValueError("La base debe usar extensión .sqlite3")
    resolved = path.resolve(strict=True)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(resolved.as_uri() + "?mode=rw", uri=True, timeout=5.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise TelemetryStorageError("Versión de esquema no admitida; no se migró la base")
        reference = sqlite3.connect(":memory:")
        try:
            reference.executescript(_SCHEMA)
            if _schema_objects(connection) != _schema_objects(reference):
                raise TelemetryStorageError("El esquema no coincide con TradingLab v1")
        finally:
            reference.close()
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise TelemetryStorageError("Falló la comprobación de integridad SQLite")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise TelemetryStorageError("La base contiene relaciones inválidas")
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise TelemetryStorageError("No se pudo abrir el registro SQLite") from exc
    except Exception:
        if connection is not None:
            connection.close()
        raise
    try:
        yield TelemetryRegistry(connection)
    finally:
        connection.close()


def create_database(path: Path) -> None:
    """Create schema v1 at an explicit new .sqlite3 path without replacing files.

    The parent directory must already exist. Callers must choose a private local
    path under _storage for operations (tests use temporary directories). Failure
    can leave a reserved file; it is never deleted or overwritten automatically.
    This is a creation primitive, not an opener, migration or ingestion API.
    """
    if path.suffix != ".sqlite3":
        raise ValueError("La base debe usar extensión .sqlite3")
    # Exclusive creation rejects existing files, directories and symlinks.
    with path.open("xb"):
        pass
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(_SCHEMA)
    except sqlite3.Error as exc:
        raise TelemetryStorageError(
            "No se pudo crear el esquema; revisar el archivo reservado antes de reintentar"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
