"""Isolated durable admission for the proposed telemetry v2 contract."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradinglab.metrics.position_cycles import (
    CycleExclusion,
    CycleLifecycle,
    PositionCycle,
    reconstruct_position_cycles,
)
from tradinglab.telemetry.admission_v2 import (
    AdmissionDisposition,
    AuthorizedEnvelope,
    ProducerIdentity,
    ProducerRole,
    V2AuthorizationError,
    V2ConflictError,
    V2StaleSequenceError,
)
from tradinglab.telemetry.contract import (
    DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS,
    IDENTIFIER,
    TelemetryEnvelope,
)
from tradinglab.telemetry.contract_v2 import SCHEMA_VERSION as WIRE_SCHEMA_VERSION
from tradinglab.telemetry.contract_v2 import parse_envelope_v2

DATABASE_SCHEMA_VERSION = 4

_POSITION_CYCLE_TABLE = """CREATE TABLE position_cycle_observations (
    message_id INTEGER PRIMARY KEY REFERENCES telemetry_v2_messages(message_id),
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    position_id TEXT NOT NULL CHECK(
        length(position_id) BETWEEN 1 AND 20 AND position_id NOT GLOB '*[^0-9]*'
    ),
    owner_magic TEXT,
    started_at_msc INTEGER NOT NULL CHECK(started_at_msc >= 0),
    last_event_at_msc INTEGER NOT NULL CHECK(last_event_at_msc >= started_at_msc),
    lifecycle TEXT NOT NULL CHECK(lifecycle IN ('closed', 'open', 'incomplete', 'inconsistent')),
    remaining_signed_volume TEXT NOT NULL,
    observed_net_result TEXT NOT NULL,
    eligible INTEGER NOT NULL CHECK(eligible IN (0, 1)),
    observed_magics_json TEXT NOT NULL CHECK(json_valid(observed_magics_json)),
    deal_tickets_json TEXT NOT NULL CHECK(json_valid(deal_tickets_json)),
    exclusions_json TEXT NOT NULL CHECK(json_valid(exclusions_json)),
    cycle_json TEXT NOT NULL CHECK(json_valid(cycle_json)),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    captured_at_utc TEXT NOT NULL
) STRICT;"""
_POSITION_CYCLE_INDEX = """CREATE INDEX position_cycle_observations_query
ON position_cycle_observations(account_id, last_event_at_msc, position_id);"""
_POSITION_CYCLE_DDL = _POSITION_CYCLE_TABLE + "\n" + _POSITION_CYCLE_INDEX

_SCHEMA = f"""
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
CREATE TABLE activity_observations (
    message_id INTEGER NOT NULL REFERENCES telemetry_v2_messages(message_id),
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    entity_type TEXT NOT NULL CHECK(entity_type IN ('deal', 'order')),
    ticket TEXT NOT NULL CHECK(
        length(ticket) BETWEEN 1 AND 20 AND ticket NOT GLOB '*[^0-9]*'
    ),
    event_msc INTEGER NOT NULL CHECK(event_msc BETWEEN 0 AND 9223372036854775807),
    magic_number TEXT NOT NULL CHECK(
        length(magic_number) BETWEEN 1 AND 20
    ),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    session_id TEXT NOT NULL,
    sequence TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    received_at_utc TEXT NOT NULL,
    row_json TEXT NOT NULL CHECK(json_valid(row_json)),
    PRIMARY KEY(message_id, entity_type, ticket)
) STRICT;
CREATE INDEX activity_observations_query
ON activity_observations(account_id, entity_type, ticket, captured_at_utc);
CREATE TABLE activity_coverage (
    message_id INTEGER NOT NULL REFERENCES telemetry_v2_messages(message_id),
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    entity_type TEXT NOT NULL CHECK(entity_type IN ('deal', 'order')),
    from_server_msc INTEGER NOT NULL CHECK(from_server_msc >= 0),
    to_server_msc INTEGER NOT NULL CHECK(to_server_msc >= from_server_msc),
    status TEXT NOT NULL CHECK(status IN ('complete', 'truncated', 'error')),
    reported_total INTEGER,
    captured_at_utc TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    session_id TEXT NOT NULL,
    sequence TEXT NOT NULL,
    collection_json TEXT NOT NULL CHECK(json_valid(collection_json)),
    PRIMARY KEY(message_id, entity_type)
) STRICT;
CREATE INDEX activity_coverage_query
ON activity_coverage(account_id, entity_type, from_server_msc, to_server_msc);
{_POSITION_CYCLE_DDL}
PRAGMA user_version = 4;
COMMIT;
"""
_SCHEMA_V3 = _SCHEMA.replace(_POSITION_CYCLE_DDL, "").replace(
    "PRAGMA user_version = 4", "PRAGMA user_version = 3"
)


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


@dataclass(frozen=True, slots=True)
class RestoredV2Message:
    account_id: str
    role: ProducerRole
    envelope: TelemetryEnvelope
    received_at: datetime
    message_id: int
    sequence_gap: int
    out_of_order: bool


@dataclass(frozen=True, slots=True)
class RegisteredV2Source:
    source_id: str
    role: ProducerRole


@dataclass(frozen=True, slots=True)
class V2AccountEvidence:
    account_id: str
    label: str
    identity: ProducerIdentity
    sources: tuple[RegisteredV2Source, ...]
    messages: tuple[RestoredV2Message, ...]


@dataclass(frozen=True, slots=True)
class V2ActivityItem:
    message_id: int
    ticket: str
    values: dict[str, object]
    observed_at: str
    received_at: str
    source_id: str
    session_id: str
    sequence: int
    conflict_at: str | None


@dataclass(frozen=True, slots=True)
class V2ActivityPage:
    account_id: str
    entity_type: str
    items: tuple[V2ActivityItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class V2CoverageReport:
    account_id: str
    entity_type: str
    complete_ranges: tuple[tuple[str, str], ...]
    incomplete_batches: int


@dataclass(frozen=True, slots=True)
class V2PositionCycleItem:
    message_id: int
    cycle: PositionCycle
    source_id: str
    captured_at: str


@dataclass(frozen=True, slots=True)
class V2PositionCyclePage:
    account_id: str
    owner_magic: str | None
    items: tuple[V2PositionCycleItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class _PositionDeal:
    account_id: str
    ticket: str
    position_id: str
    magic_number: str
    time_msc: int
    deal_type: int
    entry: int
    volume: float
    profit: float
    commission: float
    swap: float
    fee: float


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


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _cycle_document(cycle: PositionCycle) -> dict[str, object]:
    return {
        "account_id": cycle.account_id,
        "position_id": cycle.position_id,
        "owner_magic": cycle.owner_magic,
        "observed_magics": cycle.observed_magics,
        "started_at_msc": cycle.started_at_msc,
        "last_event_at_msc": cycle.last_event_at_msc,
        "lifecycle": cycle.lifecycle.value,
        "remaining_signed_volume": str(cycle.remaining_signed_volume),
        "observed_net_result": str(cycle.observed_net_result),
        "deal_tickets": cycle.deal_tickets,
        "exclusions": tuple(reason.value for reason in cycle.exclusions),
    }


def _restore_cycle(document: str) -> PositionCycle:
    try:
        value = json.loads(document)
        return PositionCycle(
            account_id=value["account_id"],
            position_id=value["position_id"],
            owner_magic=value["owner_magic"],
            observed_magics=tuple(value["observed_magics"]),
            started_at_msc=value["started_at_msc"],
            last_event_at_msc=value["last_event_at_msc"],
            lifecycle=CycleLifecycle(value["lifecycle"]),
            remaining_signed_volume=Decimal(value["remaining_signed_volume"]),
            observed_net_result=Decimal(value["observed_net_result"]),
            deal_tickets=tuple(value["deal_tickets"]),
            exclusions=tuple(CycleExclusion(reason) for reason in value["exclusions"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise V2StorageError("Ciclo de posición guardado inválido") from exc


def _schema_objects(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()


def _expected_schema_objects(schema: str) -> list[tuple[str, str, str]]:
    reference = sqlite3.connect(":memory:")
    try:
        reference.executescript(schema)
        return _schema_objects(reference)
    finally:
        reference.close()


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
            capture_is_plausible = datetime.fromisoformat(envelope.captured_at) <= (
                received_at.astimezone(UTC)
                + timedelta(seconds=DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS)
            )
            if envelope.kind == "activity_batch" and capture_is_plausible:
                self._project_activity(
                    connection,
                    result.message_id,
                    authorized.account_id,
                    envelope,
                    captured,
                    received,
                )
        return result

    @staticmethod
    def _project_activity(
        connection: sqlite3.Connection,
        message_id: int,
        account_id: str,
        envelope: TelemetryEnvelope,
        captured: str,
        received: str,
    ) -> None:
        payload = envelope.payload
        window = payload["window"]
        for collection, entity_type, time_field in (
            ("deals", "deal", "time_msc"),
            ("orders", "order", "done_time_msc"),
        ):
            evidence = payload[collection]
            if payload["reason"] != "position_reconcile":
                connection.execute(
                    """INSERT INTO activity_coverage
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        account_id,
                        entity_type,
                        int(window["from_server_msc"]),
                        int(window["to_server_msc"]),
                        evidence["status"],
                        evidence["total"],
                        captured,
                        envelope.source_id,
                        envelope.session_id,
                        str(envelope.sequence),
                        json.dumps(
                            evidence,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                )
            for row in evidence["items"]:
                canonical_row = json.dumps(
                    row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                connection.execute(
                    """INSERT INTO activity_observations VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        account_id,
                        entity_type,
                        row["ticket"],
                        int(row[time_field]),
                        row["magic_number"],
                        envelope.source_id,
                        envelope.session_id,
                        str(envelope.sequence),
                        captured,
                        received,
                        canonical_row,
                    ),
                )
        if payload["reason"] == "position_reconcile":
            V2TelemetryRegistry._project_position_cycle(
                connection,
                message_id,
                account_id,
                envelope.source_id,
                captured,
                payload["deals"]["items"],
            )

    @staticmethod
    def _project_position_cycle(
        connection: sqlite3.Connection,
        message_id: int,
        account_id: str,
        source_id: str,
        captured: str,
        rows: list[dict[str, object]],
    ) -> None:
        deals = tuple(
            _PositionDeal(
                account_id=account_id,
                ticket=str(row["ticket"]),
                position_id=str(row["position_id"]),
                magic_number=str(row["magic_number"]),
                time_msc=int(str(row["time_msc"])),
                deal_type=int(row["deal_type"]),
                entry=int(row["entry"]),
                volume=float(row["volume"]),
                profit=float(row["profit"]),
                commission=float(row["commission"]),
                swap=float(row["swap"]),
                fee=float(row["fee"]),
            )
            for row in rows
        )
        position_id = deals[0].position_id
        selection = reconstruct_position_cycles(
            deals,
            coverage_confirmed={(account_id, position_id)},
        )
        if len(selection.cycles) != 1:
            raise V2StorageError("La reconciliación no produjo un único ciclo de posición")
        cycle = selection.cycles[0]
        cycle_document = _cycle_document(cycle)
        connection.execute(
            """INSERT INTO position_cycle_observations
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                account_id,
                cycle.position_id,
                cycle.owner_magic,
                cycle.started_at_msc,
                cycle.last_event_at_msc,
                cycle.lifecycle.value,
                str(cycle.remaining_signed_volume),
                str(cycle.observed_net_result),
                int(cycle.eligible_for_autonomous_metrics),
                _canonical_json(cycle.observed_magics),
                _canonical_json(cycle.deal_tickets),
                _canonical_json(tuple(reason.value for reason in cycle.exclusions)),
                _canonical_json(cycle_document),
                source_id,
                captured,
            ),
        )

    def activity_page(
        self,
        account_id: str,
        entity_type: str,
        *,
        from_msc: int,
        to_msc: int,
        magic_number: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> V2ActivityPage:
        """Return resolved activity using bounded keyset pagination."""

        account = _identifier(account_id, "account_id")
        if entity_type not in {"deal", "order"}:
            raise ValueError("entity_type debe ser deal u order")
        if (
            isinstance(from_msc, bool)
            or not isinstance(from_msc, int)
            or isinstance(to_msc, bool)
            or not isinstance(to_msc, int)
            or not 0 <= from_msc < to_msc <= 2**63 - 1
        ):
            raise ValueError("Rango temporal inválido")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit debe estar entre 1 y 100")
        if magic_number is not None:
            if not isinstance(magic_number, str) or not magic_number:
                raise ValueError("magic_number inválido")
            try:
                magic = int(magic_number)
            except ValueError as exc:
                raise ValueError("magic_number inválido") from exc
            if not -(2**63) <= magic <= 2**63 - 1 or str(magic) != magic_number:
                raise ValueError("magic_number inválido")
        cursor_event, cursor_ticket = self._decode_activity_cursor(cursor)
        filters = ["event_msc >= ?", "event_msc < ?"]
        parameters: list[object] = [account, entity_type, from_msc, to_msc]
        if magic_number is not None:
            filters.append("magic_number = ?")
            parameters.append(magic_number)
        if cursor_event is not None and cursor_ticket is not None:
            filters.append(
                "(event_msc < ? OR "
                "(event_msc = ? AND (length(ticket) < ? OR "
                "(length(ticket) = ? AND ticket < ?))))"
            )
            parameters.extend(
                [
                    cursor_event,
                    cursor_event,
                    len(cursor_ticket),
                    len(cursor_ticket),
                    cursor_ticket,
                ]
            )
        where = " AND ".join(filters)
        parameters.append(limit + 1)
        sql = f"""
            WITH session_ranked AS (
                SELECT o.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY ticket, captured_at_utc, session_id
                        ORDER BY length(sequence) DESC, sequence DESC, message_id DESC
                    ) AS session_rank
                FROM activity_observations o
                WHERE account_id = ? AND entity_type = ?
            ), capture_summary AS (
                SELECT ticket, captured_at_utc, COUNT(DISTINCT row_json) AS variants
                FROM session_ranked WHERE session_rank = 1
                GROUP BY ticket, captured_at_utc
            ), eligible AS (
                SELECT s.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.ticket
                        ORDER BY s.captured_at_utc DESC, s.message_id DESC
                    ) AS capture_rank
                FROM session_ranked s
                JOIN capture_summary c USING(ticket, captured_at_utc)
                WHERE s.session_rank = 1 AND c.variants = 1
            ), resolved AS (
                SELECT e.*,
                    (SELECT MAX(c.captured_at_utc) FROM capture_summary c
                     WHERE c.ticket = e.ticket AND c.variants > 1
                       AND c.captured_at_utc > e.captured_at_utc) AS conflict_at
                FROM eligible e WHERE e.capture_rank = 1
            )
            SELECT ticket, row_json, captured_at_utc, received_at_utc,
                   source_id, session_id, sequence, conflict_at, event_msc, message_id
            FROM resolved WHERE {where}
            ORDER BY event_msc DESC, length(ticket) DESC, ticket DESC
            LIMIT ?
        """
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as exc:
            raise V2StorageError("No se pudo consultar la actividad v2") from exc
        items = tuple(
            V2ActivityItem(
                message_id=int(row[9]),
                ticket=row[0],
                values=json.loads(row[1]),
                observed_at=row[2],
                received_at=row[3],
                source_id=row[4],
                session_id=row[5],
                sequence=int(row[6]),
                conflict_at=row[7],
            )
            for row in rows[:limit]
        )
        next_cursor = None
        if len(rows) > limit and items:
            next_cursor = self._encode_activity_cursor(int(rows[limit - 1][8]), items[-1].ticket)
        return V2ActivityPage(account, entity_type, items, next_cursor)

    def coverage_report(
        self,
        account_id: str,
        entity_type: str,
        *,
        from_msc: int,
        to_msc: int,
    ) -> V2CoverageReport:
        """Return merged complete coverage and count incomplete overlapping batches."""

        account = _identifier(account_id, "account_id")
        if entity_type not in {"deal", "order"}:
            raise ValueError("entity_type debe ser deal u order")
        if not 0 <= from_msc < to_msc <= 2**63 - 1:
            raise ValueError("Rango temporal inválido")
        rows = self._connection.execute(
            """WITH session_ranked AS (
                SELECT c.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY captured_at_utc, session_id
                        ORDER BY length(sequence) DESC, sequence DESC, message_id DESC
                    ) AS session_rank
                FROM activity_coverage c
                WHERE account_id = ? AND entity_type = ?
            ), capture_summary AS (
                SELECT captured_at_utc, COUNT(DISTINCT collection_json) AS variants
                FROM session_ranked WHERE session_rank = 1
                GROUP BY captured_at_utc
            ), resolved AS (
                SELECT s.* FROM session_ranked s
                JOIN capture_summary c USING(captured_at_utc)
                WHERE s.session_rank = 1 AND c.variants = 1
            )
            SELECT from_server_msc, to_server_msc, status
            FROM resolved
            WHERE to_server_msc >= ? AND from_server_msc < ?
            ORDER BY from_server_msc, to_server_msc""",
            (account, entity_type, from_msc, to_msc),
        ).fetchall()
        merged: list[list[int]] = []
        incomplete = 0
        for start_text, end_text, status in rows:
            if status != "complete":
                incomplete += 1
                continue
            start, end = max(start_text, from_msc), min(end_text, to_msc)
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return V2CoverageReport(
            account,
            entity_type,
            tuple((str(start), str(end)) for start, end in merged),
            incomplete,
        )

    def position_cycles(
        self,
        account_id: str,
        *,
        owner_magic: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> V2PositionCyclePage:
        """Return the latest unambiguous durable observation of each position cycle."""

        account = _identifier(account_id, "account_id")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit debe estar entre 1 y 500")
        if owner_magic is not None:
            if not isinstance(owner_magic, str) or not owner_magic:
                raise ValueError("owner_magic inválido")
            try:
                int(owner_magic)
            except ValueError as exc:
                raise ValueError("owner_magic inválido") from exc
        cursor_event, cursor_position = self._decode_activity_cursor(cursor)
        if cursor_position is not None and (
            cursor_position == "0" or str(int(cursor_position)) != cursor_position
        ):
            raise ValueError("Cursor de ciclos inválido")
        filters = ["account_id = ?"]
        parameters: list[object] = [account]
        if owner_magic is not None:
            filters.append("owner_magic = ?")
            parameters.append(owner_magic)
        result_filter = "capture_rank = 1"
        if cursor_event is not None and cursor_position is not None:
            result_filter += """ AND (last_event_at_msc < ? OR
                (last_event_at_msc = ? AND (length(position_id) < ? OR
                (length(position_id) = ? AND position_id < ?))))"""
            parameters.extend(
                (
                    cursor_event,
                    cursor_event,
                    len(cursor_position),
                    len(cursor_position),
                    cursor_position,
                )
            )
        parameters.append(limit + 1)
        rows = self._connection.execute(
            f"""WITH filtered AS (
                SELECT * FROM position_cycle_observations
                WHERE {" AND ".join(filters)}
            ), capture_summary AS (
                SELECT account_id, position_id, captured_at_utc,
                       COUNT(DISTINCT cycle_json) AS variants
                FROM filtered
                GROUP BY account_id, position_id, captured_at_utc
            ), eligible AS (
                SELECT p.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.position_id
                        ORDER BY p.captured_at_utc DESC, p.message_id DESC
                    ) AS capture_rank
                FROM filtered p
                JOIN capture_summary c USING(account_id, position_id, captured_at_utc)
                WHERE c.variants = 1
            )
            SELECT message_id, cycle_json, source_id, captured_at_utc,
                   position_id, owner_magic, started_at_msc, last_event_at_msc,
                   lifecycle, remaining_signed_volume, observed_net_result, eligible,
                   observed_magics_json, deal_tickets_json, exclusions_json
            FROM eligible WHERE {result_filter}
            ORDER BY last_event_at_msc DESC, length(position_id) DESC, position_id DESC
            LIMIT ?""",
            parameters,
        ).fetchall()
        items: list[V2PositionCycleItem] = []
        for row in rows:
            cycle = _restore_cycle(row[1])
            expected = (
                account,
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
                row[13],
                row[14],
            )
            actual = (
                cycle.account_id,
                cycle.position_id,
                cycle.owner_magic,
                cycle.started_at_msc,
                cycle.last_event_at_msc,
                cycle.lifecycle.value,
                str(cycle.remaining_signed_volume),
                str(cycle.observed_net_result),
                int(cycle.eligible_for_autonomous_metrics),
                _canonical_json(cycle.observed_magics),
                _canonical_json(cycle.deal_tickets),
                _canonical_json(tuple(reason.value for reason in cycle.exclusions)),
            )
            if actual != expected:
                raise V2StorageError("Columnas y ciclo de posición guardado no coinciden")
            items.append(V2PositionCycleItem(int(row[0]), cycle, row[2], row[3]))
        page_items = tuple(items[:limit])
        next_cursor = None
        if len(items) > limit and page_items:
            cycle = page_items[-1].cycle
            next_cursor = self._encode_activity_cursor(
                cycle.last_event_at_msc,
                cycle.position_id,
            )
        return V2PositionCyclePage(account, owner_magic, page_items, next_cursor)

    @staticmethod
    def _encode_activity_cursor(event_msc: int, ticket: str) -> str:
        return f"{event_msc}:{ticket}"

    @staticmethod
    def _decode_activity_cursor(cursor: str | None) -> tuple[int | None, str | None]:
        if cursor is None:
            return None, None
        if not isinstance(cursor, str) or ":" not in cursor:
            raise ValueError("Cursor inválido")
        event, ticket = cursor.split(":", 1)
        if not event.isdigit() or not ticket.isdigit() or not ticket:
            raise ValueError("Cursor inválido")
        event_value = int(event)
        if event_value > 2**63 - 1 or int(ticket) > 2**64 - 1:
            raise ValueError("Cursor inválido")
        return event_value, ticket

    def account_messages(self, account_id: str) -> tuple[RestoredV2Message, ...]:
        """Restore and verify a consistent snapshot of one account's messages."""

        return self.account_evidence(account_id).messages

    def account_evidence(self, account_id: str) -> V2AccountEvidence:
        """Read registered sources and verified messages in one transaction."""

        account = _identifier(account_id, "account_id")
        try:
            with self._read_transaction() as connection:
                metadata = connection.execute(
                    """SELECT label, login_masked, server, currency FROM accounts
                    WHERE account_id = ?""",
                    (account,),
                ).fetchone()
                if metadata is None:
                    raise V2AuthorizationError("Cuenta v2 no registrada")
                source_rows = connection.execute(
                    """SELECT source_id, role FROM sources WHERE account_id = ?
                    ORDER BY role, source_id""",
                    (account,),
                ).fetchall()
                rows = connection.execute(
                    """SELECT m.message_id, m.source_id, s.role, m.session_id,
                              m.sequence, m.event_id, m.kind, m.captured_at_utc,
                              m.received_at_utc, m.schema_version,
                              m.collector_version, m.payload_json,
                              m.content_sha256, m.out_of_order, m.gap_count
                    FROM telemetry_v2_messages m
                    JOIN sources s ON s.source_id = m.source_id
                    WHERE s.account_id = ? ORDER BY m.message_id""",
                    (account,),
                ).fetchall()
                messages = tuple(self._restore_message(row, account, metadata[1:]) for row in rows)
                return V2AccountEvidence(
                    account_id=account,
                    label=metadata[0],
                    identity=ProducerIdentity(*metadata[1:]),
                    sources=tuple(
                        RegisteredV2Source(source_id, ProducerRole(role))
                        for source_id, role in source_rows
                    ),
                    messages=messages,
                )
        except V2AuthorizationError, V2StorageError:
            raise
        except (sqlite3.Error, UnicodeError, ValueError, TypeError) as exc:
            raise V2StorageError("No se pudieron restaurar los mensajes v2") from exc

    @staticmethod
    def _restore_message(
        row: tuple[object, ...],
        account_id: str,
        account_identity: tuple[object, ...],
    ) -> RestoredV2Message:
        (
            message_id,
            source_id,
            role,
            session_id,
            sequence,
            event_id,
            kind,
            captured,
            received,
            schema,
            collector,
            canonical,
            digest,
            out_of_order,
            gap_count,
        ) = row
        if not isinstance(canonical, str) or not isinstance(digest, str):
            raise V2StorageError("Contenido v2 guardado inválido")
        payload = canonical.encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != digest:
            raise V2StorageError("El mensaje v2 guardado no coincide con su hash")
        envelope = parse_envelope_v2(payload)
        restored_identity = envelope.payload["identity"]
        if (
            canonical != envelope.canonical_bytes().decode("utf-8")
            or (
                envelope.source_id,
                envelope.session_id,
                str(envelope.sequence),
                envelope.event_id,
                envelope.kind,
                _timestamp(datetime.fromisoformat(envelope.captured_at)),
                envelope.schema_version,
                envelope.collector_version,
            )
            != (
                source_id,
                session_id,
                sequence,
                event_id,
                kind,
                captured,
                schema,
                collector,
            )
            or (
                restored_identity["login_masked"],
                restored_identity["server"],
                restored_identity["currency"],
            )
            != account_identity
            or role not in (ProducerRole.LIVE.value, ProducerRole.ACTIVITY.value)
            or (role == ProducerRole.LIVE.value and kind == "activity_batch")
            or (role == ProducerRole.ACTIVITY.value and kind == "live_snapshot")
            or out_of_order not in (0, 1)
            or not isinstance(gap_count, int)
            or gap_count < 0
        ):
            raise V2StorageError("Columnas y mensaje v2 guardado no coinciden")
        received_at = datetime.fromisoformat(received)
        if received_at.tzinfo is None or _timestamp(received_at) != received:
            raise V2StorageError("Hora de recepción v2 guardada inválida")
        return RestoredV2Message(
            account_id=account_id,
            role=ProducerRole(role),
            envelope=envelope,
            received_at=received_at,
            message_id=int(message_id),
            sequence_gap=gap_count,
            out_of_order=bool(out_of_order),
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
        except sqlite3.Error as exc:
            raise V2StorageError("No se pudo completar la transacción v2") from exc

    @contextmanager
    def _read_transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self._connection.execute("BEGIN")
            yield self._connection
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise


@contextmanager
def open_v2_registry(
    path: Path,
    *,
    cross_thread: bool = False,
    read_only: bool = False,
) -> Iterator[V2TelemetryRegistry]:
    """Open an existing exact v2 schema without creating or migrating it."""

    if path.suffix != ".sqlite3":
        raise ValueError("La base debe usar extensión .sqlite3")
    resolved = path.resolve(strict=True)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            resolved.as_uri() + ("?mode=ro" if read_only else "?mode=rw"),
            uri=True,
            timeout=5.0,
            check_same_thread=not cross_thread,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        if not read_only:
            connection.execute("PRAGMA synchronous = FULL")
        if connection.execute("PRAGMA user_version").fetchone()[0] != DATABASE_SCHEMA_VERSION:
            raise V2StorageError("Versión de esquema v2 no admitida")
        if _schema_objects(connection) != _expected_schema_objects(_SCHEMA):
            raise V2StorageError("El esquema no coincide con TradingLab v2")
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


def migrate_v2_database_v3_to_v4(path: Path, backup_path: Path) -> int:
    """Back up and atomically add durable position-cycle observations.

    Returns the number of existing ``position_reconcile`` messages projected
    during the migration. The source must exist and the backup path must be new.
    """

    if path.suffix != ".sqlite3" or backup_path.suffix != ".sqlite3":
        raise ValueError("La base y su copia deben usar extensión .sqlite3")
    source = path.resolve(strict=True)
    backup = backup_path.resolve(strict=False)
    if source == backup:
        raise ValueError("La copia debe usar otro archivo")
    if backup.exists():
        raise FileExistsError(f"La copia ya existe: {backup}")
    backup.parent.resolve(strict=True)

    connection = sqlite3.connect(source, timeout=5.0)
    backup_connection: sqlite3.Connection | None = None
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 3:
            raise V2StorageError("La migración exige una base v2 con esquema 3")
        if _schema_objects(connection) != _expected_schema_objects(_SCHEMA_V3):
            raise V2StorageError("El esquema 3 no coincide con TradingLab v2")
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise V2StorageError("Falló la comprobación previa de SQLite v2")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise V2StorageError("La base v2 contiene relaciones inválidas")

        backup_connection = sqlite3.connect(backup, timeout=5.0)
        connection.backup(backup_connection)
        backup_connection.commit()
        if backup_connection.execute("PRAGMA quick_check").fetchall() != [
            ("ok",)
        ] or _schema_objects(backup_connection) != _expected_schema_objects(_SCHEMA_V3):
            raise V2StorageError("La copia previa a la migración no quedó verificada")
        backup_connection.close()
        backup_connection = None

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_POSITION_CYCLE_TABLE)
        connection.execute(_POSITION_CYCLE_INDEX)
        projected = 0
        rows = connection.execute(
            """SELECT m.message_id, s.account_id, m.source_id,
                      m.captured_at_utc, m.payload_json
            FROM telemetry_v2_messages m
            JOIN sources s ON s.source_id = m.source_id
            WHERE m.kind = 'activity_batch'
            ORDER BY m.message_id"""
        ).fetchall()
        for message_id, account_id, source_id, captured, canonical in rows:
            envelope = parse_envelope_v2(canonical.encode("utf-8"))
            if envelope.payload["reason"] != "position_reconcile":
                continue
            V2TelemetryRegistry._project_position_cycle(
                connection,
                int(message_id),
                account_id,
                source_id,
                captured,
                envelope.payload["deals"]["items"],
            )
            projected += 1
        connection.execute("PRAGMA user_version = 4")
        if _schema_objects(connection) != _expected_schema_objects(_SCHEMA):
            raise V2StorageError("El esquema migrado no coincide con TradingLab v2")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise V2StorageError("La migración produjo relaciones inválidas")
        connection.commit()
        return projected
    except sqlite3.Error as exc:
        connection.rollback()
        raise V2StorageError("No se pudo migrar la base v2") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        if backup_connection is not None:
            backup_connection.close()
        connection.close()
