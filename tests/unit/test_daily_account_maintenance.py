from __future__ import annotations

import io
import runpy
import sqlite3
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import test_daily_account_store as daily_fixture
from test_mt5_telemetry import encoded, snapshot_message

from tradinglab.telemetry.daily_account_maintenance import run_daily_account_maintenance
from tradinglab.telemetry.sqlite_store import open_registry


class DailyAccountMaintenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        daily_fixture.DailyAccountStoreTest.setUp(self)
        self.now = datetime(2026, 10, 25, 12, tzinfo=UTC)

    def put(self, sequence: int, day: int, hour: int, *, minute: int = 0, marker=True) -> None:
        message = snapshot_message(sequence=sequence)
        captured = datetime(2026, 10, day, hour, minute, tzinfo=UTC)
        message["captured_at"] = captured.isoformat().replace("+00:00", "Z")
        message["payload"]["account"]["balance"] = 100 + sequence
        if marker:
            message["payload"]["server_time_msc"] = str(int(captured.timestamp() * 1000) + 7200000)
        with open_registry(self.path) as registry:
            registry.store_message(encoded(message), received_at=captured)

    def seed(self) -> None:
        self.put(1, 15, 8)
        self.put(2, 15, 21)
        self.put(3, 25, 12)

    def run_job(self, **options):
        return run_daily_account_maintenance(self.path, "test-account", now=self.now, **options)

    def test_preview_is_read_only_and_real_run_is_idempotent_without_servers(self) -> None:
        self.seed()
        preview = self.run_job()
        self.assertEqual(preview["days"], ["2026-10-15"])
        self.assertEqual(preview["state"], "preview")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM account_daily_observations").fetchone()[0], 0
            )
        result = self.run_job(apply=True)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual((result["consolidated_days"], result["compacted_messages"]), (1, 1))
        repeat = self.run_job(apply=True)
        self.assertEqual((repeat["consolidated_days"], repeat["compacted_messages"]), (0, 0))

    def test_late_capture_updates_revision_even_if_close_does_not_change(self) -> None:
        self.seed()
        self.run_job(apply=True)
        self.put(4, 15, 10)
        result = self.run_job(apply=True)
        self.assertEqual(result["consolidated_days"], 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT balance, max_balance, last_processed_message_id FROM account_daily_observations"
                ).fetchone(),
                ("102", "104", 4),
            )
        self.assertEqual(self.run_job(apply=True)["consolidated_days"], 0)

    def test_missing_broker_reference_defers_without_modifying_data(self) -> None:
        self.put(1, 15, 8, marker=False)
        result = self.run_job(apply=True)
        self.assertEqual(result["state"], "deferred")
        self.assertEqual(result["reason"], "broker_clock_unavailable")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM account_daily_observations").fetchone()[0], 0
            )

    def test_stale_reference_processes_only_proven_closed_days(self) -> None:
        self.seed()
        result = run_daily_account_maintenance(
            self.path,
            "test-account",
            apply=True,
            now=self.now + timedelta(days=30),
        )
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["reason"], "stale_broker_clock")
        self.assertEqual(result["broker_day"], "2026-10-25")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT broker_day FROM account_daily_observations").fetchall(),
                [("2026-10-15",)],
            )

    def test_five_minute_grace_does_not_close_current_day_prematurely(self) -> None:
        self.put(1, 24, 8)
        self.put(2, 24, 22, minute=3)  # Broker Oct 25 00:03.
        self.now = datetime(2026, 10, 24, 22, 3, tzinfo=UTC)
        self.assertEqual(self.run_job(apply=True)["consolidated_days"], 0)
        self.put(3, 24, 22, minute=6)
        self.now += timedelta(minutes=3)
        self.assertEqual(self.run_job(apply=True)["consolidated_days"], 1)

    def test_day_limit_makes_progress_and_leaves_explicit_pending_work(self) -> None:
        for sequence, day in enumerate((1, 2, 3, 25), 1):
            self.put(sequence, day, 12)
        self.assertEqual(self.run_job(apply=True, max_days=1)["state"], "partial")
        self.assertEqual(self.run_job(apply=True, max_days=1)["days"], ["2026-10-02"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM account_daily_observations").fetchone()[0], 2
            )

    def test_budget_exhaustion_never_becomes_a_retry_loop(self) -> None:
        self.seed()
        clock = iter((0.0, 61.0))
        result = self.run_job(apply=True, timer=lambda: next(clock))
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["reason"], "budget_exhausted")
        self.assertEqual(result["consolidated_days"], 0)

    def test_batch_limit_is_global_and_bounded(self) -> None:
        self.seed()
        with patch(
            "tradinglab.telemetry.daily_account_maintenance.compact_account_samples",
            return_value={"compacted": 1000, "more_pending": True},
        ) as compact:
            result = self.run_job(apply=True, max_batches=2)
        self.assertEqual(compact.call_count, 2)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["reason"], "work_limit")

    def test_invalid_configuration_is_rejected(self) -> None:
        for options in (
            {"max_days": 0},
            {"max_batches": True},
            {"budget_seconds": float("nan")},
            {"now": datetime(2026, 10, 25)},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                run_daily_account_maintenance(self.path, "test-account", **options)

    def test_real_cli_backs_up_uncompacted_data_before_offline_maintenance(self) -> None:
        self.seed()
        root = Path(__file__).resolve().parents[2]
        main = runpy.run_path(str(root / "scripts/run_telemetry_maintenance.py"))["main"]

        def frozen_daily(*args, **kwargs):
            return run_daily_account_maintenance(*args, now=self.now + timedelta(days=30), **kwargs)

        with (
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            patch(
                "tradinglab.telemetry.daily_account_maintenance.run_daily_account_maintenance",
                side_effect=frozen_daily,
            ),
        ):
            # Only the clock is fixed; backup and all database operations are real.
            code = main(
                [
                    "--storage-root",
                    str(self.path.parent),
                    "--database",
                    self.path.name,
                    "--daily-account-id",
                    "test-account",
                    "--apply",
                ]
            )
        self.assertEqual(code, 3)
        backups = list((self.path.parent / "backups").glob("*/data.sqlite3"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM telemetry_messages WHERE compacted_broker_day IS NOT NULL"
                ).fetchone()[0],
                0,
            )
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM telemetry_messages WHERE compacted_broker_day IS NOT NULL"
                ).fetchone()[0],
                1,
            )
