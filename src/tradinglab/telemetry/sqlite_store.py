"""Opt-in SQLite creation and registration, isolated from the live receiver."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tradinglab.telemetry.contract import (
    DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS,
    IDENTIFIER,
    MAX_INT64,
    MAX_UINT64,
    TelemetryEnvelope,
    parse_envelope,
)

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


class MessageStaleError(MessageAdmissionError):
    """An unknown sequence arrived behind an already committed sequence."""


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """Returned only after the transaction committed successfully."""

    message_id: int
    duplicate: bool
    sequence_gap: bool
    gap_count: int = 0


@dataclass(frozen=True, slots=True)
class RestoredSnapshot:
    """A historical observation with its original capture and receipt times."""

    envelope: TelemetryEnvelope
    received_at: datetime
    message_id: int


@dataclass(frozen=True, slots=True)
class DealHistoryCursor:
    """Stable keyset cursor for a descending historical-deal page."""

    time_msc: int
    ticket: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.time_msc, bool)
            or not isinstance(self.time_msc, int)
            or not 0 <= self.time_msc <= MAX_INT64
        ):
            raise ValueError("Cursor de historial inválido")
        _unsigned_decimal(self.ticket, maximum=MAX_UINT64, label="cursor")
        if self.ticket == "0":
            raise ValueError("Cursor de historial inválido")

    def encode(self) -> str:
        return f"{self.time_msc}.{self.ticket}"

    @classmethod
    def decode(cls, value: str) -> DealHistoryCursor:
        if not isinstance(value, str) or value.count(".") != 1:
            raise ValueError("Cursor de historial inválido")
        time_text, ticket = value.split(".")
        _unsigned_decimal(time_text, maximum=MAX_INT64, label="cursor")
        return cls(int(time_text), ticket)


@dataclass(frozen=True, slots=True)
class HistoricalDeal:
    """One validated MT5 deal and the journal observation that supplied it."""

    account_id: str
    source_id: str
    message_id: int
    captured_at: str
    ticket: str
    order_id: str
    position_id: str
    magic_number: str
    time_msc: int
    deal_type: int
    entry: int
    symbol: str
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    fee: float

    def as_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class DealHistoryPage:
    """Bounded result; next_cursor is absent only on the final page."""

    account_id: str
    deals: tuple[HistoricalDeal, ...]
    next_cursor: DealHistoryCursor | None


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


def _unsigned_decimal(value: str, *, maximum: int, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or (len(value) > 1 and value.startswith("0"))
        or not value.isascii()
        or not value.isdecimal()
        or int(value) > maximum
    ):
        raise ValueError(f"{label} inválido")


def _magic_number(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("Magic Number inválido")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("Magic Number inválido") from exc
    if str(parsed) != value or not -(2**63) <= parsed <= MAX_INT64:
        raise ValueError("Magic Number inválido")


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _capture_is_plausible(snapshot: RestoredSnapshot) -> bool:
    captured_at = datetime.fromisoformat(snapshot.envelope.captured_at)
    tolerance = timedelta(seconds=DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS)
    return captured_at <= snapshot.received_at + tolerance


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
                raise MessageStaleError("Secuencia antigua desconocida")
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
                gap_count=envelope.sequence - last_sequence - 1,
            )
        return result

    def latest_account_snapshot(self, source_id: str) -> RestoredSnapshot | None:
        """Read one verified snapshot for a registered source.

        Capture time determines which observation is newest; insertion order only
        breaks ties. A capture too far ahead of its trusted reception time remains
        stored but cannot displace a plausible observation. The returned timestamps
        are historical evidence, never an assertion that the collector is connected.
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
            latest = self._restore_snapshot_row(row, source_id=source_id)
            if _capture_is_plausible(latest):
                return latest

            rows = self._connection.execute(
                """SELECT message_id, session_id, sequence, captured_at_utc,
                          received_at_utc, schema_version, collector_version,
                          payload_json, content_sha256
                   FROM telemetry_messages
                   WHERE source_id = ?
                     AND json_extract(payload_json, '$.kind') = 'account_snapshot'
                     AND julianday(captured_at_utc) <= julianday(received_at_utc)
                         + (? / 86400.0)
                   ORDER BY captured_at_utc DESC, message_id DESC""",
                (source_id, DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS),
            )
            for eligible_row in rows:
                restored = self._restore_snapshot_row(eligible_row, source_id=source_id)
                if _capture_is_plausible(restored):
                    return restored
            return None
        except MessageAdmissionError:
            raise
        except (sqlite3.Error, UnicodeError, ValueError, TypeError) as exc:
            raise TelemetryStorageError("No se pudo recuperar el snapshot guardado") from exc

    def account_for_source(self, source_id: str) -> str:
        """Return the immutable account bound to a registered source."""
        _identifier(source_id)
        try:
            row = self._connection.execute(
                "SELECT account_id FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise TelemetryStorageError("No se pudo leer la cuenta de la fuente") from exc
        if row is None:
            raise MessageAdmissionError("Fuente no registrada")
        return str(row[0])

    def account_history(self, source_id: str, *, from_msc: int, to_msc: int) -> dict[str, Any]:
        """Return at most 480 verified end-of-bucket snapshots using indexed seeks.

        Reads existing evidence only; empty buckets stay empty and no equity is
        reconstructed from deals. Memory and query duration remain bounded.
        """
        if (
            type(from_msc) is not int
            or type(to_msc) is not int
            or not 0 <= from_msc < to_msc < 253402300799000
            or to_msc - from_msc > 366 * 86400000
        ):
            raise ValueError("La ventana debe abarcar hasta 12 meses")
        account_id = self.account_for_source(source_id)
        bucket_msc = max(60000, (to_msc - from_msc + 479) // 480)
        points: list[dict[str, object]] = []
        deadline = time.monotonic() + 2.0
        try:
            for start in range(from_msc, to_msc, bucket_msc):
                if time.monotonic() > deadline:
                    raise TelemetryStorageError("La consulta histórica superó el plazo seguro")
                end = min(to_msc, start + bucket_msc)
                row = self._connection.execute(
                    """SELECT message_id, session_id, sequence, captured_at_utc,
                              received_at_utc, schema_version, collector_version,
                              payload_json, content_sha256
                       FROM telemetry_messages
                       WHERE source_id = ? AND captured_at_utc >= ? AND captured_at_utc < ?
                         AND json_extract(payload_json, '$.kind') = 'account_snapshot'
                       ORDER BY captured_at_utc DESC, message_id DESC LIMIT 1""",
                    (
                        source_id,
                        _timestamp(datetime.fromtimestamp(start / 1000, UTC)),
                        _timestamp(datetime.fromtimestamp(end / 1000, UTC)),
                    ),
                ).fetchone()
                if row is None:
                    continue
                restored = self._restore_snapshot_row(row, source_id=source_id)
                if not _capture_is_plausible(restored):
                    continue
                account = restored.envelope.payload["account"]
                points.append(
                    {
                        "observed_at": restored.envelope.captured_at,
                        "balance": account["balance"],
                        "equity": account["equity"],
                    }
                )
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise TelemetryStorageError("No se pudo consultar balance/equity histórico") from exc
        return {
            "account_id": account_id,
            "source_id": source_id,
            "from_msc": from_msc,
            "to_msc": to_msc,
            "bucket_msc": bucket_msc,
            "sampling": "last_observation_per_bucket",
            "points": points,
        }

    def deal_history(
        self,
        account_id: str,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: DealHistoryCursor | None = None,
    ) -> DealHistoryPage:
        """Read a bounded, newest-first page from overlapping v1 history windows.

        A deal identity is ``account_id + ticket``. When collectors resend or
        correct a deal, the newest captured observation wins. ``to_msc`` is an
        exclusive boundary. The query never mutates the journal or loads all
        matching messages into Python memory.
        """
        _identifier(account_id)
        if (
            isinstance(from_msc, bool)
            or not isinstance(from_msc, int)
            or isinstance(to_msc, bool)
            or not isinstance(to_msc, int)
            or not 0 <= from_msc < to_msc <= MAX_INT64
        ):
            raise ValueError("Período de historial inválido")
        if magic_number is not None:
            _magic_number(magic_number)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("El límite de historial debe ser 1..100")
        if cursor is not None and not isinstance(cursor, DealHistoryCursor):
            raise ValueError("Cursor de historial inválido")

        parameters: list[object] = [account_id, from_msc, to_msc]
        filters = [
            "observation_rank = 1",
            "deal_time_msc >= ?",
            "deal_time_msc < ?",
        ]
        if magic_number is not None:
            filters.append("magic_number = ?")
            parameters.append(magic_number)
        if cursor is not None:
            filters.append(
                """(deal_time_msc < ? OR (deal_time_msc = ? AND
                (length(ticket) < ? OR (length(ticket) = ? AND ticket < ?))))"""
            )
            parameters.extend(
                (
                    cursor.time_msc,
                    cursor.time_msc,
                    len(cursor.ticket),
                    len(cursor.ticket),
                    cursor.ticket,
                )
            )
        parameters.append(limit + 1)
        sql = f"""
            WITH observations AS (
                SELECT a.account_id, s.source_id, m.message_id, m.session_id,
                       m.sequence, m.captured_at_utc, m.received_at_utc,
                       m.schema_version, m.collector_version, m.payload_json,
                       m.content_sha256, deal.value AS deal_json,
                       json_extract(deal.value, '$.ticket') AS ticket,
                       json_extract(deal.value, '$.magic_number') AS magic_number,
                       CAST(json_extract(deal.value, '$.time_msc') AS INTEGER)
                           AS deal_time_msc,
                       ROW_NUMBER() OVER (
                           PARTITION BY a.account_id,
                                        json_extract(deal.value, '$.ticket')
                           ORDER BY m.captured_at_utc DESC, m.message_id DESC,
                                    s.source_id DESC
                       ) AS observation_rank
                FROM telemetry_messages AS m
                JOIN sources AS s ON s.source_id = m.source_id
                JOIN accounts AS a ON a.account_id = s.account_id
                JOIN json_each(m.payload_json, '$.payload.history.deals') AS deal
                WHERE a.account_id = ?
                  AND json_extract(m.payload_json, '$.kind') = 'account_snapshot'
            )
            SELECT account_id, source_id, message_id, session_id, sequence,
                   captured_at_utc, received_at_utc, schema_version,
                   collector_version, payload_json, content_sha256, deal_json,
                   ticket, deal_time_msc
            FROM observations
            WHERE {" AND ".join(filters)}
            ORDER BY deal_time_msc DESC, length(ticket) DESC, ticket DESC
            LIMIT ?
        """
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
            if (
                not rows
                and self._connection.execute(
                    "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
                ).fetchone()
                is None
            ):
                raise MessageAdmissionError("Cuenta no registrada")
            deals = tuple(self._restore_deal_row(row) for row in rows[:limit])
        except MessageAdmissionError:
            raise
        except TelemetryStorageError:
            raise
        except (sqlite3.Error, UnicodeError, ValueError, TypeError, KeyError) as exc:
            raise TelemetryStorageError("No se pudo consultar el historial guardado") from exc
        next_cursor = None
        if len(rows) > limit:
            last = deals[-1]
            next_cursor = DealHistoryCursor(last.time_msc, last.ticket)
        return DealHistoryPage(account_id, deals, next_cursor)

    @staticmethod
    def _restore_deal_row(row: tuple[object, ...]) -> HistoricalDeal:
        (
            account_id,
            source_id,
            message_id,
            session_id,
            sequence,
            captured,
            received,
            schema,
            collector,
            canonical,
            digest,
            deal_json,
            ticket,
            deal_time_msc,
        ) = row
        payload = canonical.encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != digest:
            raise TelemetryStorageError("El mensaje histórico no coincide con su hash")
        envelope = parse_envelope(payload)
        if (
            canonical != envelope.canonical_bytes().decode("utf-8")
            or (envelope.source_id, envelope.session_id, str(envelope.sequence))
            != (source_id, session_id, sequence)
            or _timestamp(datetime.fromisoformat(envelope.captured_at)) != captured
            or (envelope.schema_version, envelope.collector_version) != (schema, collector)
            or envelope.kind != "account_snapshot"
        ):
            raise TelemetryStorageError("Columnas y mensaje histórico no coinciden")
        received_at = datetime.fromisoformat(received)
        if received_at.tzinfo is None or _timestamp(received_at) != received:
            raise TelemetryStorageError("Hora histórica guardada inválida")
        deal: dict[str, Any] = json.loads(deal_json)
        history = envelope.payload.get("history")
        if history is None or deal not in history["deals"]:
            raise TelemetryStorageError("Deal y mensaje histórico no coinciden")
        if deal["ticket"] != ticket or int(deal["time_msc"]) != deal_time_msc:
            raise TelemetryStorageError("Clave de deal histórico inválida")
        return HistoricalDeal(
            account_id=str(account_id),
            source_id=str(source_id),
            message_id=int(message_id),
            captured_at=str(captured),
            ticket=deal["ticket"],
            order_id=deal["order_id"],
            position_id=deal["position_id"],
            magic_number=deal["magic_number"],
            time_msc=int(deal["time_msc"]),
            deal_type=deal["deal_type"],
            entry=deal["entry"],
            symbol=deal["symbol"],
            volume=float(deal["volume"]),
            price=float(deal["price"]),
            profit=float(deal["profit"]),
            commission=float(deal["commission"]),
            swap=float(deal["swap"]),
            fee=float(deal["fee"]),
        )

    @staticmethod
    def _restore_snapshot_row(row: tuple[object, ...], *, source_id: str) -> RestoredSnapshot:
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

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
        except sqlite3.Error as exc:
            raise TelemetryStorageError("No se pudo completar la transacción local") from exc


@contextmanager
def open_registry(path: Path, *, cross_thread: bool = False) -> Iterator[TelemetryRegistry]:
    """Open an existing exact v1 schema, without creating or migrating a database.

    The file and its parent must be under operator control. cross_thread is only
    for a caller that serializes *all* registry access with its own lock.
    """
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
