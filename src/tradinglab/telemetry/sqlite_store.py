"""Opt-in SQLite schema creation; not connected to the live receiver yet."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
