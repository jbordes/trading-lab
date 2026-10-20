from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from test_mt5_telemetry import encoded, snapshot_message

from tradinglab.telemetry.contract import TelemetryValidationError, parse_envelope
from tradinglab.telemetry.persisted_view import PersistedSnapshotView
from tradinglab.telemetry.sqlite_store import (
    MessageAdmissionError,
    MessageConflictError,
    TelemetryRegistry,
    TelemetryStorageError,
    create_database,
    open_registry,
)


class FailingCommitConnection(sqlite3.Connection):
    """Inject failure before commit or an ambiguous result after durable commit."""

    after_commit = False

    def __exit__(self, *args: object) -> None:
        if self.after_commit:
            super().__exit__(*args)
        else:
            self.rollback()
        raise sqlite3.OperationalError("injected commit failure")


class StoredMessagesTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "messages.sqlite3"
        create_database(self.path)
        self.now = datetime(2026, 10, 20, 12, tzinfo=UTC)
        with open_registry(self.path) as registry:
            registry.register_account("a", "Demo", "DEMO-SERVER", "USD", created_at=self.now)
            for source in ("demo-terminal-01", "other-source"):
                registry.register_source(source, "a", created_at=self.now)

    def rows(self) -> list[tuple]:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                "SELECT payload_json, content_sha256, received_at_utc FROM telemetry_messages"
            ).fetchall()

    def test_round_trip_hash_and_retry_after_reopen(self) -> None:
        message = snapshot_message()
        with open_registry(self.path) as registry:
            first = registry.store_message(encoded(message), received_at=self.now)
        with open_registry(self.path) as registry:
            repeat = registry.store_message(
                json.dumps(message, indent=4).encode(), received_at=self.now + timedelta(days=1)
            )
        self.assertFalse(first.duplicate)
        self.assertTrue(repeat.duplicate)
        self.assertEqual(first.message_id, repeat.message_id)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][0]), message)
        canonical = parse_envelope(encoded(message)).canonical_bytes()
        self.assertEqual(rows[0][1], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(rows[0][2], "2026-10-20T12:00:00.000000Z")

    def test_conflict_preserves_original_and_allows_next_message(self) -> None:
        message = snapshot_message()
        with open_registry(self.path) as registry:
            registry.store_message(encoded(message), received_at=self.now)
            message["payload"]["account"]["balance"] = 1.0
            with self.assertRaises(MessageConflictError):
                registry.store_message(encoded(message), received_at=self.now)
            registry.store_message(encoded(snapshot_message(sequence=2)), received_at=self.now)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(json.loads(self.rows()[0][0])["payload"]["account"]["balance"], 100000.0)

    def test_rejects_unregistered_source_and_mismatched_metadata(self) -> None:
        with open_registry(self.path) as registry:
            for field, value in (("server", "OTHER"), ("currency", "EUR")):
                message = snapshot_message()
                message["payload"]["account"][field] = value
                with self.assertRaises(MessageAdmissionError):
                    registry.store_message(encoded(message), received_at=self.now)
            with self.assertRaises(MessageAdmissionError):
                registry.store_message(
                    encoded(snapshot_message(source_id="unknown")), received_at=self.now
                )
        self.assertEqual(self.rows(), [])

    def test_invalid_contract_and_naive_time_do_not_write(self) -> None:
        with open_registry(self.path) as registry:
            with self.assertRaises(TelemetryValidationError):
                registry.store_message(b"{}", received_at=self.now)
            with self.assertRaises(ValueError):
                registry.store_message(
                    encoded(snapshot_message()), received_at=self.now.replace(tzinfo=None)
                )
        self.assertEqual(self.rows(), [])

    def test_numeric_sequence_gaps_old_retry_and_unknown_old_sequence(self) -> None:
        with open_registry(self.path) as registry:
            for sequence, gap in ((1, False), (9, True), (10, False), (2**63 - 1, True)):
                result = registry.store_message(
                    encoded(snapshot_message(sequence=sequence)), received_at=self.now
                )
                self.assertEqual(result.sequence_gap, gap)
            self.assertTrue(
                registry.store_message(encoded(snapshot_message()), received_at=self.now).duplicate
            )
            with self.assertRaises(MessageAdmissionError):
                registry.store_message(encoded(snapshot_message(sequence=2)), received_at=self.now)

    def test_sources_and_sessions_have_separate_sequences(self) -> None:
        with open_registry(self.path) as registry:
            registry.store_message(encoded(snapshot_message()), received_at=self.now)
            other = snapshot_message(source_id="other-source")
            registry.store_message(encoded(other), received_at=self.now)
            other["session_id"] = "new-session"
            registry.store_message(encoded(other), received_at=self.now)
        self.assertEqual(len(self.rows()), 3)

    def test_heartbeat_is_stored_without_claiming_account_capture(self) -> None:
        message = snapshot_message()
        message.update(kind="heartbeat", payload={"status": "ok"})
        with open_registry(self.path) as registry:
            registry.store_message(encoded(message), received_at=self.now)
        self.assertEqual(json.loads(self.rows()[0][0])["kind"], "heartbeat")

    def test_restore_latest_capture_after_reopen_skips_heartbeat_and_late_queue(self) -> None:
        older = snapshot_message(sequence=1)
        newer = snapshot_message(sequence=2)
        newer["captured_at"] = "2026-10-20T11:00:00Z"
        newer["payload"]["account"]["balance"] = 200.0
        delayed = snapshot_message(sequence=3)
        delayed["captured_at"] = "2026-10-15T20:00:00Z"
        delayed["payload"]["account"]["balance"] = 300.0
        heartbeat = snapshot_message(sequence=4)
        heartbeat.update(kind="heartbeat", payload={"status": "ok"})
        heartbeat["captured_at"] = "2026-10-20T12:00:00Z"
        with open_registry(self.path) as registry:
            for message, received in (
                (older, self.now),
                (newer, self.now),
                (delayed, self.now + timedelta(seconds=30)),
                (heartbeat, self.now + timedelta(seconds=40)),
            ):
                registry.store_message(encoded(message), received_at=received)
        with open_registry(self.path) as registry:
            restored = registry.latest_account_snapshot("demo-terminal-01")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.envelope.sequence, 2)
        self.assertEqual(restored.envelope.payload["account"]["balance"], 200.0)
        self.assertEqual(restored.envelope.captured_at, "2026-10-20T11:00:00Z")
        self.assertEqual(restored.received_at, self.now)

    def test_restore_empty_and_isolated_source(self) -> None:
        with open_registry(self.path) as registry:
            self.assertIsNone(registry.latest_account_snapshot("demo-terminal-01"))
            with self.assertRaises(MessageAdmissionError):
                registry.latest_account_snapshot("unknown")
            registry.store_message(encoded(snapshot_message()), received_at=self.now)
            self.assertIsNone(registry.latest_account_snapshot("other-source"))

    def test_restore_detects_tampered_content_and_columns(self) -> None:
        with open_registry(self.path) as registry:
            registry.store_message(encoded(snapshot_message()), received_at=self.now)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE telemetry_messages SET received_at_utc = ?",
                ("2026-10-20T12:00:00X",),
            )
            connection.commit()
        with open_registry(self.path) as registry:
            with self.assertRaises(TelemetryStorageError):
                registry.latest_account_snapshot("demo-terminal-01")
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE telemetry_messages SET received_at_utc = ?, content_sha256 = ?",
                ("2026-10-20T12:00:00.000000Z", "0" * 64),
            )
            connection.commit()
        with open_registry(self.path) as registry:
            with self.assertRaises(TelemetryStorageError):
                registry.latest_account_snapshot("demo-terminal-01")

    def test_view_restores_history_and_does_not_refresh_time_on_replay(self) -> None:
        first = snapshot_message()
        with open_registry(self.path) as registry:
            view = PersistedSnapshotView(registry, source_id="demo-terminal-01")
            self.assertIsNone(view.snapshot())
            view.store_message(encoded(first), received_at=self.now)
            original = view.snapshot()
            self.assertEqual(original.received_at, self.now)
            original.envelope.payload["account"]["balance"] = 0.0
            replay = view.store_message(encoded(first), received_at=self.now + timedelta(hours=2))
            self.assertTrue(replay.duplicate)
            self.assertEqual(view.snapshot().received_at, self.now)
            self.assertEqual(view.snapshot().envelope.payload["account"]["balance"], 100000.0)
        with open_registry(self.path) as registry:
            restarted = PersistedSnapshotView(registry, source_id="demo-terminal-01")
            self.assertEqual(restarted.snapshot().received_at, self.now)
            self.assertEqual(restarted.snapshot().envelope.captured_at, first["captured_at"])

    def test_view_keeps_latest_capture_when_heartbeat_or_old_queue_arrives(self) -> None:
        newest = snapshot_message()
        newest["captured_at"] = "2026-10-20T11:00:00Z"
        delayed = snapshot_message(sequence=2)
        delayed["captured_at"] = "2026-10-15T20:00:00Z"
        heartbeat = snapshot_message(sequence=3)
        heartbeat.update(kind="heartbeat", payload={"status": "ok"})
        with open_registry(self.path) as registry:
            view = PersistedSnapshotView(registry, source_id="demo-terminal-01")
            view.store_message(encoded(newest), received_at=self.now)
            view.store_message(encoded(delayed), received_at=self.now + timedelta(minutes=1))
            view.store_message(encoded(heartbeat), received_at=self.now + timedelta(minutes=2))
            self.assertEqual(view.snapshot().envelope.sequence, 1)
            self.assertEqual(view.snapshot().received_at, self.now)

    def test_view_is_source_scoped_and_can_refresh_external_commit(self) -> None:
        with open_registry(self.path) as registry:
            view = PersistedSnapshotView(registry, source_id="demo-terminal-01")
            with self.assertRaises(MessageAdmissionError):
                view.store_message(
                    encoded(snapshot_message(source_id="other-source")), received_at=self.now
                )
            registry.store_message(encoded(snapshot_message()), received_at=self.now)
            self.assertIsNone(view.snapshot())
            view.refresh()
            self.assertEqual(view.snapshot().envelope.source_id, "demo-terminal-01")
            other = PersistedSnapshotView(registry, source_id="other-source")
            self.assertIsNone(other.snapshot())

    def test_refresh_failure_after_commit_requires_retry_before_read(self) -> None:
        with open_registry(self.path) as registry:
            view = PersistedSnapshotView(registry, source_id="demo-terminal-01")
            original = registry.latest_account_snapshot
            with patch.object(
                registry, "latest_account_snapshot", side_effect=TelemetryStorageError
            ):
                with self.assertRaises(TelemetryStorageError):
                    view.store_message(encoded(snapshot_message()), received_at=self.now)
            with self.assertRaises(TelemetryStorageError):
                view.snapshot()
            self.assertEqual(len(self.rows()), 1)
            self.assertIsNotNone(original("demo-terminal-01"))
            retry = view.store_message(encoded(snapshot_message()), received_at=self.now)
            self.assertTrue(retry.duplicate)
            self.assertEqual(view.snapshot().envelope.sequence, 1)

    def test_failure_before_commit_then_retry_inserts_once(self) -> None:
        self.check_commit_failure(after_commit=False)

    def test_concurrent_identical_requests_insert_once(self) -> None:
        barrier = threading.Barrier(2, timeout=5)

        def send() -> bool:
            with open_registry(self.path) as registry:
                barrier.wait()
                return registry.store_message(
                    encoded(snapshot_message()), received_at=self.now
                ).duplicate

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(send) for _ in range(2)]
            self.assertEqual(sorted(future.result(timeout=10) for future in futures), [False, True])
        self.assertEqual(len(self.rows()), 1)

    def test_failure_after_commit_then_retry_is_duplicate(self) -> None:
        self.check_commit_failure(after_commit=True)

    def check_commit_failure(self, *, after_commit: bool) -> None:
        with closing(sqlite3.connect(self.path, factory=FailingCommitConnection)) as connection:
            connection.after_commit = after_commit
            connection.execute("PRAGMA foreign_keys = ON")
            registry = TelemetryRegistry(connection)
            with self.assertRaises(TelemetryStorageError):
                registry.store_message(encoded(snapshot_message()), received_at=self.now)
        self.assertEqual(len(self.rows()), int(after_commit))
        with open_registry(self.path) as registry:
            retry = registry.store_message(encoded(snapshot_message()), received_at=self.now)
        self.assertEqual(retry.duplicate, after_commit)
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()
