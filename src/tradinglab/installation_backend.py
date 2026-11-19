"""Stable main adapter: two local databases, two receivers and dashboard."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.installation import InstallationConfig, write_tokens
from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.local_secrets import load_local_secrets
from tradinglab.telemetry.runtime_v2 import V2PilotRuntimeConfig, run_v2_pilot
from tradinglab.telemetry.sqlite_store import create_database, open_registry
from tradinglab.telemetry.sqlite_store_v2 import create_v2_database, open_v2_registry

LAYOUT = "local-dual-v1"
TOKEN_NAMES = (
    "TRADINGLAB_TELEMETRY_TOKEN",
    "TRADINGLAB_TELEMETRY_LIVE_TOKEN",
    "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN",
    "TRADINGLAB_TELEMETRY_READ_TOKEN",
    "TRADINGLAB_DASHBOARD_TOKEN",
)


def prepare_backend(directory: Path, config: InstallationConfig) -> None:
    stamp = datetime.now(UTC)
    account = directory / "account-state.sqlite3"
    activity = directory / "trading-events.sqlite3"
    create_database(account)
    with open_registry(account) as registry:
        registry.register_account(
            config.account_id, config.label, config.server, config.currency, created_at=stamp
        )
        registry.register_source(config.snapshot_source_id, config.account_id, created_at=stamp)
    create_v2_database(activity)
    with open_v2_registry(activity) as registry:
        registry.register_account(
            config.account_id,
            config.label,
            ProducerIdentity(config.login_masked, config.server, config.currency),
            created_at=stamp,
        )
        registry.register_source(
            config.live_source_id, config.account_id, ProducerRole.LIVE, created_at=stamp
        )
        registry.register_source(
            config.activity_source_id, config.account_id, ProducerRole.ACTIVITY, created_at=stamp
        )
    write_tokens(directory / ".env.local", TOKEN_NAMES)


def run_backend(root: Path, directory: Path, config: InstallationConfig) -> None:
    values = load_local_secrets(directory / ".env.local", allowed_names=TOKEN_NAMES, environment={})
    if set(values) != set(TOKEN_NAMES):
        raise ValueError("Faltan credenciales de instalación")
    environment = dict(os.environ)
    environment.update(values)
    runtime = V2PilotRuntimeConfig(
        live_source_id=config.snapshot_source_id,
        activity_source_id=config.activity_source_id,
        account_id=config.account_id,
        v1_database=directory / "account-state.sqlite3",
        v2_database=directory / "trading-events.sqlite3",
        storage_root=directory,
        v1_port=config.snapshot_port,
        v2_port=config.activity_port,
        dashboard_port=config.dashboard_port,
        broker_utc_offset_minutes=config.broker_utc_offset_minutes,
    )
    run_v2_pilot(root, runtime, environment)
