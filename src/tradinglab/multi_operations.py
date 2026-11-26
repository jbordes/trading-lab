"""User operations exposed by TradingLab SetUp."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
from tradinglab.multi_terminal import COLLECTORS, HELPER, stage_collectors, verified_collector_build
from tradinglab.telemetry.operational_job import exclusive_job_lock


def attach(root: Path, cfg: Settings, admin: str = "") -> None:
    dest = Path(cfg.data_dir)
    if not cfg.mt5_data_dir or ("relay" not in cfg.components and not cfg.remote_relay_id):
        raise ValueError(
            "Seleccione la carpeta MT5 y prepare el relay local o indique el ID del relay remoto"
        )
    terminal = Path(cfg.mt5_data_dir).resolve(strict=True)
    registry = dest / "terminals.json"
    binaries = root / "collectors"
    checkout_binaries = None if binaries.is_dir() else verified_collector_build(root)[1]
    with exclusive_job_lock(dest / "prepare.lock"):
        terminals = json.loads(registry.read_bytes()) if registry.exists() else {}
        path_key = os.path.normcase(str(terminal))
        record = terminals.setdefault(path_key, {"id": uuid.uuid4().hex, "files": {}})
        save_json(registry, terminals)
        roles = ("account-state", "trading-events")
        if "relay" in cfg.components:
            master = json.loads((dest / "relay.private.json").read_bytes())["terminal_master"]
            tokens = {role: credential(master, record["id"], role) for role in roles}
        else:
            if not admin and "api" in cfg.components:
                admin = json.loads((dest / "api.private.json").read_bytes())["admin"]
            if not admin:
                raise ValueError(
                    "Ingrese la clave de administración de la API para preparar esta terminal"
                )
            tokens = api_request(
                f"{cfg.api_base_url}/pair/terminal/{cfg.remote_relay_id}/{record['id']}", admin, {}
            )
            if not isinstance(tokens, dict) or any(
                not isinstance(tokens.get(role), str)
                or not re.fullmatch(record["id"] + r"\.[a-f0-9]{64}", tokens[role])
                for role in roles
            ):
                raise ValueError("La API devolvió una vinculación de terminal inválida")
        with TemporaryDirectory(dir=dest) as tmp:
            presets = Path(tmp)
            if checkout_binaries is not None:
                binaries = presets / "compiled"
                binaries.mkdir()
                for filename, contents in checkout_binaries.items():
                    (binaries / filename).write_bytes(contents)
            for name, url, role in zip(
                COLLECTORS,
                (cfg.snapshot_ingest_url, cfg.activity_ingest_url),
                roles,
                strict=True,
            ):
                key = tokens[role]
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
        port = (
            config.relay_port(config.snapshot_ingest_url) if role == "relay" else config.port(role)
        )
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
        if "relay" in cfg.components:
            relay_id = json.loads((dest / "relay.private.json").read_bytes())["id"]
            instructions.append(
                f"ID público del relay para preparar terminales remotas: {relay_id}"
            )
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
        attach(
            root,
            stored.model_copy(
                update={"mt5_data_dir": cfg.mt5_data_dir, "remote_relay_id": cfg.remote_relay_id}
            ),
            form.get("admin", ""),
        )
        origins = [
            urlsplit(url) for url in (stored.snapshot_ingest_url, stored.activity_ingest_url)
        ]
        return {
            "message": "En MT5 permita WebRequest a "
            + " y ".join(o.scheme + "://" + o.netloc for o in origins)
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
