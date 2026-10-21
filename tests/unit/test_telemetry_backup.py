from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.backup import BackupPlan  # noqa: E402
from tradinglab.telemetry.provisioning import ProvisionPlan  # noqa: E402
from tradinglab.telemetry.sqlite_store import open_registry  # noqa: E402


class TelemetryBackupTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 10, 20, 12, tzinfo=UTC)
        self.source = ProvisionPlan(
            self.root, "pilot.sqlite3", "account-demo", "Demo", "DEMO", "USD", "demo-source"
        ).apply(clock=self.now)
        self.plan = BackupPlan(self.root, "pilot.sqlite3")

    def test_online_backup_has_valid_manifest_without_touching_source(self) -> None:
        with open_registry(self.source) as registry:
            registry.register_source("another-source", "account-demo", created_at=self.now)
            before = self.source.read_bytes()
            result = self.plan.apply(clock=self.now)
            self.assertEqual(self.source.read_bytes(), before)
            registry.register_source("after-backup", "account-demo", created_at=self.now)
        copied = result.directory / "data.sqlite3"
        manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sha256"], hashlib.sha256(copied.read_bytes()).hexdigest())
        self.assertEqual(
            (manifest["size_bytes"], manifest["sha256"]), (result.size_bytes, result.sha256)
        )
        self.assertEqual(manifest["source_file"], "pilot.sqlite3")
        with closing(sqlite3.connect(copied)) as connection:
            sources = {row[0] for row in connection.execute("SELECT source_id FROM sources")}
            self.assertEqual(sources, {"demo-source", "another-source"})
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchall(), [("ok",)])

    def test_new_copy_does_not_remove_or_replace_previous_copy(self) -> None:
        first = self.plan.apply(clock=self.now)
        first_hash = first.sha256
        second = self.plan.apply(clock=self.now + timedelta(seconds=1))
        self.assertNotEqual(first.directory, second.directory)
        self.assertTrue(first.directory.is_dir())
        self.assertTrue(second.directory.is_dir())
        self.assertEqual(first.sha256, first_hash)

    def test_preview_and_invalid_inputs_do_not_create_backups(self) -> None:
        self.assertEqual(self.plan.source, self.source)
        self.assertFalse((self.root / "_storage" / "backups").exists())
        with self.assertRaises(ValueError):
            BackupPlan(self.root, "../pilot.sqlite3")
        with self.assertRaises(FileNotFoundError):
            BackupPlan(self.root, "missing.sqlite3").apply()
        with self.assertRaises(ValueError):
            self.plan.apply(clock=self.now.replace(tzinfo=None))
        self.assertFalse((self.root / "_storage" / "backups").exists())


if __name__ == "__main__":
    unittest.main()
