"""SQLite v2 schema definitions and structural verification shared by storage and migrations."""

from __future__ import annotations

import sqlite3

DATABASE_SCHEMA_VERSION = 5

POSITION_CYCLE_TABLE = """CREATE TABLE position_cycle_observations (
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
POSITION_CYCLE_INDEX = """CREATE INDEX position_cycle_observations_query
ON position_cycle_observations(account_id, last_event_at_msc, position_id);"""
POSITION_CYCLE_REVISION_INDEX = """CREATE INDEX position_cycle_observations_revision
ON position_cycle_observations(
    account_id, position_id, captured_at_utc DESC, message_id DESC
);"""
POSITION_CYCLE_MAGIC_INDEX = """CREATE INDEX position_cycle_observations_magic_query
ON position_cycle_observations(account_id, owner_magic, last_event_at_msc, position_id);"""
POSITION_CYCLE_EXTRA_INDEXES = POSITION_CYCLE_REVISION_INDEX + "\n" + POSITION_CYCLE_MAGIC_INDEX
POSITION_CYCLE_DDL_V4 = POSITION_CYCLE_TABLE + "\n" + POSITION_CYCLE_INDEX
POSITION_CYCLE_DDL = POSITION_CYCLE_DDL_V4 + "\n" + POSITION_CYCLE_EXTRA_INDEXES

SCHEMA = f"""
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
{POSITION_CYCLE_DDL}
PRAGMA user_version = 5;
COMMIT;
"""
SCHEMA_V4 = SCHEMA.replace("\n" + POSITION_CYCLE_EXTRA_INDEXES, "").replace(
    "PRAGMA user_version = 5", "PRAGMA user_version = 4"
)
SCHEMA_V3 = SCHEMA_V4.replace(POSITION_CYCLE_DDL_V4, "").replace(
    "PRAGMA user_version = 4", "PRAGMA user_version = 3"
)


def schema_objects(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()


def expected_schema_objects(schema: str) -> list[tuple[str, str, str]]:
    reference = sqlite3.connect(":memory:")
    try:
        reference.executescript(schema)
        return schema_objects(reference)
    finally:
        reference.close()
