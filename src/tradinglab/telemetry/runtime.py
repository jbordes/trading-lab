"""Foreground supervision of the existing receiver and dashboard processes."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tradinglab.dashboard.auth import DASHBOARD_TOKEN_ENV, validate_dashboard_token
from tradinglab.telemetry.contract import IDENTIFIER


@dataclass(frozen=True)
class RuntimeConfig:
    source_id: str
    receiver_port: int = 8776
    dashboard_port: int = 8775
    sqlite_db: Path | None = None

    def __post_init__(self) -> None:
        if not IDENTIFIER.fullmatch(self.source_id):
            raise ValueError("SourceId inválido")
        for port in (self.receiver_port, self.dashboard_port):
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("Los puertos deben estar entre 1 y 65535")
        if self.receiver_port == self.dashboard_port:
            raise ValueError("Receptor y dashboard necesitan puertos distintos")


def ensure_port_available(port: int) -> None:
    """Fail closed; never stop or adopt a previously running service."""
    with socket.socket() as probe:
        if sys.platform == "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                f"El puerto {port} está ocupado o no está disponible; no se ha detenido su proceso"
            ) from exc


def receiver_ready(port: int) -> bool:
    """Require our health schema and HTTP/1.1, without accessing account data."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            body = response.read(65537)
            if response.status != 200 or response.version != 11 or len(body) > 65536:
                return False
            state = json.loads(body)
            return (
                isinstance(state, dict)
                and state.get("status") == "ready"
                and isinstance(state.get("accepted"), int)
                and isinstance(state.get("missing_sequences"), int)
            )
    except OSError, urllib.error.URLError, ValueError:
        return False


def stop_child(child: subprocess.Popen[bytes]) -> None:
    """Only terminate a child created by this invocation."""
    if child.poll() is None:
        child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def run_runtime(
    root: Path,
    config: RuntimeConfig,
    environment: Mapping[str, str],
    *,
    spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    check_port: Callable[[int], None] = ensure_port_available,
    ready: Callable[[int], bool] = receiver_ready,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> None:
    """Start both services, supervise them, and clean up on every exit path."""
    telemetry_credential = environment.get("TRADINGLAB_TELEMETRY_TOKEN", "")
    if len(telemetry_credential) < 24 or any(
        not 33 <= ord(char) <= 126 for char in telemetry_credential
    ):
        raise ValueError("El token debe tener al menos 24 caracteres ASCII sin espacios")
    dashboard_credential = environment.get(DASHBOARD_TOKEN_ENV, "")
    validate_dashboard_token(dashboard_credential)
    if dashboard_credential == telemetry_credential:
        raise ValueError("Los tokens de telemetría y dashboard deben ser distintos")
    check_port(config.receiver_port)
    check_port(config.dashboard_port)
    database: Path | None = None
    if config.sqlite_db is not None:
        try:
            database = config.sqlite_db.resolve(strict=True)
        except OSError as exc:
            raise ValueError("La base SQLite configurada no existe") from exc
        if database.suffix != ".sqlite3" or not database.is_relative_to(
            (root / "_storage").resolve()
        ):
            raise ValueError("La base SQLite debe existir bajo _storage/ y ser .sqlite3")
    children: list[subprocess.Popen[bytes]] = []
    receiver_environment = dict(environment)
    receiver_environment.pop(DASHBOARD_TOKEN_ENV, None)
    receiver_environment["PYTHONUNBUFFERED"] = "1"
    dashboard_environment = dict(environment)
    dashboard_environment["PYTHONUNBUFFERED"] = "1"
    try:
        receiver_command = [
            sys.executable,
            str(root / "scripts" / "telemetry_receiver.py"),
            "--port",
            str(config.receiver_port),
        ]
        if database is not None:
            receiver_command.extend(("--sqlite-db", str(database), "--source-id", config.source_id))
        receiver = spawn(
            receiver_command,
            cwd=root,
            env=receiver_environment,
            shell=False,
        )
        children.append(receiver)
        deadline = clock() + 15
        while True:
            if receiver.poll() is not None:
                raise RuntimeError("El receptor terminó durante el arranque")
            if ready(config.receiver_port):
                break
            if clock() >= deadline:
                raise RuntimeError("El receptor no confirmó HTTP/1.1 y salud en 15 segundos")
            sleep(0.25)
        dashboard = spawn(
            [
                sys.executable,
                str(root / "scripts" / "live_dashboard.py"),
                "--telemetry",
                "--telemetry-source",
                config.source_id,
                "--telemetry-port",
                str(config.receiver_port),
                "--port",
                str(config.dashboard_port),
            ],
            cwd=root,
            env=dashboard_environment,
            shell=False,
        )
        children.append(dashboard)
        report("Receptor listo con HTTP/1.1. Esperando muestras del EA.")
        report(f"Dashboard: http://127.0.0.1:{config.dashboard_port}/dashboard")
        report("Mantenga esta consola abierta. Ctrl+C detiene ambos procesos.")
        while True:
            for name, child in (("receptor", receiver), ("dashboard", dashboard)):
                if child.poll() is not None:
                    raise RuntimeError(f"El {name} terminó; se detiene el conjunto")
            sleep(1)
    finally:
        for child in reversed(children):
            stop_child(child)
