"""Daily observed account history in the single central database."""

DAILY_ACCOUNT_DDL = """CREATE TABLE account_daily_observations (
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    broker_day TEXT NOT NULL CHECK(length(broker_day) = 10),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    close_message_id INTEGER NOT NULL UNIQUE REFERENCES telemetry_messages(message_id),
    first_captured_at_utc TEXT NOT NULL,
    close_captured_at_utc TEXT NOT NULL,
    close_broker_time TEXT NOT NULL,
    balance TEXT NOT NULL,
    equity TEXT NOT NULL,
    floating_pnl TEXT NOT NULL,
    min_balance TEXT NOT NULL,
    max_balance TEXT NOT NULL,
    min_equity TEXT NOT NULL,
    max_equity TEXT NOT NULL,
    last_processed_message_id INTEGER NOT NULL REFERENCES telemetry_messages(message_id)
        CHECK(last_processed_message_id >= close_message_id),
    PRIMARY KEY(account_id, broker_day),
    CHECK(first_captured_at_utc <= close_captured_at_utc),
    CHECK(substr(close_broker_time, 1, 10) = broker_day)
) STRICT;"""
