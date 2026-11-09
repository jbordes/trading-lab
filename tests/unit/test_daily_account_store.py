from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

from test_mt5_telemetry import encoded, snapshot_message

from tradinglab.telemetry.central_migration import (
    PREVIOUS_CENTRAL_SCHEMA,
    migrate_daily_history,
)
from tradinglab.telemetry.central_schema import create_central_database, validate_central_schema
from tradinglab.telemetry.daily_account_store import persist_daily_account_history
from tradinglab.telemetry.sqlite_store import TelemetryStorageError, open_registry

DAY = date(2026, 10, 15)


class DailyAccountStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "central.sqlite3"
        create_central_database(self.path)
        with open_registry(self.path) as registry:
            registry.register_account(
                "test-account",
                "Test",
                "DEMO-SERVER",
                "USD",
                login_masked="****1234",
                created_at=datetime.now(UTC),
            )
            registry.register_source(
                "demo-terminal-01", "test-account", created_at=datetime.now(UTC)
            )

    def add(self, sequence: int, hour: int, balance: int, *, marker: bool = True) -> bytes:
        message = snapshot_message(sequence=sequence)
        captured = datetime(2026, 10, 15, hour, tzinfo=UTC)
        message["captured_at"] = captured.isoformat().replace("+00:00", "Z")
        if marker:
            message["payload"]["server_time_msc"] = str(int(captured.timestamp() * 1000) + 7200000)
        message["payload"]["account"]["balance"] = balance
        raw = encoded(message)
        with open_registry(self.path) as registry:
            registry.store_message(raw, received_at=captured)
        return raw

    def consolidate(self, **overrides):
        arguments = {
            "account_id": "test-account",
            "broker_day": DAY,
            "current_broker_day": date(2026, 10, 16),
        }
        arguments.update(overrides)
        return persist_daily_account_history(self.path, **arguments)

    def read_daily(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT * FROM account_daily_observations").fetchall()

    def test_persists_close_extremes_and_replay_preserves_raw_dedup(self) -> None:
        raw = self.add(1, 10, 120)
        self.add(2, 21, 90)
        self.add(3, 23, 999)  # Next broker day must not become this day's close.
        result = self.consolidate()
        self.assertEqual(result.close.balance, 90)
        self.assertEqual(result.max_balance, 120)
        before = self.read_daily()
        self.assertEqual(self.consolidate(), result)
        self.assertEqual(self.read_daily(), before)
        with open_registry(self.path) as registry:
            self.assertTrue(registry.store_message(raw, received_at=datetime.now(UTC)).duplicate)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM telemetry_messages").fetchone()[0], 3)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_late_arrival_recomputes_without_losing_extremes(self) -> None:
        self.add(1, 10, 120)
        self.consolidate()
        self.add(2, 21, 90)
        result = self.consolidate()
        self.assertEqual((result.close.balance, result.max_balance), (90, 120))
        self.assertEqual(len(self.read_daily()), 1)

    def test_no_data_or_missing_clock_does_not_invent_daily_point(self) -> None:
        self.assertIsNone(self.consolidate())
        self.add(1, 10, 120, marker=False)
        self.assertIsNone(self.consolidate())
        self.assertEqual(self.read_daily(), [])

    def test_rejects_today_unknown_account_and_wrong_schema(self) -> None:
        with self.assertRaises(ValueError):
            self.consolidate(current_broker_day=DAY)
        with self.assertRaises(TelemetryStorageError):
            self.consolidate(account_id="unregistered")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version=7")
        with self.assertRaises(TelemetryStorageError):
            self.consolidate()

    def test_corruption_keeps_previous_daily_row_and_all_evidence(self) -> None:
        self.add(1, 10, 120)
        self.consolidate()
        before = self.read_daily()
        self.add(2, 21, 90)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "UPDATE telemetry_messages SET content_sha256=? WHERE sequence='2'", ("0" * 64,)
            )
        with self.assertRaises(TelemetryStorageError):
            self.consolidate()
        self.assertEqual(self.read_daily(), before)

    def test_failed_write_rolls_back_and_releases_lock(self) -> None:
        self.add(1, 10, 120)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TRIGGER fail_daily BEFORE INSERT ON account_daily_observations "
                "BEGIN SELECT RAISE(ABORT, 'test failure'); END;"
            )
        # Schema validator also refuses unexpected triggers before any write.
        with self.assertRaises(TelemetryStorageError):
            self.consolidate()
        # Bypass only structural inspection to inject an actual SQLite write
        # failure; production never bypasses that inspection.
        with (
            patch("tradinglab.telemetry.daily_account_store.validate_central_schema"),
            self.assertRaises(TelemetryStorageError),
        ):
            self.consolidate()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TRIGGER fail_daily")
        self.assertEqual(self.read_daily(), [])
        self.assertIsNotNone(self.consolidate())

    def test_upgrade_preserves_existing_raw_messages_and_registration(self) -> None:
        raw = self.add(1, 10, 120)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE account_daily_observations")
            db.execute("DROP INDEX telemetry_messages_uncompacted_capture")
            db.execute("DROP INDEX telemetry_messages_broker_day")
            db.execute("ALTER TABLE telemetry_messages DROP COLUMN observed_broker_day")
            db.execute("ALTER TABLE telemetry_messages DROP COLUMN compacted_broker_day")
            db.execute("PRAGMA user_version=7")
        migrate_daily_history(self.path, apply=True)
        with open_registry(self.path) as registry:
            self.assertTrue(registry.store_message(raw, received_at=datetime.now(UTC)).duplicate)
        self.assertEqual(self.consolidate().close.balance, 120)


class DailyAccountMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "old.sqlite3"
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(PREVIOUS_CENTRAL_SCHEMA)
            db.execute("PRAGMA journal_mode=WAL")

    def test_preview_does_not_change_schema_then_apply_is_idempotent(self) -> None:
        before = self.path.read_bytes()
        self.assertFalse(migrate_daily_history(self.path)["changed"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(migrate_daily_history(self.path, apply=True)["changed"])
        with closing(sqlite3.connect(self.path)) as db:
            validate_central_schema(db, check_integrity=True)
        self.assertFalse(migrate_daily_history(self.path, apply=True)["changed"])

    def test_post_ddl_validation_failure_rolls_back_version_and_table(self) -> None:
        with (
            patch(
                "tradinglab.telemetry.central_migration.validate_central_schema",
                side_effect=ValueError,
            ),
            self.assertRaises(ValueError),
        ):
            migrate_daily_history(self.path, apply=True)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='account_daily_observations'"
                ).fetchone()
            )

    def test_unknown_schema_and_missing_path_are_never_created_or_repaired(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE unrelated (id INTEGER)")
        with self.assertRaises(ValueError):
            migrate_daily_history(self.path, apply=True)
        missing = self.path.with_name("missing.sqlite3")
        with self.assertRaises(FileNotFoundError):
            migrate_daily_history(missing, apply=True)
        self.assertFalse(missing.exists())
