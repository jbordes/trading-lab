"""Explicit, transactional upgrade from the exact central schema 7 to 8."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from tradinglab.telemetry.account_state_schema import (
    BROKER_DAY_INDEX,
    MESSAGE_COMPACTION_DDL,
    MESSAGES_DDL,
    OBSERVED_BROKER_DAY_DDL,
    UNCOMPACTED_CAPTURE_INDEX,
)
from tradinglab.telemetry.central_schema import validate_central_schema
from tradinglab.telemetry.daily_account_schema import DAILY_ACCOUNT_DDL
from tradinglab.telemetry.trading_events_schema import (
    build_schema,
    expected_schema_objects,
    schema_objects,
)

PREVIOUS_CENTRAL_SCHEMA = build_schema(
    version=7, source_roles_sql="'live', 'activity', 'snapshot'", extra_tables=MESSAGES_DDL
)


def migrate_daily_history(database: Path, *, apply: bool = False) -> dict[str, object]:
    """Preview by default; never create a missing DB or upgrade unknown schemas.

    Stop services and take a verified backup before operator-approved application.
    No raw messages or account registrations are rewritten or removed.
    """
    if database.suffix != ".sqlite3":
        raise ValueError("La base central debe usar extensión .sqlite3")
    resolved = database.resolve(strict=True)
    mode = "rw" if apply else "ro"
    with closing(sqlite3.connect(resolved.as_uri() + f"?mode={mode}", uri=True, timeout=1)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA synchronous = FULL")
        try:
            db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 8:
                validate_central_schema(db, check_integrity=True)
                result = {"from_version": 8, "to_version": 8, "changed": False}
            elif version == 7:
                if schema_objects(db) != expected_schema_objects(PREVIOUS_CENTRAL_SCHEMA):
                    raise ValueError("El esquema 7 no coincide con TradingLab Central")
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("Falló la integridad SQLite")
                if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("La base contiene relaciones inválidas")
                if apply:
                    # executescript would implicitly commit; keep DDL/version atomic.
                    db.execute(DAILY_ACCOUNT_DDL)
                    db.execute(MESSAGE_COMPACTION_DDL)
                    db.execute(OBSERVED_BROKER_DAY_DDL)
                    db.execute(UNCOMPACTED_CAPTURE_INDEX)
                    db.execute(BROKER_DAY_INDEX)
                    db.execute("PRAGMA user_version = 8")
                    validate_central_schema(db, check_integrity=True)
                result = {"from_version": 7, "to_version": 8, "changed": apply}
            else:
                raise ValueError("Versión central no admitida para esta migración")
            db.commit()
            return {**result, "applied": apply}
        except sqlite3.Error, ValueError:
            db.rollback()
            raise
