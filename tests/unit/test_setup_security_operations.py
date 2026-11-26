import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tradinglab.installation import verify_installation_files
from tradinglab.multi_config import Settings
from tradinglab.multi_operations import status
from tradinglab.telemetry.relay_queue import SCHEMA_V1, inspect_relay_database


class SetupSecurityOperationsTest(unittest.TestCase):
    def test_inspecting_queue_preserves_old_version_and_detects_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "relay.sqlite3"
            with self.assertRaises(ValueError):
                inspect_relay_database(path)
            self.assertFalse(path.exists())
            with closing(sqlite3.connect(path)) as db:
                db.executescript(SCHEMA_V1)
            inspect_relay_database(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_private_directory_does_not_hide_public_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            private = root / "relay.private.json"
            private.touch(mode=0o600)
            verify_installation_files(root)
            private.chmod(0o644)
            with self.assertRaises(ValueError):
                verify_installation_files(root)

    def test_status_identifies_failed_activity_port(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Settings(data_dir=folder, components=["relay"])
            with (
                patch("tradinglab.multi_operations.running", return_value=True),
                patch(
                    "tradinglab.multi_operations._probe",
                    side_effect=[("disponible", 4), ("sin respuesta", None), ("disponible", None)],
                ),
            ):
                result = status(config)
            self.assertIn("Telemetry (8776): proceso activo · disponible", result)
            self.assertIn("Activity (8777): proceso activo · sin respuesta", result)
            self.assertEqual(result.count("lotes pendientes: 4"), 1)
