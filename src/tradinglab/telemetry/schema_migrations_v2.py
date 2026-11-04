"""Explicit offline schema migrations; never part of normal ingestion startup."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from tradinglab.telemetry.contract_v2 import parse_envelope_v2
from tradinglab.telemetry.schema_v2 import (
    POSITION_CYCLE_INDEX,
    POSITION_CYCLE_MAGIC_INDEX,
    POSITION_CYCLE_REVISION_INDEX,
    POSITION_CYCLE_TABLE,
    SCHEMA,
    SCHEMA_V3,
    SCHEMA_V4,
    expected_schema_objects,
    schema_objects,
)
from tradinglab.telemetry.sqlite_store_v2 import V2StorageError


def migrate_v2_database_v3_to_v4(
    path: Path, backup_path: Path, *, project_cycle: Callable[..., None]
) -> int:
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
        if schema_objects(connection) != expected_schema_objects(SCHEMA_V3):
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
        ] or schema_objects(backup_connection) != expected_schema_objects(SCHEMA_V3):
            raise V2StorageError("La copia previa a la migración no quedó verificada")
        backup_connection.close()
        backup_connection = None

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(POSITION_CYCLE_TABLE)
        connection.execute(POSITION_CYCLE_INDEX)
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
            project_cycle(
                connection,
                int(message_id),
                account_id,
                source_id,
                captured,
                envelope.payload["deals"]["items"],
            )
            projected += 1
        connection.execute("PRAGMA user_version = 4")
        if schema_objects(connection) != expected_schema_objects(SCHEMA_V4):
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


def migrate_v2_database_v4_to_v5(path: Path, backup_path: Path) -> None:
    """Back up and atomically add the indexes used by multi-year cycle queries."""

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
        if connection.execute("PRAGMA user_version").fetchone()[0] != 4:
            raise V2StorageError("La migración exige una base v2 con esquema 4")
        if schema_objects(connection) != expected_schema_objects(SCHEMA_V4):
            raise V2StorageError("El esquema 4 no coincide con TradingLab v2")
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise V2StorageError("Falló la comprobación previa de SQLite v2")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise V2StorageError("La base v2 contiene relaciones inválidas")

        backup_connection = sqlite3.connect(backup, timeout=5.0)
        connection.backup(backup_connection)
        backup_connection.commit()
        if backup_connection.execute("PRAGMA quick_check").fetchall() != [
            ("ok",)
        ] or schema_objects(backup_connection) != expected_schema_objects(SCHEMA_V4):
            raise V2StorageError("La copia previa a la migración no quedó verificada")
        backup_connection.close()
        backup_connection = None

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(POSITION_CYCLE_REVISION_INDEX)
        connection.execute(POSITION_CYCLE_MAGIC_INDEX)
        connection.execute("PRAGMA user_version = 5")
        if schema_objects(connection) != expected_schema_objects(SCHEMA):
            raise V2StorageError("El esquema migrado no coincide con TradingLab v2")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise V2StorageError("La migración produjo relaciones inválidas")
        connection.commit()
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
