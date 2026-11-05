"""Explicit, fresh-only preparation of a private central API host."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from tradinglab.telemetry.admission_v2 import ProducerIdentity
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.provisioning_v2 import V2ProvisionPlan
from tradinglab.telemetry.sqlite_store import create_database, open_registry
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry

CENTRAL_KEYS = (
    "CENTRAL_V1_INGEST",
    "CENTRAL_V1_READ",
    "CENTRAL_V2_LIVE",
    "CENTRAL_V2_ACTIVITY",
    "CENTRAL_V2_READ",
)


def tailscale_hostname(value: str) -> str:
    """Allow only one literal DNS host, never wildcard, URL, port or IP."""
    labels = value.split(".")
    if (
        len(value) > 253
        or not value.endswith(".ts.net")
        or len(labels) < 4
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels)
    ):
        raise ValueError("Indique el nombre DNS completo de Tailscale, sin https:// ni puerto")
    return value


@dataclass(frozen=True)
class RemoteHostConfig:
    account_id: str
    label: str
    login_masked: str
    server: str
    currency: str
    v1_source_id: str
    v2_live_source_id: str
    v2_activity_source_id: str
    port: int = 8781

    def __post_init__(self) -> None:
        # Reuse the production identity and provisioning validators before any IO.
        self.plan(Path.cwd(), Path.cwd())
        if not isinstance(self.v1_source_id, str) or not IDENTIFIER.fullmatch(self.v1_source_id):
            raise ValueError("Fuente v1 inválida")
        if len({self.v1_source_id, self.v2_live_source_id, self.v2_activity_source_id}) != 3:
            raise ValueError("Configure tres fuentes distintas")
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("Puerto de API inválido (1024..65535)")
        if self.server.startswith("REEMPLAZAR"):
            raise ValueError("Complete la identidad del broker antes de preparar el host")

    def plan(self, repo: Path, directory: Path) -> V2ProvisionPlan:
        return V2ProvisionPlan(
            repo,
            "central-v2.sqlite3",
            self.account_id,
            self.label,
            ProducerIdentity(self.login_masked, self.server, self.currency),
            self.v2_live_source_id,
            self.v2_activity_source_id,
            storage_root=directory,
        )


def read_host_config(path: Path) -> RemoteHostConfig:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Campo de configuración duplicado")
            result[key] = value
        return result

    if path.stat().st_size > 16384:
        raise ValueError("Configuración demasiado grande")
    data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError("La configuración debe ser un objeto JSON")
    try:
        return RemoteHostConfig(**data)
    except TypeError as exc:
        raise ValueError("Campos de configuración inválidos") from exc


def _private_directory(directory: Path) -> None:
    directory.mkdir(mode=0o700)  # Exclusive: never adopt an existing directory.
    if os.name != "nt":
        directory.chmod(0o700)
        return
    identity = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    rows = list(csv.reader(io.StringIO(identity.stdout)))
    if len(rows) != 1 or len(rows[0]) != 2:
        raise ValueError("No se pudo determinar el SID del usuario")
    sid = rows[0][1]
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise ValueError("No se pudo determinar el SID del usuario")
    subprocess.run(
        [
            "icacls.exe",
            str(directory),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )


def _write_new(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())


def prepare_host(repo: Path, directory: Path, config: RemoteHostConfig, *, apply: bool) -> dict:
    """Preview or create an isolated bundle; never migrate, start services or delete."""
    repo = repo.resolve(strict=True)
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("Use un directorio nuevo absoluto, sin enlace simbólico")
    directory = directory.resolve()
    if directory.is_relative_to(repo) or directory.exists() or not directory.parent.is_dir():
        raise ValueError("El destino debe ser nuevo, fuera del checkout y con padre existente")
    plan = config.plan(repo, directory)
    result = {"directory": str(directory), "schema_v1": 1, "schema_v2": 5, "applied": apply}
    if not apply:
        return result
    _private_directory(directory)
    # Failure preserves partial files for inspection; no destructive rollback.
    v1 = directory / "central-v1.sqlite3"
    create_database(v1)
    stamp = datetime.now(UTC)
    with open_registry(v1) as registry:
        registry.register_account(
            config.account_id, config.label, config.server, config.currency, created_at=stamp
        )
        registry.register_source(config.v1_source_id, config.account_id, created_at=stamp)
    plan.apply(clock=stamp)
    for name, version in ((v1.name, 1), (plan.filename, 5)):
        with closing(sqlite3.connect((directory / name).as_uri() + "?mode=ro", uri=True)) as db:
            if (
                db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                or db.execute("PRAGMA user_version").fetchone()[0] != version
                or db.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise RuntimeError("Falló la verificación de SQLite")
    with open_v2_registry(plan.database, read_only=True) as registry:
        if registry.account_evidence(config.account_id).identity != plan.identity:
            raise RuntimeError("La identidad creada no coincide")
    _write_new(
        directory / ".env.central",
        "".join(f"{key}={secrets.token_urlsafe(32)}\n" for key in CENTRAL_KEYS),
    )
    _write_new(
        directory / ".env.dashboard", f"TRADINGLAB_DASHBOARD_TOKEN={secrets.token_urlsafe(32)}\n"
    )
    # Written last: launch refuses incomplete preparation. No secrets in this JSON.
    _write_new(directory / "host.json", json.dumps(asdict(config), indent=2) + "\n")
    return result
