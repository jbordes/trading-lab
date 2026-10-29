"""Foreground supervision for the transitional v1-live plus v2-history pilot."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tradinglab.dashboard.auth import DASHBOARD_TOKEN_ENV, validate_dashboard_token
from tradinglab.dashboard.telemetry import TELEMETRY_TOKEN_ENV
from tradinglab.dashboard.telemetry_v2 import TELEMETRY_READ_TOKEN_ENV
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.runtime import ensure_port_available, receiver_ready, stop_child

LIVE_TOKEN_ENV = "TRADINGLAB_TELEMETRY_LIVE_TOKEN"
ACTIVITY_TOKEN_ENV = "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN"


@dataclass(frozen=True, slots=True)
class V2PilotRuntimeConfig:
    live_source_id: str
    activity_source_id: str
    account_id: str
    v1_database: Path
    v2_database: Path
    v1_port: int = 8776
    v2_port: int = 8777
    dashboard_port: int = 8775
    broker_utc_offset_minutes: int = 120

    def __post_init__(self) -> None:
        for value in (self.live_source_id, self.activity_source_id, self.account_id):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError("Identificador del piloto v2 inválido")
        ports = (self.v1_port, self.v2_port, self.dashboard_port)
        if any(
            isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
            for port in ports
        ) or len(set(ports)) != len(ports):
            raise ValueError("Los tres puertos del piloto deben ser válidos y distintos")
        if (
            isinstance(self.broker_utc_offset_minutes, bool)
            or not isinstance(self.broker_utc_offset_minutes, int)
            or not -14 * 60 <= self.broker_utc_offset_minutes <= 14 * 60
        ):
            raise ValueError("El offset UTC del broker debe estar entre -840 y 840")


def run_v2_pilot(
    root: Path,
    config: V2PilotRuntimeConfig,
    environment: Mapping[str, str],
    *,
    spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    check_port: Callable[[int], None] = ensure_port_available,
    ready: Callable[[int], bool] = receiver_ready,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> None:
    """Start both receivers and the dashboard, then stop only these children."""

    credentials = {
        TELEMETRY_TOKEN_ENV: environment.get(TELEMETRY_TOKEN_ENV, ""),
        DASHBOARD_TOKEN_ENV: environment.get(DASHBOARD_TOKEN_ENV, ""),
        LIVE_TOKEN_ENV: environment.get(LIVE_TOKEN_ENV, ""),
        ACTIVITY_TOKEN_ENV: environment.get(ACTIVITY_TOKEN_ENV, ""),
        TELEMETRY_READ_TOKEN_ENV: environment.get(TELEMETRY_READ_TOKEN_ENV, ""),
    }
    validate_dashboard_token(credentials[DASHBOARD_TOKEN_ENV])
    for name, value in credentials.items():
        if name == DASHBOARD_TOKEN_ENV:
            continue
        if (
            not 24 <= len(value) <= 256
            or not value.isascii()
            or any(not 33 <= ord(character) <= 126 for character in value)
        ):
            raise ValueError(f"La credencial {name} no cumple el formato requerido")
    if len(set(credentials.values())) != len(credentials):
        raise ValueError("Las cinco credenciales del piloto deben ser distintas")

    storage_root = (root / "_storage").resolve()
    databases: list[Path] = []
    for configured in (config.v1_database, config.v2_database):
        try:
            database = configured.resolve(strict=True)
        except OSError as exc:
            raise ValueError("Una base SQLite del piloto no existe") from exc
        if database.suffix != ".sqlite3" or not database.is_relative_to(storage_root):
            raise ValueError("Las bases del piloto deben existir bajo _storage/")
        databases.append(database)

    for port in (config.v1_port, config.v2_port, config.dashboard_port):
        check_port(port)

    v1_environment = dict(environment)
    for name in (DASHBOARD_TOKEN_ENV, LIVE_TOKEN_ENV, ACTIVITY_TOKEN_ENV, TELEMETRY_READ_TOKEN_ENV):
        v1_environment.pop(name, None)
    v1_environment["PYTHONUNBUFFERED"] = "1"

    v2_environment = dict(environment)
    for name in (TELEMETRY_TOKEN_ENV, DASHBOARD_TOKEN_ENV):
        v2_environment.pop(name, None)
    v2_environment["PYTHONUNBUFFERED"] = "1"

    dashboard_environment = dict(environment)
    for name in (LIVE_TOKEN_ENV, ACTIVITY_TOKEN_ENV):
        dashboard_environment.pop(name, None)
    dashboard_environment["PYTHONUNBUFFERED"] = "1"

    children: list[subprocess.Popen[bytes]] = []
    try:
        v1_receiver = spawn(
            [
                sys.executable,
                str(root / "scripts" / "telemetry_receiver.py"),
                "--port",
                str(config.v1_port),
                "--sqlite-db",
                str(databases[0]),
                "--source-id",
                config.live_source_id,
            ],
            cwd=root,
            env=v1_environment,
            shell=False,
        )
        children.append(v1_receiver)
        _wait_for_receiver("v1", v1_receiver, config.v1_port, ready, clock, sleep)

        v2_receiver = spawn(
            [
                sys.executable,
                str(root / "scripts" / "telemetry_receiver_v2.py"),
                "--port",
                str(config.v2_port),
                "--sqlite-db",
                str(databases[1]),
                "--account-id",
                config.account_id,
            ],
            cwd=root,
            env=v2_environment,
            shell=False,
        )
        children.append(v2_receiver)
        _wait_for_receiver("v2", v2_receiver, config.v2_port, ready, clock, sleep)

        dashboard = spawn(
            [
                sys.executable,
                str(root / "scripts" / "live_dashboard.py"),
                "--telemetry",
                "--telemetry-source",
                config.live_source_id,
                "--telemetry-port",
                str(config.v1_port),
                "--history-v2",
                "--history-v2-source",
                config.activity_source_id,
                "--history-v2-port",
                str(config.v2_port),
                "--port",
                str(config.dashboard_port),
                "--broker-utc-offset-minutes",
                str(config.broker_utc_offset_minutes),
            ],
            cwd=root,
            env=dashboard_environment,
            shell=False,
        )
        children.append(dashboard)
        report("Receptores v1/v2 listos. Esperando telemetría de Juampi.")
        report(f"Dashboard: http://127.0.0.1:{config.dashboard_port}/dashboard")
        report("Mantenga esta consola abierta. Ctrl+C detiene los tres procesos.")
        while True:
            for name, child in (
                ("receptor v1", v1_receiver),
                ("receptor v2", v2_receiver),
                ("dashboard", dashboard),
            ):
                if child.poll() is not None:
                    raise RuntimeError(f"El {name} terminó; se detiene el conjunto")
            sleep(1)
    finally:
        for child in reversed(children):
            stop_child(child)


def _wait_for_receiver(
    name: str,
    child: subprocess.Popen[bytes],
    port: int,
    ready: Callable[[int], bool],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> None:
    deadline = clock() + 15
    while True:
        if child.poll() is not None:
            raise RuntimeError(f"El receptor {name} terminó durante el arranque")
        if ready(port):
            return
        if clock() >= deadline:
            raise RuntimeError(f"El receptor {name} no confirmó salud en 15 segundos")
        sleep(0.25)
