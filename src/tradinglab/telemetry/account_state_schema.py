"""Account-state message table within the only supported central schema."""

MESSAGES_DDL = """
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
"""

# Additive part of the not-yet-deployed schema 8. Keep MESSAGES_DDL unchanged
# so the explicit migration can still recognize the exact former schema 7.
MESSAGE_COMPACTION_DDL = """ALTER TABLE telemetry_messages
ADD COLUMN compacted_broker_day TEXT CHECK(
    (compacted_broker_day IS NULL AND payload_json != 'null') OR
    (compacted_broker_day IS NOT NULL AND length(compacted_broker_day) = 10
     AND payload_json = 'null')
);"""

UNCOMPACTED_CAPTURE_INDEX = """CREATE INDEX telemetry_messages_uncompacted_capture
ON telemetry_messages(source_id, captured_at_utc, message_id)
WHERE compacted_broker_day IS NULL;"""

OBSERVED_BROKER_DAY_DDL = """ALTER TABLE telemetry_messages
ADD COLUMN observed_broker_day TEXT GENERATED ALWAYS AS (
    CASE WHEN json_valid(payload_json) THEN
      CASE WHEN json_extract(payload_json, '$.kind') = 'account_snapshot' THEN
        date(CAST(json_extract(payload_json, '$.payload.server_time_msc') AS INTEGER)/1000,
             'unixepoch')
      END
    END
) VIRTUAL;"""

BROKER_DAY_INDEX = """CREATE INDEX telemetry_messages_broker_day
ON telemetry_messages(source_id, observed_broker_day, message_id)
WHERE compacted_broker_day IS NULL AND observed_broker_day IS NOT NULL;"""
