"""User operations exposed by TradingLab SetUp."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib import request
from urllib.error import URLError
from urllib.parse import urlsplit

from tradinglab.multi_catalog import Registration, credential
from tradinglab.multi_config import Settings, api_request, save_json
from tradinglab.multi_host import SERVICES, launch, prepare, running, stop_service
from tradinglab.multi_terminal import COLLECTORS, HELPER, stage_collectors
from tradinglab.telemetry.operational_job import exclusive_job_lock


def attach(root: Path, cfg: Settings) -> None:
    dest = Path(cfg.data_dir)
    if not cfg.mt5_data_dir or not (dest / "relay.private.json").is_file():
        raise ValueError("Prepare el relay local y seleccione la carpeta de datos MT5")
    terminal = Path(cfg.mt5_data_dir).resolve(strict=True)
    registry = dest / "terminals.json"
    binaries = root / "collectors"
    if not binaries.is_dir():
        binaries = root / "_storage/multicuenta/compiled"
    with exclusive_job_lock(dest / "prepare.lock"):
        terminals = json.loads(registry.read_bytes()) if registry.exists() else {}
        path_key = os.path.normcase(str(terminal))
        record = terminals.setdefault(path_key, {"id": uuid.uuid4().hex, "files": {}})
        save_json(registry, terminals)
        master = json.loads((dest / "relay.private.json").read_bytes())["terminal_master"]
        with TemporaryDirectory(dir=dest) as tmp:
            presets = Path(tmp)
            for name, url, role in zip(
                COLLECTORS,
                (cfg.snapshot_ingest_url, cfg.activity_ingest_url),
                ("account-state", "trading-events"),
                strict=True,
            ):
                key = credential(master, record["id"], role)
                (presets / (name + ".set")).write_bytes(
                    f"IngestUrl={url}\r\nToken={key}\r\nTerminalId={record['id']}\r\n".encode(
                        "utf-16"
                    )
                )
            stage_collectors(terminal, binaries, presets, owned=record["files"])
            files = [binaries / (name + ".ex5") for name in (*COLLECTORS, HELPER)]
            record["files"] = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [*files, *presets.glob("*.set")]
            }
            save_json(registry, terminals)


def status(config: Settings) -> str:
    dest = Path(config.data_dir)
    lines = []
    for role in SERVICES:
        if not running(dest, role):
            note = "detenido"
            error = dest / (role + ".error.json")
            if error.is_file():
                note += " · último error: " + json.loads(error.read_bytes())["error"]
            lines.append(f"{role}: {note}")
            continue
        port = urlsplit(config.snapshot_ingest_url).port if role == "relay" else config.port(role)
        try:
            with request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                health = json.load(response)
            extra = f" · lotes pendientes: {health['active_records']}" if role == "relay" else ""
            lines.append(f"{role}: en ejecución, responde{extra}")
        except OSError, ValueError, KeyError:
            lines.append(f"{role}: proceso activo, esperando respuesta")
    try:
        with request.build_opener(request.ProxyHandler({})).open(
            config.api_base_url + "/health", timeout=2
        ) as response:
            available = json.load(response).get("status") == "ready"
    except OSError, ValueError, URLError:
        available = False
    lines.append("API configurada: " + ("disponible" if available else "sin respuesta"))
    return "\n".join(lines)


def dispatch(root: Path, action: str, form: dict) -> dict:
    cfg = Settings.model_validate(form["config"])
    dest = Path(cfg.data_dir)
    if action == "prepare":
        prepare(cfg, form.get("admin", ""), form.get("password", ""))
        instructions = ["Configuración preparada. Puede iniciar los servicios seleccionados."]
        if "dashboard" in cfg.components:
            instructions.append(
                f"Contraseña del dashboard: campo password en {dest / 'dashboard.private.json'}."
            )
        if "api" in cfg.components:
            instructions.append(
                f"Para administrar desde otro equipo: campo admin en {dest / 'api.private.json'}."
            )
        return {"message": "\n\n".join(instructions)}
    if action == "validate":
        return cfg.model_dump()
    if action == "register":
        account = dict(form["account"])
        account["history_from"] = int(
            datetime.strptime(account["history_from"], "%Y.%m.%d %H:%M:%S")
            .replace(tzinfo=UTC)
            .timestamp()
        )
        record = Registration.model_validate(account)
        key = form.get("admin", "")
        if not key and "api" in cfg.components and (dest / "api.private.json").is_file():
            stored = Settings.model_validate_json((dest / "setup.json").read_bytes())
            if stored.api_base_url != cfg.api_base_url:
                raise ValueError("Revise el destino de la API antes del alta")
            key = json.loads((dest / "api.private.json").read_bytes())["admin"]
        if not key:
            raise ValueError(
                "Para dar de alta una cuenta desde este equipo, ingrese la clave de administración de la API central."
            )
        api_request(cfg.api_base_url + "/catalog", key, record.model_dump())
        return {
            "message": "Cuenta registrada. Los collectors pueden reconocerla en la próxima consulta."
        }
    if action == "status":
        return {"message": status(cfg)}
    if not (dest / "setup.json").is_file():
        raise ValueError("Primero prepare este equipo o abra su setup.json existente")
    stored = Settings.model_validate_json((dest / "setup.json").read_bytes())
    if action == "attach":
        attach(root, stored.model_copy(update={"mt5_data_dir": cfg.mt5_data_dir}))
        origins = [
            urlsplit(url) for url in (stored.snapshot_ingest_url, stored.activity_ingest_url)
        ]
        return {
            "message": "En MT5 permita WebRequest a "
            + " y ".join("http://" + o.netloc for o in origins)
            + ". En Navegador > Scripts > TradingLab ejecute TradingLabAttachCollectors."
        }
    roles = form["roles"]
    if not roles or any(role not in SERVICES for role in roles):
        raise ValueError("Seleccione al menos un servicio")
    if action == "start":
        launch(root, stored, roles)
        return {"message": "Inicio solicitado. Cada servicio tiene su propia consola."}
    if action == "stop":
        for role in roles:
            stop_service(dest, role)
        return {"message": "Detención solicitada a los servicios seleccionados."}
    raise ValueError("Operación desconocida")
