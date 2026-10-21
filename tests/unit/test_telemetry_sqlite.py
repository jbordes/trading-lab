from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.sqlite_store import (  # noqa: E402
    SCHEMA_VERSION,
    RegistrationConflictError,
    TelemetryStorageError,
    create_database,
    open_registry,
)

STAMP = "2026-10-20T12:00:00Z"


class TelemetrySchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "telemetry.sqlite3"
        create_database(self.path)
        self.connection = sqlite3.connect(self.path)
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA foreign_keys = ON")

    def register(self) -> None:
        self.connection.execute(
            "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
            ("account-a", "Demo A", "Test-Server", "USD", STAMP),
        )
        self.connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?)", ("source-a", "account-a", STAMP)
        )

    def message(self, sequence: str = "1", source: str = "source-a") -> None:
        self.connection.execute(
            """INSERT INTO telemetry_messages
            (source_id, session_id, sequence, captured_at_utc, received_at_utc,
             schema_version, collector_version, payload_json, content_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source, "session-a", sequence, STAMP, STAMP, "v1", "0.1", "{}", "a" * 64),
        )

    def test_schema_version_and_tables_survive_reopen(self) -> None:
        with closing(sqlite3.connect(self.path)) as reopened:
            self.assertEqual(reopened.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            tables = reopened.execute("SELECT name FROM sqlite_master WHERE type='table'")
            self.assertEqual(
                {row[0] for row in tables}, {"accounts", "sources", "telemetry_messages"}
            )

    def test_existing_database_is_not_replaced(self) -> None:
        self.register()
        self.connection.commit()
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            create_database(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_extension_and_missing_parent_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_database(self.path.with_suffix(".txt"))
        missing = self.path.parent / "absent" / "data.sqlite3"
        with self.assertRaises(FileNotFoundError):
            create_database(missing)
        self.assertFalse(missing.parent.exists())

    def test_setup_failure_is_explicit_and_keeps_reserved_file(self) -> None:
        failed = self.path.parent / "failed.sqlite3"
        with patch("tradinglab.telemetry.sqlite_store.sqlite3.connect", side_effect=sqlite3.Error):
            with self.assertRaises(TelemetryStorageError):
                create_database(failed)
        self.assertTrue(failed.exists())
        with self.assertRaises(FileExistsError):
            create_database(failed)

    def test_unknown_account_and_source_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?)", ("unknown", "missing", STAMP)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.message()

    def test_source_account_cannot_be_reassigned(self) -> None:
        self.register()
        self.connection.execute(
            "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
            ("account-b", "Demo B", "Test-Server", "USD", STAMP),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("UPDATE sources SET account_id = 'account-b'")
        self.assertEqual(
            self.connection.execute("SELECT account_id FROM sources").fetchone()[0], "account-a"
        )

    def test_duplicate_identity_and_invalid_sequences_rejected(self) -> None:
        self.register()
        self.message()
        with self.assertRaises(sqlite3.IntegrityError):
            self.message()
        for sequence in ("", "0", "01", "-1", "1.0", "x", "9223372036854775808"):
            with self.subTest(sequence=sequence), self.assertRaises(sqlite3.IntegrityError):
                self.message(sequence)
        self.message("9223372036854775807")

    def test_different_sources_do_not_collide_and_rollback_is_atomic(self) -> None:
        self.register()
        self.connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?)", ("source-b", "account-a", STAMP)
        )
        self.connection.commit()
        self.message()
        self.message(source="source-b")
        self.connection.rollback()
        self.assertEqual(
            self.connection.execute("SELECT count(*) FROM telemetry_messages").fetchone()[0], 0
        )

    def test_json_hash_and_null_constraints(self) -> None:
        self.register()
        self.message()
        for field, value in (
            ("payload_json", "bad"),
            ("content_sha256", "z" * 64),
            ("session_id", None),
        ):
            with self.subTest(field=field), self.assertRaises(sqlite3.IntegrityError):
                self.connection.execute(f"UPDATE telemetry_messages SET {field} = ?", (value,))


class TelemetryRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "registry.sqlite3"
        create_database(self.path)
        self.now = datetime(2026, 10, 20, 12, tzinfo=UTC)

    def test_register_repeat_reopen_and_preserve_original_date(self) -> None:
        with open_registry(self.path) as registry:
            self.assertTrue(
                registry.register_account("a", "Demo", "Test", "USD", created_at=self.now)
            )
            self.assertTrue(registry.register_source("source-a", "a", created_at=self.now))
        with open_registry(self.path) as registry:
            later = self.now + timedelta(days=1)
            self.assertFalse(
                registry.register_account("a", "Demo", "Test", "USD", created_at=later)
            )
            self.assertFalse(registry.register_source("source-a", "a", created_at=later))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM accounts").fetchone(), (1,))
            self.assertEqual(
                connection.execute("SELECT created_at_utc FROM sources").fetchone(),
                ("2026-10-20T12:00:00.000000Z",),
            )

    def test_conflicts_rollback_and_registry_remains_usable(self) -> None:
        with open_registry(self.path) as registry:
            registry.register_account("a", "Demo", "Test", "USD", created_at=self.now)
            registry.register_account("b", "Demo", "Test", "USD", created_at=self.now)
            registry.register_source("source-a", "a", created_at=self.now)
            with self.assertRaises(RegistrationConflictError):
                registry.register_account("a", "Changed", "Test", "USD", created_at=self.now)
            with self.assertRaises(RegistrationConflictError):
                registry.register_source("source-a", "b", created_at=self.now)
            with self.assertRaises(ValueError):
                registry.register_source("source-missing", "unknown", created_at=self.now)
            self.assertTrue(registry.register_source("source-b", "b", created_at=self.now))
            self.assertFalse(registry.register_source("source-a", "a", created_at=self.now))

    def test_invalid_inputs_leave_no_accounts(self) -> None:
        with open_registry(self.path) as registry:
            for identity, label, stamp in (
                ("bad/id", "Demo", self.now),
                ("a", " ", self.now),
                ("a", "Demo\n", self.now),
                ("a", "x" * 129, self.now),
                ("a", "Demo", self.now.replace(tzinfo=None)),
            ):
                with self.subTest(identity=identity, label=label), self.assertRaises(ValueError):
                    registry.register_account(identity, label, "Test", "USD", created_at=stamp)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM accounts").fetchone(), (0,))

    def test_missing_database_is_not_created(self) -> None:
        missing = self.path.parent / "missing.sqlite3"
        with self.assertRaises(FileNotFoundError), open_registry(missing):
            self.fail("No debe abrir una base inexistente")
        self.assertFalse(missing.exists())

    def test_rejects_future_version_without_modifying_file(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA user_version = 99")
        before = self.path.read_bytes()
        with self.assertRaises(TelemetryStorageError), open_registry(self.path):
            self.fail("No debe abrir una versión desconocida")
        self.assertEqual(self.path.read_bytes(), before)

    def test_rejects_missing_guard_even_with_correct_version(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TRIGGER sources_no_reassignment")
        with self.assertRaises(TelemetryStorageError), open_registry(self.path):
            self.fail("No debe abrir un esquema alterado")

    def test_rejects_broken_foreign_key(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("INSERT INTO sources VALUES ('s', 'missing', ?)", (STAMP,))
            connection.commit()
        with self.assertRaises(TelemetryStorageError), open_registry(self.path):
            self.fail("No debe abrir relaciones inválidas")

    def test_concurrent_registries_observe_committed_registration(self) -> None:
        with open_registry(self.path) as first, open_registry(self.path) as second:
            self.assertTrue(first.register_account("a", "Demo", "Test", "USD", created_at=self.now))
            self.assertFalse(
                second.register_account("a", "Demo", "Test", "USD", created_at=self.now)
            )
            with self.assertRaises(RegistrationConflictError):
                second.register_account("a", "Other", "Test", "USD", created_at=self.now)

    def test_context_closes_connection_after_caller_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "caller"), open_registry(self.path) as registry:
            raise RuntimeError("caller")
        with self.assertRaises(TelemetryStorageError):
            registry.register_account("a", "Demo", "Test", "USD", created_at=self.now)


if __name__ == "__main__":
    unittest.main()
