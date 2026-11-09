"""Bounded daily work planned from durable captures, independent of HTTP/UI."""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from tradinglab.telemetry.account_sample_retention import (
    RECENT_BROKER_DAYS,
    compact_account_samples,
)
from tradinglab.telemetry.central_schema import validate_central_schema
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.daily_account_store import persist_daily_account_history
from tradinglab.telemetry.sqlite_store import TelemetryRegistry, TelemetryStorageError


def _plan(database: Path, account_id: str, now: datetime, limit: int) -> dict[str, object]:
    deadline = time.monotonic() + 3.0
    with closing(
        sqlite3.connect(database.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=0.1)
    ) as db:
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        db.execute("BEGIN")
        validate_central_schema(db)
        source = db.execute(
            "SELECT source_id FROM sources WHERE account_id=? AND role='snapshot'", (account_id,)
        ).fetchone()
        if source is None:
            raise ValueError("Cuenta sin fuente de capturas registrada")
        rows = db.execute(
            "SELECT message_id, session_id, sequence, captured_at_utc, received_at_utc, "
            "schema_version, collector_version, payload_json, content_sha256 "
            "FROM telemetry_messages WHERE source_id=? AND compacted_broker_day IS NULL "
            "AND observed_broker_day IS NOT NULL "
            "ORDER BY captured_at_utc DESC, message_id DESC LIMIT 64",
            source,
        )
        reference = None
        for row in rows:
            if time.monotonic() >= deadline:
                raise ValueError("Planificación fuera del plazo seguro")
            candidate = TelemetryRegistry._restore_snapshot_row(row, source_id=source[0])
            captured = datetime.fromisoformat(candidate.envelope.captured_at)
            if captured <= now and candidate.received_at >= captured - timedelta(seconds=30):
                reference = candidate
                break
        rows.close()
        if reference is None:
            return {
                "reference_mode": "unavailable",
                "broker_day": None,
                "days": [],
                "retention_days": [],
                "more_pending": False,
            }
        captured = datetime.fromisoformat(reference.envelope.captured_at)
        elapsed = now - captured
        broker = datetime(1970, 1, 1) + timedelta(
            milliseconds=int(reference.envelope.payload["server_time_msc"])
        )
        fresh = elapsed <= timedelta(minutes=15)
        # Never advance broker time from the host clock, including across DST.
        frontier = (broker - timedelta(minutes=5)).date()
        days = db.execute(
            "WITH observed AS (SELECT observed_broker_day AS day, MAX(message_id) AS revision "
            "FROM telemetry_messages WHERE source_id=? AND compacted_broker_day IS NULL "
            "AND observed_broker_day IS NOT NULL AND observed_broker_day<? "
            "GROUP BY observed_broker_day) "
            "SELECT o.day FROM observed o LEFT JOIN account_daily_observations d "
            "ON d.account_id=? AND d.broker_day=o.day "
            "WHERE d.account_id IS NULL OR d.last_processed_message_id<o.revision "
            "ORDER BY o.day LIMIT ?",
            (source[0], frontier.isoformat(), account_id, limit + 1),
        ).fetchall()
        cutoff = (frontier - timedelta(days=RECENT_BROKER_DAYS - 1)).isoformat()
        retention = db.execute(
            "SELECT DISTINCT m.observed_broker_day FROM telemetry_messages m "
            "LEFT JOIN account_daily_observations d ON d.account_id=? "
            "AND d.broker_day=m.observed_broker_day "
            "WHERE m.source_id=? AND m.compacted_broker_day IS NULL "
            "AND m.observed_broker_day IS NOT NULL AND m.observed_broker_day<? "
            "AND json_type(m.payload_json, '$.payload.history') IS NULL "
            "AND (d.close_message_id IS NULL OR m.captured_at_utc<d.close_captured_at_utc) "
            "ORDER BY m.observed_broker_day LIMIT ?",
            (account_id, source[0], cutoff, limit + 1),
        ).fetchall()
        return {
            "reference_mode": "fresh" if fresh else "observed_frontier",
            "broker_day": frontier.isoformat(),
            "reference_captured_at": reference.envelope.captured_at,
            "days": [row[0] for row in days[:limit]],
            "retention_days": [row[0] for row in retention[:limit]],
            "more_pending": len(days) > limit or len(retention) > limit,
        }


def run_daily_account_maintenance(
    database: Path,
    account_id: str,
    *,
    apply: bool = False,
    now: datetime | None = None,
    max_days: int = 14,
    max_batches: int = 32,
    budget_seconds: float = 60,
    timer: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Caller owns the job lock and verified backup; preview never writes.

    Each unit commits separately. Budgets stop this run with explicit pending
    work; no busy waits/retry loops. Crashes/repetition resume from DB revisions.
    """
    now = datetime.now(UTC) if now is None else now
    if (
        not isinstance(account_id, str)
        or not IDENTIFIER.fullmatch(account_id)
        or not isinstance(now, datetime)
        or now.utcoffset() is None
        or type(max_days) is not int
        or not 1 <= max_days <= 31
        or type(max_batches) is not int
        or not 1 <= max_batches <= 128
        or type(budget_seconds) not in (int, float)
        or not math.isfinite(budget_seconds)
        or not 1 <= budget_seconds <= 300
        or database.suffix != ".sqlite3"
    ):
        raise ValueError("Configuración de mantenimiento diario inválida")
    deadline = timer() + budget_seconds
    try:
        plan = _plan(database, account_id, now.astimezone(UTC), max_days)
        result = {
            **plan,
            "applied": apply,
            "consolidated_days": 0,
            "compacted_messages": 0,
            "batches": 0,
        }
        if plan["broker_day"] is None:
            return {**result, "state": "deferred", "reason": "broker_clock_unavailable"}
        if not apply:
            return {**result, "state": "preview", "reason": None}
        frontier = date.fromisoformat(plan["broker_day"])
        pending = plan["more_pending"]
        for day in plan["days"]:
            if timer() >= deadline:
                return {
                    **result,
                    "state": "partial",
                    "reason": "budget_exhausted",
                    "more_pending": True,
                }
            persist_daily_account_history(
                database,
                account_id=account_id,
                broker_day=date.fromisoformat(day),
                current_broker_day=frontier,
            )
            result["consolidated_days"] += 1
        for day in plan["retention_days"]:
            for _ in range(max_batches - result["batches"]):
                if timer() >= deadline:
                    return {
                        **result,
                        "state": "partial",
                        "reason": "budget_exhausted",
                        "more_pending": True,
                    }
                batch = compact_account_samples(
                    database,
                    account_id=account_id,
                    broker_day=date.fromisoformat(day),
                    current_broker_day=frontier,
                    apply=True,
                )
                result["batches"] += 1
                result["compacted_messages"] += batch["compacted"]
                if not batch["more_pending"]:
                    break
            else:
                pending = True
                break
        result["more_pending"] = pending
        stale = plan["reference_mode"] != "fresh"
        return {
            **result,
            "state": "partial" if pending or stale else "succeeded",
            "reason": "work_limit" if pending else "stale_broker_clock" if stale else None,
        }
    except (sqlite3.Error, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise TelemetryStorageError(
            "Falló el mantenimiento diario; se conserva el trabajo ya confirmado"
        ) from exc
