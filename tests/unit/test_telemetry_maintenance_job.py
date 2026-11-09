from __future__ import annotations

import errno
import io
import json
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from tradinglab.telemetry.operational_job import (
    JobAlreadyRunningError,
    exclusive_job_lock,
    write_job_status,
)

ROOT = Path(__file__).resolve().parents[2]


class TelemetryMaintenanceJobTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Path(directory.name)
        # Only path validation is exercised here; backup behavior is tested separately.
        (self.storage / "central.sqlite3").write_bytes(b"synthetic-source")
        self.status = self.storage / "operations" / "maintenance-status.json"
        self.lock = self.storage / "operations" / "maintenance.lock"
        self.main = runpy.run_path(str(ROOT / "scripts/run_telemetry_maintenance.py"))["main"]
        self.stderr = io.StringIO()

    def run_job(self, *extra: str, apply: bool = True) -> int:
        args = ["--storage-root", str(self.storage), *extra]
        if apply:
            args.append("--apply")
        with redirect_stderr(self.stderr), redirect_stdout(io.StringIO()):
            return self.main(args)

    def running_status(self) -> bytes:
        write_job_status(self.status, job="telemetry-maintenance", state="running", detail="Owner")
        return self.status.read_bytes()

    def test_busy_job_keeps_owner_status_byte_for_byte_and_skips_backup(self) -> None:
        original = self.running_status()
        with (
            exclusive_job_lock(self.lock),
            patch("tradinglab.telemetry.backup.BackupPlan.apply") as backup,
        ):
            self.assertEqual(self.run_job(), 2)
            backup.assert_not_called()
            self.assertEqual(self.status.read_bytes(), original)
        self.assertIn("Omitido", self.stderr.getvalue())
        self.assertFalse(self.status.with_suffix(".json.tmp").exists())

    def test_busy_job_does_not_create_status_if_owner_has_not_written_yet(self) -> None:
        with exclusive_job_lock(self.lock):
            self.assertEqual(self.run_job(), 2)
            self.assertFalse(self.status.exists())

    def test_separate_cli_process_cannot_overwrite_active_owner_status(self) -> None:
        original = self.running_status()
        with exclusive_job_lock(self.lock):
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_telemetry_maintenance.py"),
                    "--storage-root",
                    str(self.storage),
                    "--apply",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(self.status.read_bytes(), original)

    def test_pre_lock_validation_failure_does_not_overwrite_status(self) -> None:
        original = self.running_status()
        self.assertEqual(self.run_job("--database", "../invalid.sqlite3"), 1)
        self.assertEqual(self.status.read_bytes(), original)

    def test_backup_failure_is_recorded_while_still_holding_lock(self) -> None:
        states: list[str] = []

        def record(path: Path, **values: str) -> None:
            with self.assertRaises(JobAlreadyRunningError):
                with exclusive_job_lock(self.lock):
                    self.fail("Status write without the job lock")
            states.append(values["state"])
            write_job_status(path, **values)

        with (
            patch("tradinglab.telemetry.operational_job.write_job_status", side_effect=record),
            patch(
                "tradinglab.telemetry.backup.BackupPlan.apply",
                side_effect=sqlite3.OperationalError("synthetic"),
            ),
        ):
            self.assertEqual(self.run_job(), 1)
        self.assertEqual(states, ["running", "failed"])
        self.assertEqual(json.loads(self.status.read_text())["detail"], "OperationalError")
        with exclusive_job_lock(self.lock):
            pass

    def test_success_is_recorded_and_lock_can_be_reused(self) -> None:
        with patch(
            "tradinglab.telemetry.backup.BackupPlan.apply", return_value=Mock(size_bytes=123)
        ):
            self.assertEqual(self.run_job(), 0)
        self.assertEqual(json.loads(self.status.read_text())["state"], "succeeded")
        with exclusive_job_lock(self.lock):
            pass

    def test_real_lock_io_failure_is_not_reported_as_busy_or_written_outside_lock(self) -> None:
        original = self.running_status()
        with patch(
            "tradinglab.telemetry.operational_job._lock",
            side_effect=OSError(errno.EIO, "synthetic I/O"),
        ):
            self.assertEqual(self.run_job(), 1)
        self.assertNotIn("Omitido", self.stderr.getvalue())
        self.assertEqual(self.status.read_bytes(), original)

    def test_failed_status_write_does_not_hide_original_backup_failure(self) -> None:
        with (
            patch(
                "tradinglab.telemetry.operational_job.write_job_status",
                side_effect=(None, OSError("sink failed")),
            ),
            patch(
                "tradinglab.telemetry.backup.BackupPlan.apply",
                side_effect=sqlite3.OperationalError("original failure"),
            ),
        ):
            self.assertEqual(self.run_job(), 1)
        self.assertIn("original failure", self.stderr.getvalue())
        self.assertNotIn("sink failed", self.stderr.getvalue())

    def test_preview_does_not_acquire_lock_or_change_status(self) -> None:
        original = self.running_status()
        with patch("tradinglab.telemetry.operational_job.exclusive_job_lock") as lock:
            self.assertEqual(self.run_job(apply=False), 0)
            lock.assert_not_called()
        self.assertEqual(self.status.read_bytes(), original)

    def test_daily_work_runs_only_after_verified_backup(self) -> None:
        calls = []
        outcome = {
            "state": "succeeded",
            "consolidated_days": 1,
            "compacted_messages": 2,
            "reason": None,
        }

        def backup():
            calls.append("backup")
            return Mock(size_bytes=123)

        def daily(*args, **kwargs):
            calls.append("daily")
            self.assertTrue(kwargs["apply"])
            return outcome

        with (
            patch("tradinglab.telemetry.backup.BackupPlan.apply", side_effect=backup),
            patch(
                "tradinglab.telemetry.daily_account_maintenance.run_daily_account_maintenance",
                side_effect=daily,
            ),
        ):
            self.assertEqual(self.run_job("--daily-account-id", "test-account"), 0)
        self.assertEqual(calls, ["backup", "daily"])

    def test_failed_backup_prevents_any_daily_work(self) -> None:
        with (
            patch(
                "tradinglab.telemetry.backup.BackupPlan.apply",
                side_effect=RuntimeError("backup failed"),
            ),
            patch(
                "tradinglab.telemetry.daily_account_maintenance.run_daily_account_maintenance"
            ) as daily,
        ):
            self.assertEqual(self.run_job("--daily-account-id", "test-account"), 1)
        daily.assert_not_called()

    def test_partial_daily_job_is_visible_and_does_not_retry_automatically(self) -> None:
        outcome = {
            "state": "partial",
            "consolidated_days": 1,
            "compacted_messages": 2,
            "reason": "work_limit",
        }
        with (
            patch(
                "tradinglab.telemetry.backup.BackupPlan.apply", return_value=Mock(size_bytes=123)
            ),
            patch(
                "tradinglab.telemetry.daily_account_maintenance.run_daily_account_maintenance",
                return_value=outcome,
            ) as daily,
        ):
            self.assertEqual(self.run_job("--daily-account-id", "test-account"), 3)
        daily.assert_called_once()
        self.assertEqual(json.loads(self.status.read_text())["state"], "partial")

    def test_daily_preview_neither_takes_lock_nor_creates_backup(self) -> None:
        with (
            patch("tradinglab.telemetry.backup.BackupPlan.apply") as backup,
            patch(
                "tradinglab.telemetry.daily_account_maintenance.run_daily_account_maintenance",
                return_value={"state": "preview"},
            ) as daily,
        ):
            self.assertEqual(self.run_job("--daily-account-id", "test-account", apply=False), 0)
        backup.assert_not_called()
        self.assertNotIn("apply", daily.call_args.kwargs)
        self.assertFalse(self.status.exists())


if __name__ == "__main__":
    unittest.main()
