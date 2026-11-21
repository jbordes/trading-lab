"""Read-only, privacy-conscious summaries of a local telemetry database."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from tradinglab.telemetry.central_schema import (
    CENTRAL_SCHEMA_VERSION,
    DATABASE_NAME,
    validate_central_schema,
)
from tradinglab.telemetry.contract import (
    DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS,
    parse_envelope,
)


class TelemetryInspectionError(RuntimeError):
    """The database cannot be inspected safely as TradingLab telemetry."""


@dataclass(frozen=True, slots=True)
class TelemetrySummary:
    database: Path
    size_bytes: int
    schema_version: int
    source_ids: tuple[str, ...]
    session_count: int
    message_count: int
    snapshot_count: int
    heartbeat_count: int
    first_captured_at: str | None
    last_captured_at: str | None
    latest_positions: int
    latest_orders: int
    latest_history_status: str | None
    unique_historical_deals: int
    magic_numbers: tuple[str, ...]
    account_state_message_count: int
    trading_events_message_count: int
    live_snapshot_count: int
    activity_batch_count: int
    trading_heartbeat_count: int
    unique_historical_orders: int


@dataclass(frozen=True, slots=True)
class InspectionPlan:
    root: Path
    filename: str

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or not DATABASE_NAME.fullmatch(self.filename):
            raise ValueError("Nombre de base SQLite inválido")

    @property
    def database(self) -> Path:
        root = self.root.resolve()
        storage = root / "_storage"
        database = storage / self.filename
        if not storage.resolve().is_relative_to(root):
            raise ValueError("_storage debe permanecer dentro del checkout")
        if not database.is_file() or database.is_symlink():
            raise FileNotFoundError("La base local no existe o es un enlace")
        return database

    def inspect(self, *, verify: bool = False) -> TelemetrySummary:
        """Return aggregate evidence without exposing accounts, tickets, or payloads."""
        database = self.database
        try:
            with closing(
                sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)
            ) as connection:
                connection.execute("PRAGMA query_only = ON")
                connection.execute("BEGIN")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != CENTRAL_SCHEMA_VERSION:
                    raise TelemetryInspectionError("Versión SQLite de TradingLab no admitida")
                validate_central_schema(connection)
                if verify:
                    if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise TelemetryInspectionError("La base no pasó la comprobación SQLite")
                    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise TelemetryInspectionError("La base contiene relaciones inválidas")
                return _summarize(connection, database, version)
        except TelemetryInspectionError:
            raise
        except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            raise TelemetryInspectionError("No se pudo inspeccionar la base SQLite") from exc


def _summarize(connection: sqlite3.Connection, database: Path, version: int) -> TelemetrySummary:
    source_ids = tuple(
        row[0] for row in connection.execute("SELECT source_id FROM sources ORDER BY source_id")
    )
    session_count = connection.execute(
        """SELECT COUNT(*) FROM (
             SELECT source_id, session_id FROM telemetry_messages
             UNION SELECT source_id, session_id FROM telemetry_v2_messages
           )"""
    ).fetchone()[0]
    counts = connection.execute(
        """WITH messages AS (
             SELECT CASE WHEN compacted_broker_day IS NOT NULL THEN 'account_snapshot'
                         ELSE json_extract(payload_json, '$.kind') END AS kind, captured_at_utc,
                    'account-state' AS channel FROM telemetry_messages
             UNION ALL
             SELECT kind, captured_at_utc, 'trading-events' FROM telemetry_v2_messages
           ) SELECT COUNT(*),
                  COALESCE(SUM(kind = 'account_snapshot'), 0),
                  COALESCE(SUM(channel = 'account-state' AND kind = 'heartbeat'), 0),
                  MIN(captured_at_utc), MAX(captured_at_utc),
                  COALESCE(SUM(channel = 'account-state'), 0),
                  COALESCE(SUM(channel = 'trading-events'), 0),
                  COALESCE(SUM(kind = 'live_snapshot'), 0),
                  COALESCE(SUM(kind = 'activity_batch'), 0),
                  COALESCE(SUM(channel = 'trading-events' AND kind = 'heartbeat'), 0)
           FROM messages"""
    ).fetchone()
    latest = connection.execute(
        """SELECT payload_json FROM (
             SELECT payload_json,
                    ROW_NUMBER() OVER (
                      PARTITION BY source_id
                      ORDER BY captured_at_utc DESC, message_id DESC
                    ) AS position
             FROM telemetry_messages
             WHERE json_extract(payload_json, '$.kind') = 'account_snapshot'
               AND julianday(captured_at_utc) <= julianday(received_at_utc)
                   + (? / 86400.0)
           ) WHERE position = 1""",
        (DEFAULT_CAPTURE_FUTURE_TOLERANCE_SECONDS,),
    ).fetchall()
    positions = orders = 0
    history_statuses: set[str | None] = set()
    for row in latest:
        envelope = parse_envelope(row[0].encode("utf-8"))
        payload = envelope.payload
        positions += len(payload["positions"])
        orders += len(payload["orders"])
        status = payload.get("history", {}).get("status")
        history_statuses.add(status)
    history_status = next(iter(history_statuses)) if len(history_statuses) == 1 else None
    unique_deals = connection.execute(
        """SELECT COUNT(*) FROM (
             SELECT DISTINCT source.account_id,
                    json_extract(deal.value, '$.ticket') AS ticket
             FROM telemetry_messages AS message
             JOIN sources AS source ON source.source_id = message.source_id
             JOIN json_each(message.payload_json, '$.payload.history.deals') AS deal
             WHERE json_extract(message.payload_json, '$.kind') = 'account_snapshot'
             UNION
             SELECT account_id, ticket FROM activity_observations WHERE entity_type = 'deal'
           )"""
    ).fetchone()[0]
    unique_orders = connection.execute(
        """SELECT COUNT(*) FROM (
             SELECT DISTINCT account_id, ticket FROM activity_observations WHERE entity_type = 'order'
           )"""
    ).fetchone()[0]
    magic_rows = connection.execute(
        """WITH magic(value) AS (
             SELECT json_extract(row.value, '$.magic_number')
             FROM telemetry_messages AS message,
                  json_each(message.payload_json, '$.payload.positions') AS row
             UNION
             SELECT json_extract(row.value, '$.magic_number')
             FROM telemetry_messages AS message,
                  json_each(message.payload_json, '$.payload.orders') AS row
             UNION
             SELECT json_extract(row.value, '$.magic_number')
             FROM telemetry_messages AS message,
                  json_each(message.payload_json, '$.payload.history.deals') AS row
             UNION
             SELECT magic_number FROM activity_observations
             UNION
             SELECT json_extract(row.value, '$.magic_number')
             FROM telemetry_v2_messages AS message,
                  json_each(message.payload_json, '$.payload.positions') AS row
             WHERE message.kind = 'live_snapshot'
             UNION
             SELECT json_extract(row.value, '$.magic_number')
             FROM telemetry_v2_messages AS message,
                  json_each(message.payload_json, '$.payload.orders') AS row
             WHERE message.kind = 'live_snapshot'
           ) SELECT value FROM magic WHERE value IS NOT NULL"""
    ).fetchall()
    magic_numbers = tuple(sorted((row[0] for row in magic_rows), key=int))
    return TelemetrySummary(
        database=database,
        size_bytes=database.stat().st_size,
        schema_version=version,
        source_ids=source_ids,
        session_count=session_count,
        message_count=counts[0],
        snapshot_count=counts[1] or 0,
        heartbeat_count=counts[2] or 0,
        first_captured_at=counts[3],
        last_captured_at=counts[4],
        latest_positions=positions,
        latest_orders=orders,
        latest_history_status=history_status,
        unique_historical_deals=unique_deals,
        magic_numbers=magic_numbers,
        account_state_message_count=counts[5],
        trading_events_message_count=counts[6],
        live_snapshot_count=counts[7],
        activity_batch_count=counts[8],
        trading_heartbeat_count=counts[9],
        unique_historical_orders=unique_orders,
    )
