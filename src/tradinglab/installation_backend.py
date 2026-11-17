"""Central adapter: local API, durable relay and dashboard for a prepared test host."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tradinglab.installation import InstallationConfig, write_private, write_tokens
from tradinglab.telemetry.relay_queue import create_relay_database
from tradinglab.telemetry.remote_host import (
    CENTRAL_KEYS,
    RemoteHostConfig,
    create_registered_database,
)

LAYOUT = "central-relay-v1"


def prepare_backend(directory: Path, config: InstallationConfig) -> None:
    host = RemoteHostConfig(
        config.account_id,
        config.label,
        config.login_masked,
        config.server,
        config.currency,
        config.snapshot_source_id,
        config.live_source_id,
        config.activity_source_id,
        config.central_port,
    )
    create_registered_database(directory / "central.sqlite3", host)
    central_keys = write_tokens(directory / ".env.central", CENTRAL_KEYS)
    write_tokens(directory / ".env.dashboard", ("TRADINGLAB_DASHBOARD_TOKEN",))
    local_keys = write_tokens(
        directory / ".env.collectors", ("RELAY_LIVE_LOCAL_TOKEN", "RELAY_ACTIVITY_LOCAL_TOKEN")
    )
    # Provision matching credentials in one operation; never read existing private files.
    relay_keys = local_keys | {
        "RELAY_LIVE_CENTRAL_TOKEN": central_keys["CENTRAL_SNAPSHOT_INGEST"],
        "RELAY_ACTIVITY_CENTRAL_TOKEN": central_keys["CENTRAL_ACTIVITY_INGEST"],
    }
    write_private(
        directory / ".env.relay", "".join(f"{key}={value}\n" for key, value in relay_keys.items())
    )
    rows = []
    for contract, source, role, path, prefix in (
        ("account-state", config.snapshot_source_id, "snapshot", "account-state", "LIVE"),
        ("trading-events", config.activity_source_id, "activity", "trading-events", "ACTIVITY"),
    ):
        rows.append(
            dict(
                contract=contract,
                source_id=source,
                account_id=config.account_id,
                role=role,
                login_masked=config.login_masked,
                server=config.server,
                currency=config.currency,
                target=f"http://127.0.0.1:{config.central_port}/api/{path}",
                local_token_env=f"RELAY_{prefix}_LOCAL_TOKEN",
                central_token_env=f"RELAY_{prefix}_CENTRAL_TOKEN",
            )
        )
    write_private(directory / "relay.json", json.dumps(rows, indent=2) + "\n")
    create_relay_database(directory / "relay.sqlite3")


def backend_commands(root: Path, directory: Path, config: InstallationConfig) -> list[list[str]]:
    def command(script: str, *args: str) -> list[str]:
        return [sys.executable, str(root / "scripts" / script), *args]

    return [
        command(
            "central_api.py",
            "--db",
            str(directory / "central.sqlite3"),
            "--source-id",
            config.snapshot_source_id,
            "--account-id",
            config.account_id,
            "--secrets-file",
            str(directory / ".env.central"),
            "--port",
            str(config.central_port),
        ),
        command(
            "telemetry_relay.py",
            "--queue",
            str(directory / "relay.sqlite3"),
            "--config",
            str(directory / "relay.json"),
            "--secrets-file",
            str(directory / ".env.relay"),
            "--port",
            str(config.snapshot_port),
            "--port",
            str(config.activity_port),
        ),
        command(
            "live_dashboard.py",
            "--central-api-port",
            str(config.central_port),
            "--snapshot-source",
            config.snapshot_source_id,
            "--activity-source",
            config.activity_source_id,
            "--secrets-file",
            str(directory / ".env.central"),
            "--dashboard-secrets-file",
            str(directory / ".env.dashboard"),
            "--port",
            str(config.dashboard_port),
            "--broker-utc-offset-minutes",
            str(config.broker_utc_offset_minutes),
        ),
    ]


def run_backend(root: Path, directory: Path, config: InstallationConfig) -> None:
    from tradinglab.installation_runtime import supervise

    supervise(
        backend_commands(root, directory, config),
        [config.central_port, config.snapshot_port, config.dashboard_port],
        [config.central_port, config.snapshot_port, config.activity_port, config.dashboard_port],
        root=root,
    )
