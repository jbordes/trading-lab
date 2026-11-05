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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from storage_fixtures import SnapshotTestPlan  # noqa: E402

from tradinglab.telemetry.backup import BackupPlan  # noqa: E402
from tradinglab.telemetry.operational_job import JobAlreadyRunningError, exclusive_job_lock  # noqa: E402
from tradinglab.telemetry.sqlite_store import open_registry  # noqa: E402


class TelemetryBackupTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 10, 20, 12, tzinfo=UTC)
        self.source = SnapshotTestPlan(
            self.root, "pilot.sqlite3", "account-demo", "Demo", "DEMO", "USD", "demo-source"
        ).apply(clock=self.now)
        self.plan = BackupPlan(self.root, "pilot.sqlite3")

    def test_online_backup_has_valid_manifest_without_touching_source(self) -> None:
        with open_registry(self.source) as registry:
            registry.register_account(
                "another-account",
                "Demo",
                "DEMO",
                "USD",
                login_masked="****1234",
                created_at=self.now,
            )
            registry.register_source("another-source", "another-account", created_at=self.now)
            before = self.source.read_bytes()
            result = self.plan.apply(clock=self.now)
            self.assertEqual(self.source.read_bytes(), before)
            registry.register_account(
                "after-account", "Demo", "DEMO", "USD", login_masked="****1234", created_at=self.now
            )
            registry.register_source("after-backup", "after-account", created_at=self.now)
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

    def test_publication_is_one_directory_rename_with_complete_verified_package(self) -> None:
        original_rename = Path.rename
        published: list[Path] = []

        def publish(temporary: Path, destination: Path) -> Path:
            self.assertTrue(temporary.name.startswith(".tmp-telemetry-"))
            self.assertFalse(destination.exists())
            self.assertEqual(
                {entry.name for entry in temporary.iterdir()}, {"data.sqlite3", "manifest.json"}
            )
            copied = (temporary / "data.sqlite3").read_bytes()
            manifest = json.loads((temporary / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha256"], hashlib.sha256(copied).hexdigest())
            self.assertEqual(manifest["size_bytes"], len(copied))
            published.append(destination)
            return original_rename(temporary, destination)

        with patch.object(Path, "rename", publish):
            result = self.plan.apply(clock=self.now)
        self.assertEqual(published, [result.directory])
        self.assertFalse(list(result.directory.parent.glob(".tmp-*")))

    def test_manifest_write_failure_leaves_only_temporary_new_package(self) -> None:
        previous = self.plan.apply(clock=self.now)
        before = {path.name: path.read_bytes() for path in previous.directory.iterdir()}
        source_before = self.source.read_bytes()

        def fail_manifest(document: object, stream: object, **_: object) -> None:
            stream.write('{"partial":')
            raise OSError("synthetic manifest failure")

        with patch("tradinglab.telemetry.backup.json.dump", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "manifest failure"):
                self.plan.apply(clock=self.now + timedelta(seconds=1))
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(
            before, {path.name: path.read_bytes() for path in previous.directory.iterdir()}
        )
        final = [
            path for path in previous.directory.parent.iterdir() if not path.name.startswith(".")
        ]
        self.assertEqual(final, [previous.directory])
        self.assertEqual(len(list(previous.directory.parent.glob(".tmp-*"))), 1)

    def test_directory_rename_failure_never_publishes_partial_package(self) -> None:
        previous = self.plan.apply(clock=self.now)
        with patch.object(Path, "rename", side_effect=OSError("synthetic rename failure")):
            with self.assertRaisesRegex(OSError, "rename failure"):
                self.plan.apply(clock=self.now + timedelta(seconds=1))
        final = [
            path for path in previous.directory.parent.iterdir() if not path.name.startswith(".")
        ]
        self.assertEqual(final, [previous.directory])
        temporary = next(previous.directory.parent.glob(".tmp-*"))
        self.assertTrue((temporary / "data.sqlite3").is_file())
        self.assertTrue((temporary / "manifest.json").is_file())

    def test_existing_package_and_even_empty_destination_are_never_replaced(self) -> None:
        previous = self.plan.apply(clock=self.now)
        original = (previous.directory / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.plan.apply(clock=self.now)
        self.assertEqual((previous.directory / "manifest.json").read_bytes(), original)
        later = self.now + timedelta(seconds=1)
        destination = previous.directory.parent / (
            f"pilot-{later.strftime('%Y%m%dT%H%M%S%fZ')}-{previous.sha256[:12]}"
        )
        destination.mkdir()
        with self.assertRaises(FileExistsError):
            self.plan.apply(clock=later)
        self.assertEqual(list(destination.iterdir()), [])

    def test_busy_publisher_leaves_prepared_package_temporary(self) -> None:
        with exclusive_job_lock(self.plan.storage / "operations" / "backup-publication.lock"):
            with self.assertRaisesRegex(RuntimeError, "paquete queda temporal") as failure:
                self.plan.apply(clock=self.now)
        self.assertNotIsInstance(failure.exception, JobAlreadyRunningError)
        backups = self.plan.storage / "backups"
        self.assertTrue(all(path.name.startswith(".tmp-") for path in backups.iterdir()))

    def test_unverified_manifest_is_not_published(self) -> None:
        with patch("tradinglab.telemetry.backup.json.loads", return_value={}):
            with self.assertRaisesRegex(ValueError, "manifest escrito"):
                self.plan.apply(clock=self.now)
        self.assertTrue(
            all(path.name.startswith(".tmp-") for path in (self.plan.storage / "backups").iterdir())
        )

    def test_file_sync_failure_prevents_publication(self) -> None:
        with (
            patch("tradinglab.telemetry.backup._sync_directory"),
            patch(
                "tradinglab.telemetry.backup.os.fsync",
                side_effect=OSError("synthetic fsync failure"),
            ),
        ):
            with self.assertRaisesRegex(OSError, "fsync failure"):
                self.plan.apply(clock=self.now)
        self.assertTrue(
            all(path.name.startswith(".tmp-") for path in (self.plan.storage / "backups").iterdir())
        )

    def test_post_publication_sync_failure_leaves_complete_not_partial_package(self) -> None:
        backups = self.plan.storage / "backups"

        def sync(path: Path) -> None:
            if path == backups:
                raise OSError("synthetic post-publication sync failure")

        with patch("tradinglab.telemetry.backup._sync_directory", side_effect=sync):
            with self.assertRaisesRegex(OSError, "post-publication"):
                self.plan.apply(clock=self.now)
        packages = list(backups.iterdir())
        self.assertEqual(len(packages), 1)
        self.assertFalse(packages[0].name.startswith(".tmp-"))
        self.assertEqual(
            {path.name for path in packages[0].iterdir()}, {"data.sqlite3", "manifest.json"}
        )

    def test_preview_and_invalid_inputs_do_not_create_backups(self) -> None:
        self.assertEqual(self.plan.source, self.source.resolve())
        self.assertFalse((self.root / "_storage" / "backups").exists())

    def test_explicit_storage_accepts_the_expected_v2_schema_only(self) -> None:
        external = self.root / "external-storage"
        external.mkdir()
        database = external / "pilot-v2.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA user_version = 4")
        plan = BackupPlan(self.root, database.name, external, (4,))
        result = plan.apply(clock=self.now)
        self.assertTrue((result.directory / "data.sqlite3").is_file())
        with self.assertRaisesRegex(ValueError, "no admitida"):
            BackupPlan(self.root, database.name, external, (1,)).apply(
                clock=self.now + timedelta(seconds=1)
            )
        with self.assertRaises(ValueError):
            BackupPlan(self.root, "../pilot.sqlite3")
        with self.assertRaises(FileNotFoundError):
            BackupPlan(self.root, "missing.sqlite3").apply()
        with self.assertRaises(ValueError):
            self.plan.apply(clock=self.now.replace(tzinfo=None))
        self.assertFalse((self.root / "_storage" / "backups").exists())


if __name__ == "__main__":
    unittest.main()
