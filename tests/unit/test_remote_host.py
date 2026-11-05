from __future__ import annotations

import json
import os
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tradinglab.telemetry.central_api import CentralSettings, create_central_app
from tradinglab.telemetry.remote_host import (
    CENTRAL_KEYS,
    RemoteHostConfig,
    prepare_host,
    read_host_config,
    tailscale_hostname,
)
from tradinglab.telemetry.sqlite_store import open_registry
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry

ROOT = Path(__file__).resolve().parents[2]


class RemoteHostTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve() / "private-host"
        self.config = RemoteHostConfig(
            "synthetic-demo",
            "Demo",
            "****1234",
            "DEMO-SERVER",
            "USD",
            "synthetic-v1",
            "synthetic-v2-live",
            "synthetic-activity",
        )

    def prepare(self) -> None:
        # Only synthetic credentials are written by tests; never read real env files.
        with patch(
            "tradinglab.telemetry.remote_host.secrets.token_urlsafe",
            side_effect=[f"synthetic-test-token-number-{i:02}" for i in range(6)],
        ):
            prepare_host(ROOT, self.directory, self.config, apply=True)

    def test_preview_has_no_side_effects(self) -> None:
        with patch("tradinglab.telemetry.remote_host._private_directory") as create:
            result = prepare_host(ROOT, self.directory, self.config, apply=False)
        self.assertFalse(result["applied"])
        create.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_creation_identity_schema_permissions_and_no_overwrite(self) -> None:
        self.prepare()
        for filename, version in (("central-v1.sqlite3", 1), ("central-v2.sqlite3", 5)):
            with closing(sqlite3.connect(self.directory / filename)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], version)
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        with open_registry(self.directory / "central-v1.sqlite3") as registry:
            self.assertFalse(
                registry.register_source(
                    self.config.v1_source_id,
                    self.config.account_id,
                    created_at=datetime.now(UTC),
                )
            )
        with open_v2_registry(self.directory / "central-v2.sqlite3", read_only=True) as registry:
            self.assertEqual(len(registry.account_evidence(self.config.account_id).sources), 2)
        self.assertEqual(read_host_config(self.directory / "host.json"), self.config)
        synthetic_keys = (self.directory / ".env.central").read_text().splitlines()
        self.assertEqual([line.split("=", 1)[0] for line in synthetic_keys], list(CENTRAL_KEYS))
        if os.name != "nt":
            self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.directory / ".env.central").stat().st_mode & 0o777, 0o600)
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        for apply in (False, True):
            with self.assertRaises(ValueError):
                prepare_host(ROOT, self.directory, self.config, apply=apply)
        self.assertEqual(
            before, {path.name: path.read_bytes() for path in self.directory.iterdir()}
        )

    def test_rejects_checkout_relative_path_and_missing_parent(self) -> None:
        for path in (
            ROOT / "_storage/new-server",
            Path("relative"),
            self.directory / "missing-parent/host",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                prepare_host(ROOT, path, self.config, apply=True)

    def test_config_rejects_unknown_duplicate_and_invalid_fields(self) -> None:
        path = self.directory.parent / "input.json"
        for content in (
            '{"port": 8781, "port": 8782}',
            "[]",
            json.dumps({**asdict(self.config), "command": "not-allowed"}),
            json.dumps({**asdict(self.config), "v1_source_id": "../unsafe"}),
        ):
            path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                read_host_config(path)
        for changes in (
            {"server": "REEMPLAZAR-SERVIDOR"},
            {"port": True},
            {"v1_source_id": self.config.v2_activity_source_id},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.config, **changes)

    def test_failed_setup_has_no_completion_marker_and_no_automatic_cleanup(self) -> None:
        with patch("tradinglab.telemetry.remote_host.create_database", side_effect=OSError):
            with self.assertRaises(OSError):
                prepare_host(ROOT, self.directory, self.config, apply=True)
        self.assertTrue(self.directory.is_dir())
        self.assertFalse((self.directory / "host.json").exists())
        self.assertFalse((self.directory / ".env.central").exists())

    def test_host_is_exact_dns_not_wildcard_url_or_public_bind(self) -> None:
        self.assertEqual(tailscale_hostname("mac.example.ts.net"), "mac.example.ts.net")
        for value in (
            "*.ts.net",
            "https://mac.example.ts.net",
            "0.0.0.0",
            "100.64.0.1",
            "mac.example.ts.net:443",
            "mac.example.ts.net/",
            "mac.example.ts.net.evil",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tailscale_hostname(value)

    def test_central_api_accepts_exact_proxy_host_and_preserves_origin_guard(self) -> None:
        self.prepare()
        settings = CentralSettings(
            self.directory / "central-v1.sqlite3",
            self.directory / "central-v2.sqlite3",
            self.config.v1_source_id,
            self.config.account_id,
            *(f"synthetic-central-credential-{i}" for i in range(5)),
            allowed_hosts=("localhost", "127.0.0.1", "mac.example.ts.net"),
        )
        with TestClient(
            create_central_app(settings), base_url="http://mac.example.ts.net"
        ) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(
                client.get("/health", headers={"Host": "other.example.ts.net"}).status_code, 400
            )
            self.assertEqual(
                client.get("/health", headers={"Origin": "https://mac.example.ts.net"}).status_code,
                403,
            )

    def test_cli_preview_does_not_create_directory_or_emit_tokens(self) -> None:
        config_path = self.directory.parent / "input.json"
        config_path.write_text(json.dumps(asdict(self.config)))
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/prepare_remote_host.py"),
                "--config",
                str(config_path),
                "--data-dir",
                str(self.directory),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.directory.exists())
        self.assertNotIn("CENTRAL_V1_INGEST=", result.stdout + result.stderr)

    def test_launcher_only_passes_private_files_and_allowed_host_to_central_cli(self) -> None:
        self.prepare()
        with patch.dict(sys.modules), patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
            main = runpy.run_path(str(ROOT / "scripts/run_remote_host.py"))["main"]
        with patch.dict(main.__globals__, central_main=lambda args: self._launch_check(args)):
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        str(self.directory),
                        "--tailscale-host",
                        "mac.example.ts.net",
                    ]
                ),
                0,
            )

    def _launch_check(self, args: list[str]) -> int:
        self.assertIn("--allowed-host", args)
        self.assertIn("mac.example.ts.net", args)
        self.assertNotIn("0.0.0.0", args)
        self.assertFalse(any("synthetic-test-token" in value for value in args))
        return 0


if __name__ == "__main__":
    unittest.main()
