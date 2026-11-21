"""Single SQLite schema for account-state and trading-event observations."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from tradinglab.telemetry.account_state_schema import (
    BROKER_DAY_INDEX,
    MESSAGE_COMPACTION_DDL,
    MESSAGES_DDL,
    OBSERVED_BROKER_DAY_DDL,
    UNCOMPACTED_CAPTURE_INDEX,
)
from tradinglab.telemetry.daily_account_schema import DAILY_ACCOUNT_DDL
from tradinglab.telemetry.trading_events_schema import (
    build_schema,
    expected_schema_objects,
    schema_objects,
)

CENTRAL_SCHEMA_VERSION = 8
DATABASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.sqlite3\Z")

CENTRAL_SCHEMA = build_schema(
    version=CENTRAL_SCHEMA_VERSION,
    source_roles_sql="'live', 'activity', 'snapshot'",
    extra_tables="\n".join(
        (
            MESSAGES_DDL,
            MESSAGE_COMPACTION_DDL,
            OBSERVED_BROKER_DAY_DDL,
            UNCOMPACTED_CAPTURE_INDEX,
            BROKER_DAY_INDEX,
            DAILY_ACCOUNT_DDL,
        )
    ),
)


MULTI_SCHEMA = CENTRAL_SCHEMA.replace(
    f"PRAGMA user_version = {CENTRAL_SCHEMA_VERSION};",
    """CREATE TABLE mt5_accounts (
        account_id TEXT PRIMARY KEY REFERENCES accounts(account_id),
        server TEXT NOT NULL,
        login TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('demo','real')),
        history_from INTEGER NOT NULL,
        broker_offset INTEGER NOT NULL,
        UNIQUE(server, login)
    ) STRICT;
    PRAGMA user_version = 9;""",
)


def validate_central_schema(
    connection: sqlite3.Connection, *, check_integrity: bool = False
) -> None:
    """Verify central schema; scan all rows only during creation or backup checks."""

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (CENTRAL_SCHEMA_VERSION, 9):
        raise ValueError("Versión de esquema central no admitida")
    if schema_objects(connection) != expected_schema_objects(
        MULTI_SCHEMA if version == 9 else CENTRAL_SCHEMA
    ):
        raise ValueError("El esquema no coincide con TradingLab Central")
    if check_integrity:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("Falló la comprobación de integridad SQLite")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("La base contiene relaciones inválidas")


def create_central_database(path: Path, *, multicuenta: bool = False) -> None:
    """Create a fresh central database; never overwrite an existing path."""

    if path.suffix != ".sqlite3":
        raise ValueError("La base central debe usar extensión .sqlite3")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(MULTI_SCHEMA if multicuenta else CENTRAL_SCHEMA)
        if connection.execute("PRAGMA journal_mode = WAL").fetchone()[0].lower() != "wal":
            raise RuntimeError("SQLite no habilitó WAL para la base central")
        validate_central_schema(connection, check_integrity=True)
    except sqlite3.Error as exc:
        raise RuntimeError("No se pudo crear el esquema SQLite central") from exc
    finally:
        if connection is not None:
            connection.close()
