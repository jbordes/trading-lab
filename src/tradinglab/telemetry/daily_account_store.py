"""Transactional daily consolidation, preserving aggregates after compaction."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradinglab.telemetry.central_schema import validate_central_schema
from tradinglab.telemetry.contract import parse_envelope
from tradinglab.telemetry.daily_account_history import (
    AccountObservation,
    DailyAccountObservation,
    consolidate_broker_day,
)
from tradinglab.telemetry.sqlite_store import TelemetryStorageError


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class StoredAccountSample:
    message_id: int
    observation: AccountObservation
    embedded_history: bool
    body_bytes: int


def verified_daily_samples(
    db: sqlite3.Connection, *, account_id: str, broker_day: date, deadline: float
) -> Iterator[StoredAccountSample]:
    """Stream a day's uncompacted captures using the source/UTC index."""
    source = db.execute(
        "SELECT source_id FROM sources WHERE account_id=? AND role='snapshot'", (account_id,)
    ).fetchone()
    if source is None:
        raise ValueError("Cuenta sin fuente de capturas registrada")
    source_id = source[0]
    start = datetime.combine(broker_day, datetime.min.time(), tzinfo=UTC)
    margin = timedelta(hours=14, seconds=2)  # Search bound, not an offset conversion.
    lower, upper = _stamp(start - margin), _stamp(start + timedelta(days=1) + margin)
    rows = db.execute(
        "SELECT message_id, session_id, sequence, captured_at_utc, payload_json, "
        "content_sha256 FROM telemetry_messages WHERE source_id=? "
        "AND captured_at_utc>=? AND captured_at_utc<? AND compacted_broker_day IS NULL "
        "ORDER BY captured_at_utc, message_id",
        (source_id, lower, upper),
    )
    try:
        for message_id, session, sequence, captured, body, digest in rows:
            if time.monotonic() >= deadline:
                raise TelemetryStorageError("Consolidación fuera del plazo seguro")
            raw = body.encode("utf-8")
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Captura no coincide con su hash")
            envelope = parse_envelope(raw)
            if (
                (envelope.source_id, envelope.session_id, str(envelope.sequence))
                != (source_id, session, sequence)
                or _stamp(datetime.fromisoformat(envelope.captured_at)) != captured
                or envelope.canonical_bytes() != raw
            ):
                raise ValueError("Captura incompatible con sus metadatos")
            if envelope.kind != "account_snapshot":
                continue
            marker = envelope.payload.get("server_time_msc")
            if marker is None:
                continue
            broker_time = datetime(1970, 1, 1) + timedelta(milliseconds=int(marker))
            if broker_time.date() != broker_day:
                continue
            account = envelope.payload["account"]
            yield StoredAccountSample(
                message_id,
                AccountObservation(
                    account_id,
                    datetime.fromisoformat(envelope.captured_at),
                    broker_time,
                    *(Decimal(str(account[k])) for k in ("balance", "equity", "profit")),
                ),
                "history" in envelope.payload,
                len(raw),
            )
    finally:
        rows.close()


def _merge_saved_day(
    db: sqlite3.Connection, current: DailyAccountObservation
) -> DailyAccountObservation:
    """Retain extrema and first capture from bodies already compacted."""
    row = db.execute(
        "SELECT source_id, close_message_id, first_captured_at_utc, close_captured_at_utc, "
        "close_broker_time, balance, equity, floating_pnl, min_balance, max_balance, "
        "min_equity, max_equity FROM account_daily_observations "
        "WHERE account_id=? AND broker_day=?",
        (current.account_id, current.broker_day.isoformat()),
    ).fetchone()
    if row is None:
        return current
    amounts = tuple(Decimal(value) for value in row[5:])
    first, last = datetime.fromisoformat(row[2]), datetime.fromisoformat(row[3])
    if (
        first.utcoffset() is None
        or last.utcoffset() is None
        or first > last
        or any(not value.is_finite() for value in amounts)
        or not amounts[3] <= amounts[0] <= amounts[4]
        or not amounts[5] <= amounts[1] <= amounts[6]
        or last > current.close.captured_at_utc
    ):
        raise ValueError("Resumen diario inválido")
    close_row = db.execute(
        "SELECT s.account_id, m.source_id, m.captured_at_utc, m.payload_json, m.content_sha256 "
        "FROM telemetry_messages m JOIN sources s ON s.source_id=m.source_id "
        "WHERE m.message_id=? AND m.compacted_broker_day IS NULL",
        (row[1],),
    ).fetchone()
    if close_row is None or close_row[:3] != (current.account_id, row[0], row[3]):
        raise ValueError("Referencia diaria inválida")
    raw = close_row[3].encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != close_row[4]:
        raise ValueError("Referencia diaria no coincide con su hash")
    envelope = parse_envelope(raw)
    observed = envelope.payload["account"]
    broker = datetime(1970, 1, 1) + timedelta(milliseconds=int(envelope.payload["server_time_msc"]))
    if (
        envelope.source_id != row[0]
        or broker.isoformat(timespec="seconds") != row[4]
        or broker.date() != current.broker_day
        or tuple(Decimal(str(observed[k])) for k in ("balance", "equity", "profit")) != amounts[:3]
    ):
        raise ValueError("Cierre diario incompatible con su evidencia")
    return replace(
        current,
        first_captured_at_utc=min(first, current.first_captured_at_utc),
        min_balance=min(amounts[3], current.min_balance),
        max_balance=max(amounts[4], current.max_balance),
        min_equity=min(amounts[5], current.min_equity),
        max_equity=max(amounts[6], current.max_equity),
    )


def consolidate_daily_on_connection(
    db: sqlite3.Connection,
    *,
    account_id: str,
    broker_day: date,
    current_broker_day: date,
    deadline: float,
    write: bool,
) -> DailyAccountObservation | None:
    """Use an owned transaction; optionally preview without any writes."""
    close_message_id: int | None = None
    last_processed_message_id = 0
    latest: datetime | None = None

    def observations() -> Iterator[AccountObservation]:
        nonlocal close_message_id, latest, last_processed_message_id
        for sample in verified_daily_samples(
            db, account_id=account_id, broker_day=broker_day, deadline=deadline
        ):
            captured = sample.observation.captured_at_utc
            last_processed_message_id = max(last_processed_message_id, sample.message_id)
            if latest is None or captured > latest:
                latest, close_message_id = captured, sample.message_id
            yield sample.observation

    result = consolidate_broker_day(
        observations(),
        account_id=account_id,
        broker_day=broker_day,
        current_broker_day=current_broker_day,
    )
    if result is None:
        return None
    result = _merge_saved_day(db, result)
    if not write:
        return result
    assert close_message_id is not None
    close = result.close
    source = db.execute(
        "SELECT source_id FROM telemetry_messages WHERE message_id=?", (close_message_id,)
    ).fetchone()[0]
    db.execute(
        "INSERT INTO account_daily_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(account_id, broker_day) DO UPDATE SET "
        "source_id=excluded.source_id, close_message_id=excluded.close_message_id, "
        "first_captured_at_utc=excluded.first_captured_at_utc, "
        "close_captured_at_utc=excluded.close_captured_at_utc, "
        "close_broker_time=excluded.close_broker_time, balance=excluded.balance, "
        "equity=excluded.equity, floating_pnl=excluded.floating_pnl, "
        "min_balance=excluded.min_balance, max_balance=excluded.max_balance, "
        "min_equity=excluded.min_equity, max_equity=excluded.max_equity, "
        "last_processed_message_id=MAX(account_daily_observations.last_processed_message_id, "
        "excluded.last_processed_message_id)",
        (
            account_id,
            broker_day.isoformat(),
            source,
            close_message_id,
            _stamp(result.first_captured_at_utc),
            _stamp(close.captured_at_utc),
            close.broker_time.isoformat(timespec="seconds"),
            *(
                str(value)
                for value in (
                    close.balance,
                    close.equity,
                    close.floating_pnl,
                    result.min_balance,
                    result.max_balance,
                    result.min_equity,
                    result.max_equity,
                )
            ),
            last_processed_message_id,
        ),
    )
    return result


def persist_daily_account_history(
    database: Path,
    *,
    account_id: str,
    broker_day: date,
    current_broker_day: date,
) -> DailyAccountObservation | None:
    """Atomically upsert one closed day without migrating or compacting data."""
    consolidate_broker_day(
        (), account_id=account_id, broker_day=broker_day, current_broker_day=current_broker_day
    )
    if database.suffix != ".sqlite3":
        raise ValueError("La base central debe usar extensión .sqlite3")
    deadline = time.monotonic() + 3.0
    resolved = database.resolve(strict=True)
    try:
        with closing(sqlite3.connect(resolved.as_uri() + "?mode=rw", uri=True, timeout=0.1)) as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA synchronous = FULL")
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            with db:
                db.execute("BEGIN IMMEDIATE")
                validate_central_schema(db)
                return consolidate_daily_on_connection(
                    db,
                    account_id=account_id,
                    broker_day=broker_day,
                    current_broker_day=current_broker_day,
                    deadline=deadline,
                    write=True,
                )
    except (sqlite3.Error, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise TelemetryStorageError(
            "No se pudo consolidar el día; no se eliminó evidencia"
        ) from exc
