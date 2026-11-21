"""Bounded, opt-in payload compaction after atomic daily consolidation."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from tradinglab.telemetry.central_schema import validate_central_schema
from tradinglab.telemetry.daily_account_history import consolidate_broker_day
from tradinglab.telemetry.daily_account_store import (
    consolidate_daily_on_connection,
    verified_daily_samples,
)
from tradinglab.telemetry.sqlite_store import TelemetryStorageError

RECENT_BROKER_DAYS = 7  # Today plus the six preceding broker dates.


def compact_account_samples(
    database: Path,
    *,
    account_id: str,
    broker_day: date,
    current_broker_day: date,
    apply: bool = False,
    max_messages: int = 1000,
) -> dict[str, object]:
    """Preview by default, preserving identities/hashes, daily closes and history.

    Caller supplies a trusted current broker date. Re-run bounded batches until
    more_pending is false; no service, scheduler, migration or VACUUM is started.
    """
    consolidate_broker_day(
        (), account_id=account_id, broker_day=broker_day, current_broker_day=current_broker_day
    )
    if broker_day >= current_broker_day - timedelta(days=RECENT_BROKER_DAYS - 1):
        raise ValueError("El día pertenece a la ventana reciente protegida")
    if type(max_messages) is not int or not 1 <= max_messages <= 1000:
        raise ValueError("El lote debe contener entre 1 y 1000 mensajes")
    if database.suffix != ".sqlite3":
        raise ValueError("La base central debe usar extensión .sqlite3")
    resolved = database.resolve(strict=True)
    deadline = time.monotonic() + 3.0
    try:
        mode = "rw" if apply else "ro"
        with closing(
            sqlite3.connect(resolved.as_uri() + f"?mode={mode}", uri=True, timeout=0.1)
        ) as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA synchronous = FULL")
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            with db:
                db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
                validate_central_schema(db)
                daily = consolidate_daily_on_connection(
                    db,
                    account_id=account_id,
                    broker_day=broker_day,
                    current_broker_day=current_broker_day,
                    deadline=deadline,
                    write=apply,
                )
                candidates: list[int] = []
                payload_bytes = 0
                more_pending = False
                if daily is not None:
                    samples = verified_daily_samples(
                        db, account_id=account_id, broker_day=broker_day, deadline=deadline
                    )
                    with closing(samples):
                        for sample in samples:
                            # Keep every capture at the closing instant. This also
                            # preserves the current state if the account stopped.
                            if sample.embedded_history or (
                                sample.observation.captured_at_utc >= daily.close.captured_at_utc
                            ):
                                continue
                            if len(candidates) == max_messages:
                                more_pending = True
                                break
                            candidates.append(sample.message_id)
                            payload_bytes += sample.body_bytes - len("null")
                if apply:
                    changed = db.executemany(
                        "UPDATE telemetry_messages SET payload_json='null', compacted_broker_day=? "
                        "WHERE message_id=? AND compacted_broker_day IS NULL "
                        "AND NOT EXISTS (SELECT 1 FROM account_daily_observations "
                        "WHERE close_message_id=telemetry_messages.message_id)",
                        ((broker_day.isoformat(), message_id) for message_id in candidates),
                    )
                    if changed.rowcount != len(candidates):
                        raise ValueError("Una referencia protegida impidió compactar el lote")
                return {
                    "account_id": account_id,
                    "broker_day": broker_day.isoformat(),
                    "applied": apply,
                    "eligible": len(candidates),
                    "compacted": len(candidates) if apply else 0,
                    "more_pending": more_pending,
                    "payload_bytes_releasable": payload_bytes,
                }
    except (sqlite3.Error, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise TelemetryStorageError(
            "No se pudo compactar; se revirtió la consolidación y el lote"
        ) from exc
