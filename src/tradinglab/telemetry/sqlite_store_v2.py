"""Isolated durable admission for the proposed telemetry v2 contract."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.admission_v2 import (
    AdmissionDisposition,
    AuthorizedEnvelope,
    ProducerIdentity,
    ProducerRole,
    V2AuthorizationError,
    V2ConflictError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.contract_v2 import SCHEMA_VERSION as WIRE_SCHEMA_VERSION
from tradinglab.telemetry.contract_v2 import parse_envelope_v2

DATABASE_SCHEMA_VERSION = 2

_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY NOT NULL CHECK(length(account_id) BETWEEN 1 AND 128),
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 128),
    login_masked TEXT NOT NULL CHECK(
        length(login_masked) BETWEEN 5 AND 12
        AND login_masked GLOB '[*][*][*][*][0-9]*'
        AND substr(login_masked, 5) NOT GLOB '*[^0-9]*'
    ),
    server TEXT NOT NULL CHECK(length(server) BETWEEN 1 AND 128),
    currency TEXT NOT NULL CHECK(length(currency) BETWEEN 1 AND 16),
    created_at_utc TEXT NOT NULL CHECK(length(created_at_utc) BETWEEN 20 AND 27)
) STRICT;
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY NOT NULL CHECK(length(source_id) BETWEEN 1 AND 128),
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    role TEXT NOT NULL CHECK(role IN ('live', 'activity')),
    created_at_utc TEXT NOT NULL CHECK(length(created_at_utc) BETWEEN 20 AND 27),
    UNIQUE(account_id, role)
) STRICT;
CREATE TRIGGER sources_no_identity_change
BEFORE UPDATE OF account_id, role ON sources
WHEN NEW.account_id != OLD.account_id OR NEW.role != OLD.role
BEGIN
    SELECT RAISE(ABORT, 'source identity is immutable');
END;
CREATE TABLE telemetry_v2_messages (
    message_id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    session_id TEXT NOT NULL CHECK(length(session_id) BETWEEN 1 AND 128),
    sequence TEXT NOT NULL CHECK(
        length(sequence) BETWEEN 1 AND 19
        AND sequence NOT GLOB '*[^0-9]*'
        AND substr(sequence, 1, 1) BETWEEN '1' AND '9'
        AND (length(sequence) < 19 OR sequence <= '9223372036854775807')
    ),
    event_id TEXT NOT NULL CHECK(length(event_id) BETWEEN 1 AND 128),
    kind TEXT NOT NULL CHECK(kind IN ('live_snapshot', 'activity_batch', 'heartbeat')),
    captured_at_utc TEXT NOT NULL CHECK(length(captured_at_utc) BETWEEN 20 AND 27),
    received_at_utc TEXT NOT NULL CHECK(length(received_at_utc) BETWEEN 20 AND 27),
    schema_version TEXT NOT NULL CHECK(schema_version = 'mt5-telemetry-v2'),
    collector_version TEXT NOT NULL CHECK(length(collector_version) BETWEEN 1 AND 128),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    content_sha256 TEXT NOT NULL CHECK(
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    out_of_order INTEGER NOT NULL CHECK(out_of_order IN (0, 1)),
    gap_count INTEGER NOT NULL CHECK(gap_count >= 0),
    UNIQUE(source_id, session_id, sequence),
    UNIQUE(source_id, event_id)
) STRICT;
CREATE INDEX telemetry_v2_messages_source_capture
ON telemetry_v2_messages(source_id, captured_at_utc, message_id);
PRAGMA user_version = 2;
COMMIT;
"""


class V2StorageError(RuntimeError):
    """The v2 database could not complete or verify a local operation."""


class V2RegistrationConflictError(ValueError):
    """An existing v2 account or source cannot be silently changed."""


@dataclass(frozen=True, slots=True)
class StoredV2Message:
    message_id: int
    disposition: AdmissionDisposition
    sequence_gap: int
    out_of_order: bool


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} inválido")
    return value


def _text(value: object, limit: int, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(not character.isprintable() for character in value)
    ):
        raise ValueError(f"{label} inválido")
    return value


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _schema_objects(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()


class V2TelemetryRegistry:
    """Explicit identities and durable v2 messages on one SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def register_account(
        self,
        account_id: str,
        label: str,
        identity: ProducerIdentity,
        *,
        created_at: datetime,
    ) -> bool:
        account = _identifier(account_id, "account_id")
        account_label = _text(label, 128, "label")
        if not isinstance(identity, ProducerIdentity):
            raise ValueError("Identidad MT5 inválida")
        stamp = _timestamp(created_at)
        expected = (
            account_label,
            identity.login_masked,
            identity.server,
            identity.currency,
        )
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT label, login_masked, server, currency FROM accounts
                WHERE account_id = ?""",
                (account,),
            ).fetchone()
            if row is not None:
                if row != expected:
                    raise V2RegistrationConflictError("La cuenta v2 ya tiene otra identidad")
                return False
            connection.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?)",
                (account, *expected, stamp),
            )
            return True

    def register_source(
        self,
        source_id: str,
        account_id: str,
        role: ProducerRole,
        *,
        created_at: datetime,
    ) -> bool:
        source = _identifier(source_id, "source_id")
        account = _identifier(account_id, "account_id")
        if not isinstance(role, ProducerRole):
            raise ValueError("Rol de productor inválido")
        stamp = _timestamp(created_at)
        with self._transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM accounts WHERE account_id = ?", (account,)
                ).fetchone()
                is None
            ):
                raise ValueError("La cuenta debe registrarse antes que la fuente")
            row = connection.execute(
                "SELECT account_id, role FROM sources WHERE source_id = ?", (source,)
            ).fetchone()
            if row is not None:
                if row != (account, role.value):
                    raise V2RegistrationConflictError("No se puede reasignar una fuente v2")
                return False
            try:
                connection.execute(
                    "INSERT INTO sources VALUES (?, ?, ?, ?)",
                    (source, account, role.value, stamp),
                )
            except sqlite3.IntegrityError as exc:
                raise V2RegistrationConflictError(
                    "Ya existe un productor primario para la cuenta y el rol"
                ) from exc
            return True

    def store_authorized(
        self,
        authorized: AuthorizedEnvelope,
        *,
        received_at: datetime,
    ) -> StoredV2Message:
        """Revalidate and persist one authorized envelope in one transaction."""

        if not isinstance(authorized, AuthorizedEnvelope):
            raise ValueError("Mensaje autorizado inválido")
        received = _timestamp(received_at)
        canonical_bytes = authorized.envelope.canonical_bytes()
        envelope = parse_envelope_v2(canonical_bytes)
        canonical = canonical_bytes.decode("utf-8")
        digest = hashlib.sha256(canonical_bytes).hexdigest()
        captured = _timestamp(datetime.fromisoformat(envelope.captured_at))
        identity = (envelope.source_id, envelope.session_id, str(envelope.sequence))

        with self._transaction() as connection:
            registered = connection.execute(
                """SELECT s.account_id, s.role, a.login_masked, a.server, a.currency
                FROM sources s JOIN accounts a ON a.account_id = s.account_id
                WHERE s.source_id = ?""",
                (envelope.source_id,),
            ).fetchone()
            expected = (
                authorized.account_id,
                authorized.role.value,
                envelope.payload["identity"]["login_masked"],
                envelope.payload["identity"]["server"],
                envelope.payload["identity"]["currency"],
            )
            if registered is None or registered != expected:
                raise V2AuthorizationError(
                    "La cuenta, fuente, identidad o rol no coinciden con el registro v2"
                )

            existing = connection.execute(
                """SELECT message_id, payload_json, content_sha256
                FROM telemetry_v2_messages
                WHERE source_id = ? AND session_id = ? AND sequence = ?""",
                identity,
            ).fetchone()
            if existing is not None:
                if existing[1:] != (canonical, digest):
                    raise V2ConflictError(
                        "La identidad del mensaje ya existe con contenido diferente"
                    )
                return StoredV2Message(int(existing[0]), AdmissionDisposition.DUPLICATE, 0, False)

            previous = connection.execute(
                """SELECT sequence FROM telemetry_v2_messages
                WHERE source_id = ? AND session_id = ?
                ORDER BY length(sequence) DESC, sequence DESC LIMIT 1""",
                identity[:2],
            ).fetchone()
            high_watermark = int(previous[0]) if previous else 0
            out_of_order = envelope.sequence <= high_watermark
            if out_of_order and envelope.kind != "activity_batch":
                raise V2StaleSequenceError(
                    "Secuencia desconocida anterior al máximo del flujo estricto"
                )
            sequence_gap = max(0, envelope.sequence - high_watermark - 1)
            cursor = connection.execute(
                """INSERT INTO telemetry_v2_messages
                (source_id, session_id, sequence, event_id, kind, captured_at_utc,
                 received_at_utc, schema_version, collector_version, payload_json,
                 content_sha256, out_of_order, gap_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    *identity,
                    envelope.event_id,
                    envelope.kind,
                    captured,
                    received,
                    WIRE_SCHEMA_VERSION,
                    envelope.collector_version,
                    canonical,
                    digest,
                    int(out_of_order),
                    sequence_gap,
                ),
            )
            result = StoredV2Message(
                int(cursor.lastrowid),
                AdmissionDisposition.ACCEPTED,
                sequence_gap,
                out_of_order,
            )
        return result

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
        except sqlite3.Error as exc:
            raise V2StorageError("No se pudo completar la transacción v2") from exc


@contextmanager
def open_v2_registry(path: Path, *, cross_thread: bool = False) -> Iterator[V2TelemetryRegistry]:
    """Open an existing exact v2 schema without creating or migrating it."""

    if path.suffix != ".sqlite3":
        raise ValueError("La base debe usar extensión .sqlite3")
    resolved = path.resolve(strict=True)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            resolved.as_uri() + "?mode=rw",
            uri=True,
            timeout=5.0,
            check_same_thread=not cross_thread,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        if connection.execute("PRAGMA user_version").fetchone()[0] != DATABASE_SCHEMA_VERSION:
            raise V2StorageError("Versión de esquema v2 no admitida")
        reference = sqlite3.connect(":memory:")
        try:
            reference.executescript(_SCHEMA)
            if _schema_objects(connection) != _schema_objects(reference):
                raise V2StorageError("El esquema no coincide con TradingLab v2")
        finally:
            reference.close()
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise V2StorageError("Falló la comprobación de integridad SQLite v2")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise V2StorageError("La base v2 contiene relaciones inválidas")
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise V2StorageError("No se pudo abrir el registro SQLite v2") from exc
    except Exception:
        if connection is not None:
            connection.close()
        raise
    try:
        yield V2TelemetryRegistry(connection)
    finally:
        connection.close()


def create_v2_database(path: Path) -> None:
    """Create an isolated v2 database at an explicit new path, never replacing."""

    if path.suffix != ".sqlite3":
        raise ValueError("La base debe usar extensión .sqlite3")
    with path.open("xb"):
        pass
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(_SCHEMA)
    except sqlite3.Error as exc:
        raise V2StorageError(
            "No se pudo crear el esquema v2; revisar el archivo reservado"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
