from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from storage_fixtures import TradingTestPlan

from tradinglab.telemetry.admission_v2 import ProducerIdentity
from tradinglab.telemetry.persistent_receiver_v2 import PersistentV2TelemetryReceiver
from tradinglab.telemetry.sqlite_store_v2 import (
    V2ActivityPage,
    V2CoverageReport,
    V2StorageError,
    V2TelemetryRegistry,
    open_v2_history_reader,
)

FIXTURES = Path(__file__).parents[1] / "fixtures/telemetry_v2"
LIVE_KEY = "synthetic-live-credential-safe-length"
ACTIVITY_KEY = "synthetic-activity-credential-safe-length"
FROM_MSC = 1792656000000
TO_MSC = 1792656060001


def message(name: str, sequence: int = 1) -> bytes:
    value = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    value["sequence"] = sequence
    value["event_id"] = f"{value['session_id']}:{sequence}"
    return json.dumps(value).encode()


class TradingHistoryReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = TradingTestPlan(
            Path(temporary.name),
            "central.sqlite3",
            "account-demo",
            "Demo",
            ProducerIdentity("****1234", "DEMO-SERVER", "USD"),
            "synthetic-live",
            "synthetic-activity",
        ).apply()
        self.receiver = PersistentV2TelemetryReceiver(
            self.database,
            account_id="account-demo",
            live_authorization=LIVE_KEY,
            activity_authorization=ACTIVITY_KEY,
            clock=lambda: datetime(2026, 10, 25, tzinfo=UTC),
        )
        self.addCleanup(self.receiver.close)

    def activity(self) -> tuple[V2ActivityPage, V2CoverageReport]:
        return self.receiver.activity_history("order", from_msc=FROM_MSC, to_msc=TO_MSC)

    def test_page_and_coverage_share_snapshot_while_ingestion_and_health_proceed(self) -> None:
        selected = threading.Event()
        release = threading.Event()
        original = V2TelemetryRegistry.activity_page

        def blocked(registry, *args, **kwargs):
            page = original(registry, *args, **kwargs)
            selected.set()
            if not release.wait(5):
                raise AssertionError("Reader was not released")
            return page

        with patch.object(V2TelemetryRegistry, "activity_page", blocked):
            with ThreadPoolExecutor(max_workers=2) as workers:
                reading = workers.submit(self.activity)
                try:
                    self.assertTrue(selected.wait(3))

                    def ingest_and_health() -> dict[str, int | str]:
                        self.receiver.accept(
                            message("activity-canceled-order"), f"Bearer {ACTIVITY_KEY}"
                        )
                        return self.receiver.state()

                    self.assertEqual(workers.submit(ingest_and_health).result(3)["accepted"], 1)
                finally:
                    release.set()
                page, coverage = reading.result(3)
        self.assertEqual(page.items, ())
        self.assertEqual(coverage.complete_ranges, ())
        page, coverage = self.activity()
        self.assertEqual(len(page.items), 1)
        self.assertEqual(len(coverage.complete_ranges), 1)

    def test_other_read_routes_do_not_hold_writer_lock(self) -> None:
        routes = (
            ("position_cycles", self.receiver.position_cycles),
            ("latest_activity_progress", self.receiver.activity_progress),
            ("position_cycle_magics", self.receiver.position_cycle_magics),
        )
        for sequence, (method, read) in enumerate(routes, 1):
            with self.subTest(route=method):
                selected, release = threading.Event(), threading.Event()
                original = getattr(V2TelemetryRegistry, method)

                def blocked(
                    registry, *args, original=original, selected=selected, release=release, **kwargs
                ):
                    result = original(registry, *args, **kwargs)
                    selected.set()
                    if not release.wait(5):
                        raise AssertionError("Reader was not released")
                    return result

                with patch.object(V2TelemetryRegistry, method, blocked):
                    with ThreadPoolExecutor(max_workers=2) as workers:
                        reading = workers.submit(read)
                        try:
                            self.assertTrue(selected.wait(3))
                            stored = workers.submit(
                                self.receiver.accept,
                                message("live-empty", sequence),
                                f"Bearer {LIVE_KEY}",
                            ).result(3)
                            self.assertGreater(stored.message_id, 0)
                        finally:
                            release.set()
                        reading.result(3)

    def test_reader_admission_is_bounded_and_released_after_success(self) -> None:
        ready = threading.Barrier(3)
        release = threading.Event()
        original = V2TelemetryRegistry.position_cycles

        def blocked(registry, *args, **kwargs):
            result = original(registry, *args, **kwargs)
            ready.wait(3)
            if not release.wait(5):
                raise AssertionError("Readers were not released")
            return result

        with patch.object(V2TelemetryRegistry, "position_cycles", blocked):
            with ThreadPoolExecutor(max_workers=2) as workers:
                readers = [workers.submit(self.receiver.position_cycles) for _ in range(2)]
                try:
                    ready.wait(3)
                    with self.assertRaises(V2StorageError):
                        self.receiver.activity_progress()
                    self.assertEqual(self.receiver.state()["status"], "ready")
                finally:
                    release.set()
                for reader in readers:
                    reader.result(3)
        self.assertIsNone(self.receiver.activity_progress())

    def test_reader_errors_release_admission(self) -> None:
        for _ in range(3):
            with self.assertRaises(ValueError):
                self.receiver.activity_history("invalid", from_msc=FROM_MSC, to_msc=TO_MSC)
        with patch(
            "tradinglab.telemetry.persistent_receiver_v2.open_v2_history_reader",
            side_effect=V2StorageError("Synthetic open failure"),
        ):
            for _ in range(3):
                with self.assertRaises(V2StorageError):
                    self.receiver.activity_progress()
        self.assertIsNone(self.receiver.activity_progress())

    def test_close_does_not_invalidate_an_admitted_reader(self) -> None:
        selected, release = threading.Event(), threading.Event()
        original = V2TelemetryRegistry.activity_page

        def blocked(registry, *args, **kwargs):
            result = original(registry, *args, **kwargs)
            selected.set()
            if not release.wait(5):
                raise AssertionError("Reader was not released")
            return result

        with patch.object(V2TelemetryRegistry, "activity_page", blocked):
            with ThreadPoolExecutor(max_workers=2) as workers:
                reading = workers.submit(self.activity)
                try:
                    self.assertTrue(selected.wait(3))
                    workers.submit(self.receiver.close).result(3)
                    with self.assertRaises(V2StorageError):
                        self.receiver.activity_progress()
                finally:
                    release.set()
                self.assertEqual(reading.result(3)[0].items, ())

    def test_reader_enforces_read_only_sql_deadline_and_closes_connection(self) -> None:
        connect = sqlite3.connect
        connections: list[sqlite3.Connection] = []

        def tracked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            if args[0] != ":memory:":
                connections.append(connection)
            return connection

        with (
            patch("tradinglab.telemetry.sqlite_store_v2.sqlite3.connect", tracked_connect),
            patch("tradinglab.telemetry.sqlite_store_v2.time.monotonic", return_value=0) as clock,
        ):
            with self.assertRaises(V2StorageError) as raised:
                with open_v2_history_reader(self.database):
                    connection = connections[-1]
                    with self.assertRaises(sqlite3.OperationalError):
                        connection.execute("UPDATE accounts SET label = 'Not permitted'")
                    clock.return_value = 3
                    connection.execute(
                        """WITH RECURSIVE numbers(n) AS (
                        SELECT 1 UNION ALL SELECT n+1 FROM numbers WHERE n<10000
                        ) SELECT sum(n) FROM numbers"""
                    ).fetchone()
            self.assertIsInstance(raised.exception.__cause__, sqlite3.OperationalError)
            self.assertEqual(raised.exception.__cause__.sqlite_errorcode, sqlite3.SQLITE_INTERRUPT)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[-1].execute("SELECT 1")
        self.assertIsNone(self.receiver.activity_progress())

    def test_reader_checks_deadline_after_python_processing(self) -> None:
        with patch("tradinglab.telemetry.sqlite_store_v2.time.monotonic", return_value=0) as clock:
            with self.assertRaises(V2StorageError):
                with open_v2_history_reader(self.database):
                    clock.return_value = 3

    def test_reader_rejects_invalid_deadlines(self) -> None:
        for timeout in (True, 0, -1, 31, float("nan"), float("inf"), "2"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                with open_v2_history_reader(self.database, timeout_seconds=timeout):
                    self.fail("Invalid deadline must be rejected")
