from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.provisioning_v2 import V2ProvisionPlan
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry


class V2ProvisioningTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.identity = ProducerIdentity("****1234", "DEMO-SERVER", "USD")
        self.plan = V2ProvisionPlan(
            self.root,
            "pilot-v2.sqlite3",
            "account-demo",
            "Demo",
            self.identity,
            "demo-live-01",
            "demo-activity-01",
        )
        self.now = datetime(2026, 10, 25, 10, tzinfo=UTC)

    def test_preview_is_pure_and_apply_registers_both_roles(self) -> None:
        self.assertEqual(self.plan.database, self.root.resolve() / "_storage/pilot-v2.sqlite3")
        self.assertFalse((self.root / "_storage").exists())
        database = self.plan.apply(clock=self.now)
        with open_v2_registry(database) as registry:
            evidence = registry.account_evidence("account-demo")
        self.assertEqual(evidence.identity, self.identity)
        self.assertEqual(
            {(source.source_id, source.role) for source in evidence.sources},
            {
                ("demo-live-01", ProducerRole.LIVE),
                ("demo-activity-01", ProducerRole.ACTIVITY),
            },
        )
        self.assertEqual(evidence.messages, ())

    def test_existing_database_is_untouched(self) -> None:
        database = self.plan.apply(clock=self.now)
        before = database.read_bytes()
        with self.assertRaises(FileExistsError):
            self.plan.apply(clock=self.now)
        self.assertEqual(database.read_bytes(), before)

    def test_external_storage_creates_empty_schema_five_without_checkout_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            from dataclasses import replace

            plan = replace(self.plan, storage_root=Path(directory).resolve())
            self.assertEqual(plan.database.parent, Path(directory).resolve())
            self.assertFalse(plan.database.exists())
            database = plan.apply(clock=self.now)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            with open_v2_registry(database, read_only=True) as registry:
                self.assertEqual(registry.account_evidence("account-demo").messages, ())
            self.assertFalse((self.root / "_storage").exists())

    def test_external_storage_rejects_relative_or_missing_directory(self) -> None:
        from dataclasses import replace

        for directory in (Path("relative"), self.root / "missing"):
            with self.subTest(directory=directory), self.assertRaises((ValueError, OSError)):
                replace(self.plan, storage_root=directory).apply(clock=self.now)
        self.assertFalse((self.root / "missing").exists())

    def test_create_race_never_deletes_file_not_created_by_plan(self) -> None:
        def concurrent_create(source: Path, destination: Path) -> None:
            destination.write_bytes(b"external")
            raise FileExistsError("concurrent file")

        with (
            patch(
                "tradinglab.telemetry.provisioning_v2.os.link",
                side_effect=concurrent_create,
            ),
            self.assertRaises(FileExistsError),
        ):
            self.plan.apply(clock=self.now)
        self.assertEqual(self.plan.database.read_bytes(), b"external")
        self.assertEqual(list(self.plan.database.parent.iterdir()), [self.plan.database])

    def test_partial_creation_or_registration_or_verification_failure_allows_retry(self) -> None:
        def broken_schema(path: Path) -> None:
            path.write_bytes(b"partial")
            raise OSError("simulated creation failure")

        faults = (
            ("tradinglab.telemetry.provisioning_v2.create_v2_database", broken_schema),
            ("tradinglab.telemetry.provisioning_v2.os.link", OSError("publication unavailable")),
            (
                "tradinglab.telemetry.sqlite_store_v2.V2TelemetryRegistry.register_source",
                RuntimeError("simulated registration failure"),
            ),
            (
                "tradinglab.telemetry.sqlite_store_v2.V2TelemetryRegistry.account_evidence",
                RuntimeError("simulated verification failure"),
            ),
        )
        for target, failure in faults:
            with self.subTest(target=target):
                with patch(target, side_effect=failure), self.assertRaises((OSError, RuntimeError)):
                    self.plan.apply(clock=self.now)
                self.assertFalse(self.plan.database.exists())
                self.assertEqual(list(self.plan.database.parent.iterdir()), [])
        self.plan.apply(clock=self.now)

    def test_concurrent_creators_publish_exactly_one_complete_database(self) -> None:
        def create() -> str:
            try:
                self.plan.apply(clock=self.now)
                return "created"
            except FileExistsError:
                return "exists"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: create(), range(2)))
        self.assertCountEqual(outcomes, ["created", "exists"])
        with open_v2_registry(self.plan.database, read_only=True) as registry:
            self.assertEqual(len(registry.account_evidence("account-demo").sources), 2)

    def test_abrupt_exit_does_not_publish_incomplete_database_or_block_retry(self) -> None:
        code = """
import os
import sys
from pathlib import Path
from tradinglab.telemetry.admission_v2 import ProducerIdentity
from tradinglab.telemetry.provisioning_v2 import V2ProvisionPlan
from tradinglab.telemetry.sqlite_store_v2 import V2TelemetryRegistry
V2TelemetryRegistry.register_source = lambda *a, **kw: os._exit(27)
V2ProvisionPlan(Path(sys.argv[1]), 'pilot-v2.sqlite3', 'account-demo', 'Demo',
                ProducerIdentity('****1234', 'DEMO-SERVER', 'USD'),
                'demo-live-01', 'demo-activity-01').apply()
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.root)],
            cwd=Path(__file__).resolve().parents[2] / "src",
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 27, result.stderr)
        self.assertFalse(self.plan.database.exists())
        self.plan.apply(clock=self.now)
        with open_v2_registry(self.plan.database, read_only=True) as registry:
            self.assertEqual(len(registry.account_evidence("account-demo").sources), 2)

    def test_invalid_input_and_clock_create_nothing(self) -> None:
        invalid = (
            {"filename": "../escape.sqlite3"},
            {"activity_source_id": "demo-live-01"},
            {"label": " "},
        )
        values = {
            "root": self.root,
            "filename": "pilot.sqlite3",
            "account_id": "account-demo",
            "label": "Demo",
            "identity": self.identity,
            "live_source_id": "demo-live-01",
            "activity_source_id": "demo-activity-01",
        }
        for replacement in invalid:
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                V2ProvisionPlan(**(values | replacement))
        with self.assertRaises(ValueError):
            self.plan.apply(clock=datetime(2026, 10, 25, 10))
        self.assertFalse((self.root / "_storage").exists())


if __name__ == "__main__":
    unittest.main()
