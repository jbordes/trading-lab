from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tradinglab.installation import (
    InstallationConfig,
    prepare_installation,
    public_config,
    read_config,
    read_installation,
)
from tradinglab.installation_backend import LAYOUT
from tradinglab.telemetry.local_secrets import load_local_secrets

ROOT = Path(__file__).resolve().parents[2]


def config() -> InstallationConfig:
    return InstallationConfig(
        "test-account",
        "Example",
        "****1234",
        "TEST-SERVER",
        "USD",
        "test-snapshot",
        "test-live",
        "test-activity",
    )


class InstallationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.repo = self.parent / "checkout"
        self.repo.mkdir()
        self.destination = self.parent / "private data"

    def apply(self, value=None):
        with patch(
            "tradinglab.installation.private_directory", side_effect=lambda p: p.mkdir(mode=0o700)
        ):
            return prepare_installation(self.repo, self.destination, value or config(), apply=True)

    def test_preview_is_read_only_and_real_requires_opt_in(self):
        with patch("tradinglab.installation_backend.prepare_backend") as backend:
            result = prepare_installation(self.repo, self.destination, config())
            self.assertFalse(result["applied"])
            self.assertFalse(self.destination.exists())
            backend.assert_not_called()
            with self.assertRaises(ValueError):
                prepare_installation(
                    self.repo, self.destination, replace(config(), account_mode="real")
                )
            result = prepare_installation(
                self.repo,
                self.destination,
                replace(config(), account_mode="real"),
                allow_real_account=True,
            )
            self.assertEqual(result["account_mode"], "real")
            self.assertFalse(self.destination.exists())

    def test_rejects_invalid_config(self):
        for field, value in (
            ("account_mode", "contest"),
            ("snapshot_port", True),
            ("central_port", 8775),
            ("broker_utc_offset_minutes", 900),
            ("server", "BAD\nSERVER"),
            ("activity_source_id", "test-snapshot"),
            ("login_masked", "1234"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(config(), **{field: value})

    def test_rejects_duplicate_unknown_and_oversized_config(self):
        path = self.parent / "config.json"
        for content in (
            '{"account_id":"one","account_id":"two"}',
            json.dumps(asdict(config()) | {"arbitrary": "field"}),
            " " * 16385,
        ):
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_config(path)
        path.write_text(
            (ROOT / "docs/development/installation.example.json").read_text(), encoding="utf-8"
        )
        value = read_config(path)
        self.assertEqual(value.label, "12345678")
        self.assertEqual(value.login_masked, "****5678")
        self.assertTrue(value.snapshot_source_id.startswith("mt5-12345678-"))
        self.assertEqual(value, read_config(path))

    def test_public_identity_is_scoped_to_login_and_server(self):
        data = json.loads((ROOT / "docs/development/installation.example.json").read_text())
        value = public_config(data)
        self.assertNotEqual(value.account_id, public_config(data | {"server": "OTHER"}).account_id)
        self.assertNotEqual(
            value.account_id, public_config(data | {"login_id": "87654321"}).account_id
        )
        for changes in ({"label": "unwanted"}, {"history_date": "invalid"}, {"login_id": 12345678}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                public_config(data | changes)

    def test_resume_keeps_old_registration_and_checks_public_settings(self):
        path = self.parent / "12345678.json"
        data = json.loads((ROOT / "docs/development/installation.example.json").read_text())
        path.write_text(json.dumps(data))
        legacy = replace(
            public_config(data),
            account_id="old-account",
            snapshot_source_id="old-state",
            live_source_id="old-live",
            activity_source_id="old-activity",
            label="Old internal label",
        )
        spec = importlib.util.spec_from_file_location(
            "installation_run_test", ROOT / "scripts/run_tradinglab.py"
        )
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch("tradinglab.installation.read_installation", return_value=legacy):
            self.assertEqual(
                runner.main(
                    [
                        "--data-dir",
                        str(self.destination),
                        "--dry-run",
                        "--expected-config",
                        str(path),
                    ]
                ),
                0,
            )
            path.write_text(json.dumps(data | {"server": "OTHER-SERVER"}))
            self.assertEqual(
                runner.main(
                    [
                        "--data-dir",
                        str(self.destination),
                        "--dry-run",
                        "--expected-config",
                        str(path),
                    ]
                ),
                1,
            )

    def test_creates_registered_databases_and_private_tokens_without_overwrite(self):
        self.apply()
        self.assertEqual(read_installation(self.destination), config())
        snapshots = {p.name: p.read_bytes() for p in self.destination.iterdir() if p.is_file()}
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(
            snapshots, {p.name: p.read_bytes() for p in self.destination.iterdir() if p.is_file()}
        )
        databases = sorted(self.destination.glob("*.sqlite3"))
        self.assertEqual(len(databases), 2)
        for database in databases:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                self.assertEqual(db.execute("PRAGMA quick_check").fetchall(), [("ok",)])
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        private_files = list(self.destination.glob(".env.*"))
        self.assertTrue(private_files)
        for path in private_files:
            lines = path.read_text().splitlines()
            for line in lines:
                name, value = line.split("=", 1)
                self.assertGreaterEqual(len(value), 32)
                self.assertNotIn(value, (self.destination / "installation.json").read_text())
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        if LAYOUT == "local-dual-v1":
            from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry

            db_path = self.destination / "trading-events.sqlite3"
            with open_v2_registry(db_path) as registry:
                evidence = registry.account_evidence(config().account_id)
                self.assertEqual(evidence.identity.server, config().server)
        else:
            from tradinglab.telemetry.relay_config import load_relay_producers, relay_token_names

            path = self.destination / "relay.json"
            values = load_local_secrets(
                self.destination / ".env.relay",
                allowed_names=relay_token_names(path),
                environment={},
            )
            producers = load_relay_producers(path, values)
            self.assertEqual(len(producers), 2)

    def test_wrong_layout_and_partial_installation_refuse_start(self):
        self.apply()
        path = self.destination / "installation.json"
        value = json.loads(path.read_text())
        value["layout"] = "different-architecture"
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            read_installation(self.destination)
        path.unlink()
        with self.assertRaises(OSError):
            read_installation(self.destination)

    def test_backend_failure_keeps_partial_files_without_ready_marker(self):
        def fail(directory, _config):
            (directory / "partial.txt").write_text("partial")
            raise RuntimeError("synthetic failure")

        with patch("tradinglab.installation_backend.prepare_backend", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.apply()
        self.assertTrue((self.destination / "partial.txt").is_file())
        self.assertFalse((self.destination / "installation.json").exists())

    def test_destination_must_be_new_and_outside_checkout(self):
        for destination in (self.repo, self.repo / "data", Path("relative")):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                prepare_installation(self.repo, destination, config())

    def test_installer_json_to_databases_and_mt5_presets(self):
        from tradinglab.collector_presets import create_presets

        data = json.loads((ROOT / "docs/development/installation.example.json").read_text())
        data["history_date"] = "2026.11.01 00:00:00"
        path = self.parent / (data["login_id"] + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        self.apply(read_config(path))
        registered = read_installation(self.destination)
        with patch(
            "tradinglab.collector_presets.private_directory",
            side_effect=lambda p: p.mkdir(mode=0o700),
        ):
            destination = create_presets(self.destination, data["login_id"], data["history_date"])
        activity = dict(
            line.split("=", 1)
            for line in (destination / "TradingLabActivity.set")
            .read_text(encoding="utf-16")
            .splitlines()
            if line and not line.startswith(";")
        )
        timestamp = activity["HistoryStartServerTime"]
        self.assertTrue(timestamp.isdecimal())
        self.assertEqual(
            datetime.fromtimestamp(int(timestamp), UTC).strftime("%Y.%m.%d %H:%M:%S"),
            data["history_date"],
        )
        self.assertEqual(activity["SourceId"], registered.activity_source_id)
        self.assertEqual(activity["ExpectedDemoLogin"], data["login_id"])
        self.assertEqual(activity["ExpectedDemoServer"], data["server"])
        self.assertEqual(activity["AllowRealAccount"], "false")
        self.assertEqual(json.loads(path.read_text()), data)

    def test_collectors_keep_demo_default_and_wire_explicit_real_flag(self):
        folder = ROOT / "apps/mt5-telemetry-collector"
        for filename in ("TradingLabTelemetry.mq5", "TradingLabActivity.mq5"):
            code = (folder / filename).read_text()
            self.assertIn("input bool AllowRealAccount = false;", code)
            self.assertIn("ExpectedDemoLogin, ExpectedDemoServer, AllowRealAccount", code)
            self.assertNotIn("OrderSend(", code)
        guard = (folder / "TradingLabAccountGuard.mqh").read_text()
        self.assertIn("login == expected_login && server == expected_server", guard)
        self.assertIn(
            "allow_real_account ? ACCOUNT_TRADE_MODE_REAL : ACCOUNT_TRADE_MODE_DEMO", guard
        )


if __name__ == "__main__":
    unittest.main()
