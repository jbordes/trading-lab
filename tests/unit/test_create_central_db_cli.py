from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CreateCentralDbCliTest(unittest.TestCase):
    def test_preview_creation_and_repeated_creation_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory).resolve()
            database = storage / "fresh.sqlite3"
            config = storage / "host-config.json"
            config.write_text(
                json.dumps(
                    {
                        "account_id": "demo-account",
                        "label": "Demo",
                        "login_masked": "****1234",
                        "server": "DEMO-SERVER",
                        "currency": "USD",
                        "snapshot_source_id": "demo-snapshot",
                        "live_source_id": "demo-live",
                        "activity_source_id": "demo-activity",
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(ROOT / "scripts/create_central_db.py"),
                "--config",
                str(config),
                "--database",
                str(database),
            ]
            preview = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertFalse(database.exists())
            created = subprocess.run(command + ["--apply"], capture_output=True, check=False)
            self.assertEqual(created.returncode, 0, created.stderr)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 8)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1
                )
                self.assertEqual(
                    set(connection.execute("SELECT source_id, role FROM sources")),
                    {
                        ("demo-snapshot", "snapshot"),
                        ("demo-live", "live"),
                        ("demo-activity", "activity"),
                    },
                )
            self.assertEqual(list(storage.glob("*.sqlite3")), [database])
            before = database.read_bytes()
            for flags in ([], ["--apply"]):
                result = subprocess.run(command + flags, capture_output=True, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
