"""Prepare and run independently managed Windows services for TradingLab SetUp."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import uuid
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import uvicorn

from tradinglab.dashboard.auth import validate_dashboard_token
from tradinglab.installation import private_directory, write_private
from tradinglab.multi_catalog import central_app, credential
from tradinglab.multi_config import Settings, api_request, save_json
from tradinglab.multi_dashboard import serve_dashboard
from tradinglab.multi_relay import MultiRelay
from tradinglab.telemetry.central_schema import create_central_database, validate_central_schema
from tradinglab.telemetry.operational_job import JobAlreadyRunningError, exclusive_job_lock
from tradinglab.telemetry.relay_http import relay_listeners
from tradinglab.telemetry.relay_queue import RelayQueue, create_relay_database
from tradinglab.telemetry.remote_host import CENTRAL_KEYS

SERVICES = ("api", "relay", "dashboard")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _keys(path: Path, factory) -> dict:
    if not path.exists():
        save_json(path, factory())
    return _read(path)


def prepare(config: Settings, admin: str, password: str) -> None:
    dest = Path(config.data_dir)
    if not dest.exists():
        private_directory(dest)
        write_private(dest / "multicuenta.version", "2")
    if (
        dest.is_symlink()
        or dest.is_junction()
        or not (dest / "multicuenta.version").is_file()
        or (dest / "multicuenta.version").read_text() != "2"
    ):
        raise ValueError(
            "Elija una carpeta nueva o la carpeta privada de esta instalación multicuenta"
        )
    with exclusive_job_lock(dest / "prepare.lock"):
        prior = dest / "setup.json"
        if prior.exists() and Settings.model_validate(_read(prior)) != config:
            if any(running(dest, r) for r in SERVICES):
                raise ValueError("Detenga los servicios locales antes de cambiar la configuración")
        central = None
        if "api" in config.components:

            def central_keys():
                access = admin or secrets.token_urlsafe(32)
                validate_dashboard_token(access)
                return {k: secrets.token_urlsafe(32) for k in (*CENTRAL_KEYS, "pairing")} | {
                    "admin": access
                }

            central = _keys(dest / "api.private.json", central_keys)
            db = dest / "central.sqlite3"
            if not db.exists():
                with TemporaryDirectory(dir=dest) as temp:
                    staged = Path(temp) / db.name
                    create_central_database(staged, multicuenta=True)
                    os.link(staged, db)
            with closing(sqlite3.connect(db)) as connection:
                validate_central_schema(connection)
                if connection.execute("PRAGMA user_version").fetchone()[0] not in (9, 10):
                    raise ValueError("La base seleccionada pertenece a otra versión")
        for role in ("relay", "dashboard"):
            if role not in config.components:
                continue
            path = dest / (role + ".private.json")
            stored = _read(path) if path.exists() else {}
            if stored and stored["api"] == config.api_base_url:
                continue
            identity = stored.get("id") or uuid.uuid4().hex
            if role == "dashboard":
                access = stored.get("password") or password or secrets.token_urlsafe(32)
                validate_dashboard_token(access)
                if access == (central or {}).get("admin", admin):
                    raise ValueError(
                        "Use una contraseña del dashboard distinta de la clave de alta"
                    )
            if central:
                if role == "relay":
                    keys = {
                        k: credential(central["pairing"], identity, k)
                        for k in ("account-state", "trading-events")
                    }
                else:
                    keys = {k: central[k] for k in ("CENTRAL_ACCOUNT_READ", "CENTRAL_TRADING_READ")}
            else:
                if not admin:
                    raise ValueError(
                        "Para vincular este equipo, ingrese la clave de administración de la API central."
                    )
                keys = api_request(f"{config.api_base_url}/pair/{role}/{identity}", admin, {})
            if role == "relay":
                if stored and keys["account-state"] != stored["account-state"]:
                    with closing(RelayQueue(dest / "relay.sqlite3")) as queue:
                        if queue.bindings():
                            raise ValueError("Esta cola pertenece a otra instalación central")
                keys["terminal_master"] = stored.get("terminal_master") or secrets.token_urlsafe(32)
                if not (dest / "relay.sqlite3").exists():
                    create_relay_database(dest / "relay.sqlite3")
            else:
                keys["password"] = access
            save_json(path, keys | {"id": identity, "api": config.api_base_url})
        save_json(prior, config.model_dump())


def running(dest: Path, role: str) -> bool:
    if not (dest / (role + ".lock")).exists():
        return False
    try:
        with exclusive_job_lock(dest / (role + ".lock")):
            return False
    except JobAlreadyRunningError:
        return True


def launch(root: Path, config: Settings, roles: list[str]) -> None:
    dest = Path(config.data_dir)
    if set(roles) - set(config.components):
        raise ValueError("La selección incluye servicios sin preparar")
    for role in roles:
        if running(dest, role):
            continue
        subprocess.Popen(
            [sys.executable, str(root / "scripts/multi_setup.py"), "serve", role, str(dest)],
            cwd=root,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
            stdin=None,
            stdout=None,
            stderr=None,
        )


def stop_service(dest: Path, role: str) -> None:
    if running(dest, role):
        current = _read(dest / (role + ".run.json"))
        save_json(dest / (role + ".stop.json"), current)


def run_service(config: Settings, role: str) -> None:
    dest = Path(config.data_dir)
    if role not in config.components:
        raise ValueError("Servicio sin preparar")
    with exclusive_job_lock(dest / (role + ".lock")):
        generation = {"instance": uuid.uuid4().hex}
        save_json(dest / (role + ".run.json"), generation)
        stop = threading.Event()
        signal_file = dest / (role + ".stop.json")

        def watch():
            while not stop.wait(0.5):
                if signal_file.is_file() and _read(signal_file) == generation:
                    stop.set()

        monitor = threading.Thread(target=watch, daemon=True)
        monitor.start()
        keys = _read(dest / (role + ".private.json"))
        print(f"TradingLab {role} · Ctrl+C detiene este servicio", flush=True)
        try:
            if role == "api":
                app = central_app(
                    dest / "central.sqlite3", keys, urlsplit(config.api_base_url).hostname
                )
                server = uvicorn.Server(
                    uvicorn.Config(
                        app,
                        host="127.0.0.1",
                        port=config.port(role),
                        access_log=False,
                        proxy_headers=False,
                        limit_concurrency=32,
                    )
                )

                def shutdown():
                    stop.wait()
                    server.should_exit = True

                threading.Thread(target=shutdown, daemon=True).start()
                server.run()
            elif role == "dashboard":
                serve_dashboard(config, keys, stop)
            else:
                with closing(RelayQueue(dest / "relay.sqlite3")) as queue:
                    relay = MultiRelay(queue, config.api_base_url, keys)
                    ports = [
                        config.relay_port(url)
                        for url in (config.snapshot_ingest_url, config.activity_ingest_url)
                    ]
                    with relay_listeners(relay, ports):
                        worker = threading.Thread(target=relay.forward, args=(stop,), daemon=True)
                        worker.start()
                        try:
                            while not stop.wait(0.5):
                                if not worker.is_alive():
                                    raise RuntimeError("El proceso de entrega del relay terminó")
                        finally:
                            stop.set()
                            worker.join()
        finally:
            stop.set()
            monitor.join()
