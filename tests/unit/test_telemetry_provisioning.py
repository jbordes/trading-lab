from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.telemetry.provisioning import ProvisionPlan  # noqa: E402
from tradinglab.telemetry.sqlite_store import open_registry  # noqa: E402


class ProvisioningTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.plan = ProvisionPlan(
            self.root,
            "pilot.sqlite3",
            "account-demo",
            "Demo",
            "DEMO-SERVER",
            "USD",
            "demo-terminal-01",
        )

    def test_preview_is_pure_and_apply_registers_only_requested_source(self) -> None:
        self.assertEqual(self.plan.database, self.root.resolve() / "_storage" / "pilot.sqlite3")
        self.assertFalse((self.root / "_storage").exists())
        database = self.plan.apply(clock=datetime(2026, 10, 20, tzinfo=UTC))
        self.assertTrue(database.exists())
        with open_registry(database) as registry:
            self.assertIsNone(registry.latest_account_snapshot("demo-terminal-01"))
            with self.assertRaises(ValueError):
                registry.register_source("demo-terminal-01", "other", created_at=datetime.now(UTC))

    def test_existing_database_is_untouched(self) -> None:
        database = self.plan.apply(clock=datetime(2026, 10, 20, tzinfo=UTC))
        before = database.read_bytes()
        with self.assertRaises(FileExistsError):
            self.plan.apply()
        self.assertEqual(database.read_bytes(), before)

    def test_invalid_clock_does_not_create_database(self) -> None:
        with self.assertRaises(ValueError):
            self.plan.apply(clock=datetime(2026, 10, 20))
        self.assertFalse((self.root / "_storage").exists())

    def test_invalid_inputs_fail_before_creating_storage(self) -> None:
        for filename, source, server in (
            ("../escape.sqlite3", "good", "DEMO"),
            ("pilot.db", "good", "DEMO"),
            ("pilot.sqlite3", "bad/source", "DEMO"),
            ("pilot.sqlite3", "good", " "),
        ):
            with self.subTest(filename=filename, source=source):
                with self.assertRaises(ValueError):
                    ProvisionPlan(self.root, filename, "a", "Demo", server, "USD", source)
        self.assertFalse((self.root / "_storage").exists())


if __name__ == "__main__":
    unittest.main()
