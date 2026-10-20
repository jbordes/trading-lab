from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.sqlite_store import (  # noqa: E402
    SCHEMA_VERSION,
    TelemetryStorageError,
    create_database,
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


if __name__ == "__main__":
    unittest.main()
