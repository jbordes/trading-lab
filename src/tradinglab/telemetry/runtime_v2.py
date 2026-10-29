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
    storage_root: Path | None = None
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


def _validated_credentials(
    environment: Mapping[str, str], names: tuple[str, ...]
) -> dict[str, str]:
    credentials = {name: environment.get(name, "") for name in names}
    for name, value in credentials.items():
        if name == DASHBOARD_TOKEN_ENV:
            validate_dashboard_token(value)
        elif (
            not 24 <= len(value) <= 256
            or not value.isascii()
            or any(not 33 <= ord(character) <= 126 for character in value)
        ):
            raise ValueError(f"La credencial {name} no cumple el formato requerido")
    if len(set(credentials.values())) != len(credentials):
        raise ValueError("Las credenciales requeridas deben ser distintas")
    return credentials


def _validated_storage(root: Path, config: V2PilotRuntimeConfig) -> tuple[Path, tuple[Path, Path]]:
    try:
        storage_root = (config.storage_root or root / "_storage").resolve(strict=True)
    except OSError as exc:
        raise ValueError("El directorio de almacenamiento no existe") from exc
    if not storage_root.is_dir():
        raise ValueError("El directorio de almacenamiento no es válido")
    databases: list[Path] = []
    for configured in (config.v1_database, config.v2_database):
        try:
            database = configured.resolve(strict=True)
        except OSError as exc:
            raise ValueError("Una base SQLite del piloto no existe") from exc
        if database.suffix != ".sqlite3" or not database.is_relative_to(storage_root):
            raise ValueError("Las bases del piloto deben existir bajo storage_root")
        databases.append(database)
    return storage_root, (databases[0], databases[1])


def _v1_receiver_environment(environment: Mapping[str, str]) -> dict[str, str]:
    result = dict(environment)
    for name in (DASHBOARD_TOKEN_ENV, LIVE_TOKEN_ENV, ACTIVITY_TOKEN_ENV, TELEMETRY_READ_TOKEN_ENV):
        result.pop(name, None)
    result["PYTHONUNBUFFERED"] = "1"
    return result


def _v2_receiver_environment(environment: Mapping[str, str]) -> dict[str, str]:
    result = dict(environment)
    for name in (TELEMETRY_TOKEN_ENV, DASHBOARD_TOKEN_ENV):
        result.pop(name, None)
    result["PYTHONUNBUFFERED"] = "1"
    return result


def _dashboard_environment(environment: Mapping[str, str]) -> dict[str, str]:
    result = dict(environment)
    for name in (LIVE_TOKEN_ENV, ACTIVITY_TOKEN_ENV):
        result.pop(name, None)
    result["PYTHONUNBUFFERED"] = "1"
    return result


def _receiver_commands(
    root: Path,
    config: V2PilotRuntimeConfig,
    storage_root: Path,
    databases: tuple[Path, Path],
) -> tuple[list[str], list[str]]:
    return (
        [
            sys.executable,
            str(root / "scripts" / "telemetry_receiver.py"),
            "--port",
            str(config.v1_port),
            "--sqlite-db",
            str(databases[0]),
            "--storage-root",
            str(storage_root),
            "--source-id",
            config.live_source_id,
        ],
        [
            sys.executable,
            str(root / "scripts" / "telemetry_receiver_v2.py"),
            "--port",
            str(config.v2_port),
            "--sqlite-db",
            str(databases[1]),
            "--storage-root",
            str(storage_root),
            "--account-id",
            config.account_id,
        ],
    )


def _dashboard_command(root: Path, config: V2PilotRuntimeConfig) -> list[str]:
    return [
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
    ]


def run_v2_receivers(
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
    """Supervise only the two durable receivers and stop only owned children."""
    _validated_credentials(
        environment,
        (TELEMETRY_TOKEN_ENV, LIVE_TOKEN_ENV, ACTIVITY_TOKEN_ENV, TELEMETRY_READ_TOKEN_ENV),
    )
    storage_root, databases = _validated_storage(root, config)
    check_port(config.v1_port)
    check_port(config.v2_port)
    v1_command, v2_command = _receiver_commands(root, config, storage_root, databases)
    children: list[subprocess.Popen[bytes]] = []
    try:
        v1_receiver = spawn(
            v1_command,
            cwd=root,
            env=_v1_receiver_environment(environment),
            shell=False,
        )
        children.append(v1_receiver)
        _wait_for_receiver("v1", v1_receiver, config.v1_port, ready, clock, sleep)
        v2_receiver = spawn(
            v2_command,
            cwd=root,
            env=_v2_receiver_environment(environment),
            shell=False,
        )
        children.append(v2_receiver)
        _wait_for_receiver("v2", v2_receiver, config.v2_port, ready, clock, sleep)
        report("Receptores v1/v2 listos; el dashboard puede iniciarse o detenerse aparte.")
        while True:
            for name, child in (("receptor v1", v1_receiver), ("receptor v2", v2_receiver)):
                if child.poll() is not None:
                    raise RuntimeError(f"El {name} terminó; se detienen ambos receptores")
            sleep(1)
    finally:
        for child in reversed(children):
            stop_child(child)


def run_v2_dashboard(
    root: Path,
    config: V2PilotRuntimeConfig,
    environment: Mapping[str, str],
    *,
    spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    check_port: Callable[[int], None] = ensure_port_available,
    ready: Callable[[int], bool] = receiver_ready,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> None:
    """Start only the dashboard after both pre-existing receivers answer health."""
    _validated_credentials(
        environment,
        (TELEMETRY_TOKEN_ENV, DASHBOARD_TOKEN_ENV, TELEMETRY_READ_TOKEN_ENV),
    )
    check_port(config.dashboard_port)
    if not ready(config.v1_port) or not ready(config.v2_port):
        raise RuntimeError("Los receptores v1/v2 deben estar listos antes del dashboard")
    dashboard = spawn(
        _dashboard_command(root, config),
        cwd=root,
        env=_dashboard_environment(environment),
        shell=False,
    )
    try:
        report(f"Dashboard: http://127.0.0.1:{config.dashboard_port}/dashboard")
        report("Ctrl+C detiene solo el dashboard; los receptores continúan.")
        while dashboard.poll() is None:
            sleep(1)
        raise RuntimeError("El dashboard terminó inesperadamente")
    finally:
        stop_child(dashboard)


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

    _validated_credentials(
        environment,
        (
            TELEMETRY_TOKEN_ENV,
            DASHBOARD_TOKEN_ENV,
            LIVE_TOKEN_ENV,
            ACTIVITY_TOKEN_ENV,
            TELEMETRY_READ_TOKEN_ENV,
        ),
    )

    storage_root, databases = _validated_storage(root, config)

    for port in (config.v1_port, config.v2_port, config.dashboard_port):
        check_port(port)

    v1_environment = _v1_receiver_environment(environment)
    v2_environment = _v2_receiver_environment(environment)
    dashboard_environment = _dashboard_environment(environment)
    v1_command, v2_command = _receiver_commands(root, config, storage_root, databases)

    children: list[subprocess.Popen[bytes]] = []
    try:
        v1_receiver = spawn(
            v1_command,
            cwd=root,
            env=v1_environment,
            shell=False,
        )
        children.append(v1_receiver)
        _wait_for_receiver("v1", v1_receiver, config.v1_port, ready, clock, sleep)

        v2_receiver = spawn(
            v2_command,
            cwd=root,
            env=v2_environment,
            shell=False,
        )
        children.append(v2_receiver)
        _wait_for_receiver("v2", v2_receiver, config.v2_port, ready, clock, sleep)

        dashboard = spawn(
            _dashboard_command(root, config),
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
