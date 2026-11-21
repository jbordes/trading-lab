"""Bounded read-only composition of daily closes and the latest observed day."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradinglab.telemetry.central_schema import validate_central_schema
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.sqlite_store import (
    TelemetryRegistry,
    TelemetryStorageError,
    _capture_is_plausible,
)

MAX_POINTS = 480
DAY_MS = 86_400_000
SNAPSHOT_COLUMNS = (
    "m.message_id, m.session_id, m.sequence, m.captured_at_utc, m.received_at_utc, "
    "m.schema_version, m.collector_version, m.payload_json, m.content_sha256"
)


def _stamp(msc: int) -> str:
    return (
        datetime.fromtimestamp(msc / 1000, UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _point(row: tuple, source_id: str, *, resolution: str) -> dict[str, object]:
    # Reuse the storage adapter's canonical/hash/metadata verification.
    restored = TelemetryRegistry._restore_snapshot_row(row, source_id=source_id)
    if not _capture_is_plausible(restored):
        raise ValueError("Hora de captura no verificable")
    envelope = restored.envelope
    marker = envelope.payload.get("server_time_msc")
    broker = datetime(1970, 1, 1) + timedelta(milliseconds=int(marker)) if marker else None
    return {
        "observed_at": envelope.captured_at,
        "balance": envelope.payload["account"]["balance"],
        "equity": envelope.payload["account"]["equity"],
        "resolution": resolution,
        "broker_day": broker.date().isoformat() if broker else None,
        "broker_time": broker.isoformat(timespec="seconds") if broker else None,
    }


def _read_evolution(
    db: sqlite3.Connection,
    source_id: str,
    account_id: str,
    start: int,
    end: int,
    deadline: float,
) -> dict[str, object]:
    daily: list[dict[str, object]] = []
    for row in db.execute(
        "SELECT d.broker_day, d.close_captured_at_utc, d.close_broker_time, d.balance, d.equity, "
        + SNAPSHOT_COLUMNS
        + " FROM account_daily_observations d LEFT JOIN telemetry_messages m "
        "ON m.message_id=d.close_message_id AND m.source_id=d.source_id "
        "WHERE d.account_id=? AND d.source_id=? AND d.close_captured_at_utc>=? "
        "AND d.close_captured_at_utc<? ORDER BY d.close_captured_at_utc LIMIT 481",
        (account_id, source_id, _stamp(start), _stamp(end)),
    ):
        point = _point(row[5:], source_id, resolution="daily")
        if (
            point["broker_day"] != row[0]
            or point["broker_time"] != row[2]
            or datetime.fromisoformat(point["observed_at"]) != datetime.fromisoformat(row[1])
            or any(
                Decimal(str(point[key])) != Decimal(row[index])
                for key, index in (("balance", 3), ("equity", 4))
            )
        ):
            raise ValueError("Resumen diario incompatible con su evidencia")
        daily.append(point)
    if len(daily) >= MAX_POINTS:
        raise ValueError("Demasiados cierres diarios")
    daily_days = {point["broker_day"] for point in daily}
    predicate = (
        " FROM telemetry_messages m WHERE m.source_id=? AND m.compacted_broker_day IS NULL "
        "AND m.captured_at_utc>=? AND m.captured_at_utc<? "
        "AND json_extract(m.payload_json, '$.kind')='account_snapshot'"
    )
    latest_row = db.execute(
        "SELECT "
        + SNAPSHOT_COLUMNS
        + predicate
        + " ORDER BY m.captured_at_utc DESC, m.message_id DESC LIMIT 1",
        (source_id, _stamp(start), _stamp(end)),
    ).fetchone()
    latest = _point(latest_row, source_id, resolution="recent") if latest_row else None
    recent: list[dict[str, object]] = []
    recent_start, bucket = end, 60_000
    basis = "none"
    broker_day = latest["broker_day"] if latest else None
    if latest and (broker_day is None or broker_day not in daily_days):
        recent_end = min(
            end, int(datetime.fromisoformat(latest["observed_at"]).timestamp() * 1000) + 1
        )
        lower = max(start, recent_end - DAY_MS)
        extra = (
            " AND NOT EXISTS (SELECT 1 FROM account_daily_observations d WHERE d.account_id=? "
            "AND d.broker_day=date(CAST(json_extract(m.payload_json, '$.payload.server_time_msc') "
            "AS INTEGER)/1000, 'unixepoch'))"
        )
        extra_parameters: tuple = (account_id,)
        if broker_day is not None:
            day = datetime.combine(date.fromisoformat(broker_day), datetime.min.time(), tzinfo=UTC)
            sentinel = int(day.timestamp() * 1000)
            lower = max(start, sentinel - 14 * 3_600_000 - 2000)
            extra += (
                " AND CAST(json_extract(m.payload_json, '$.payload.server_time_msc') AS INTEGER)>=? "
                "AND CAST(json_extract(m.payload_json, '$.payload.server_time_msc') AS INTEGER)<?"
            )
            extra_parameters += (sentinel, sentinel + DAY_MS)
            basis = "broker_day"
        else:
            basis = "last_24h_unassigned"
        first = db.execute(
            "SELECT m.captured_at_utc"
            + predicate
            + extra
            + " ORDER BY m.captured_at_utc, m.message_id LIMIT 1",
            (source_id, _stamp(lower), _stamp(recent_end), *extra_parameters),
        ).fetchone()
        if first:
            recent_start = max(lower, int(datetime.fromisoformat(first[0]).timestamp() * 1000))
            budget = MAX_POINTS - len(daily)
            bucket = max(60_000, (recent_end - recent_start + budget - 1) // budget)
            for cursor in range(recent_start, recent_end, bucket):
                if time.monotonic() >= deadline:
                    raise ValueError("Consulta fuera del plazo seguro")
                row = db.execute(
                    "SELECT "
                    + SNAPSHOT_COLUMNS
                    + predicate
                    + extra
                    + " ORDER BY m.captured_at_utc DESC, m.message_id DESC LIMIT 1",
                    (
                        source_id,
                        _stamp(cursor),
                        _stamp(min(cursor + bucket, recent_end)),
                        *extra_parameters,
                    ),
                ).fetchone()
                if row:
                    recent.append(_point(row, source_id, resolution="recent"))
    # Missing daily processing is not presented as complete history. Only scan
    # uncompacted bodies through their partial index, not all retained identities.
    pending = (
        db.execute(
            "SELECT 1 FROM telemetry_messages m WHERE m.source_id=? "
            "AND m.compacted_broker_day IS NULL AND m.captured_at_utc>=? AND m.captured_at_utc<? "
            "AND json_extract(m.payload_json, '$.kind')='account_snapshot' "
            "AND NOT EXISTS (SELECT 1 FROM account_daily_observations d WHERE d.account_id=? "
            "AND d.broker_day=date(CAST(json_extract(m.payload_json, '$.payload.server_time_msc') "
            "AS INTEGER)/1000, 'unixepoch')) LIMIT 1",
            (source_id, _stamp(start), _stamp(recent_start), account_id),
        ).fetchone()
        is not None
    )
    points = {datetime.fromisoformat(p["observed_at"]): p for p in recent}
    points.update({datetime.fromisoformat(p["observed_at"]): p for p in daily})
    return {
        "account_id": account_id,
        "source_id": source_id,
        "from_msc": start,
        "to_msc": end,
        "sampling": "daily_close_and_recent",
        "time_basis": "utc",
        "bucket_msc": bucket,
        "recent_basis": basis if recent else "none",
        "recent_from_msc": recent_start if recent else None,
        "unconsolidated_history": pending,
        "points": [points[key] for key in sorted(points)],
    }


def read_account_evolution(
    database: Path, source_id: str, *, from_msc: int, to_msc: int
) -> dict[str, object]:
    """Read one account consistently; never consolidate, migrate, or fill gaps."""
    if (
        not isinstance(source_id, str)
        or not IDENTIFIER.fullmatch(source_id)
        or type(from_msc) is not int
        or type(to_msc) is not int
        or not 0 <= from_msc < to_msc < 253402300799000
        or to_msc - from_msc > 366 * DAY_MS
    ):
        raise ValueError("Ventana o fuente inválida")
    deadline = time.monotonic() + 3.0
    resolved = database.resolve(strict=True)
    try:
        with closing(sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
            db.execute("PRAGMA query_only=ON")
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            db.execute("BEGIN")
            validate_central_schema(db)
            source = db.execute(
                "SELECT account_id FROM sources WHERE source_id=? AND role='snapshot'", (source_id,)
            ).fetchone()
            if source is None:
                raise ValueError("Fuente de capturas no registrada")
            return _read_evolution(db, source_id, source[0], from_msc, to_msc, deadline)
    except (sqlite3.Error, ValueError, TypeError, KeyError, ArithmeticError, AttributeError) as exc:
        raise TelemetryStorageError("No se pudo consultar la evolución observada") from exc
