from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CreateV2CliTest(unittest.TestCase):
    def test_preview_creation_and_repeated_creation_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fresh.sqlite3"
            command = [
                sys.executable,
                str(ROOT / "scripts/create_telemetry_v2_db.py"),
                "--storage-root",
                str(Path(directory).resolve()),
                "--filename",
                database.name,
                "--account-id",
                "demo-account",
                "--label",
                "Demo",
                "--login-masked",
                "****1234",
                "--server",
                "DEMO-SERVER",
                "--currency",
                "USD",
                "--live-source-id",
                "demo-live",
                "--activity-source-id",
                "demo-activity",
            ]
            preview = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("esquema SQLite: 5", preview.stdout)
            self.assertFalse(database.exists())
            created = subprocess.run(command + ["--apply"], capture_output=True, check=False)
            self.assertEqual(created.returncode, 0, created.stderr)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            before = database.read_bytes()
            for flags in ([], ["--apply"]):
                result = subprocess.run(command + flags, capture_output=True, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
