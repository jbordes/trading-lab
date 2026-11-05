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

from tradinglab.telemetry.admission_v2 import ProducerIdentity, ProducerRole
from tradinglab.telemetry.central_schema import CENTRAL_SCHEMA_VERSION, create_central_database
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.sqlite_store import open_registry
from tradinglab.telemetry.sqlite_store_v2 import open_v2_registry

CENTRAL_KEYS = (
    "CENTRAL_SNAPSHOT_INGEST",
    "CENTRAL_ACCOUNT_READ",
    "CENTRAL_LIVE_INGEST",
    "CENTRAL_ACTIVITY_INGEST",
    "CENTRAL_TRADING_READ",
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
    snapshot_source_id: str
    live_source_id: str
    activity_source_id: str
    port: int = 8781

    def __post_init__(self) -> None:
        _ = self.identity  # Validate the complete MT5 identity before any IO.
        for value in (
            self.account_id,
            self.snapshot_source_id,
            self.live_source_id,
            self.activity_source_id,
        ):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError("Identificador de cuenta o fuente inválido")
        if (
            not isinstance(self.label, str)
            or not self.label.strip()
            or len(self.label) > 128
            or not self.label.isprintable()
        ):
            raise ValueError("Etiqueta de cuenta inválida")
        if len({self.snapshot_source_id, self.live_source_id, self.activity_source_id}) != 3:
            raise ValueError("Configure tres fuentes distintas")
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("Puerto de API inválido (1024..65535)")
        if self.server.startswith("REEMPLAZAR"):
            raise ValueError("Complete la identidad del broker antes de preparar el host")

    @property
    def identity(self) -> ProducerIdentity:
        return ProducerIdentity(self.login_masked, self.server, self.currency)


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


def prepare_host(
    repo: Path, directory: Path, config: RemoteHostConfig, *, apply: bool
) -> dict[str, object]:
    """Preview or create an isolated bundle; never migrate, start services or delete."""
    repo = repo.resolve(strict=True)
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("Use un directorio nuevo absoluto, sin enlace simbólico")
    directory = directory.resolve()
    if directory.is_relative_to(repo) or directory.exists() or not directory.parent.is_dir():
        raise ValueError("El destino debe ser nuevo, fuera del checkout y con padre existente")
    database = directory / "central.sqlite3"
    result = {
        "directory": str(directory),
        "database": database.name,
        "schema_version": CENTRAL_SCHEMA_VERSION,
        "applied": apply,
    }
    if not apply:
        return result
    _private_directory(directory)
    # Failure preserves partial files for inspection; no destructive rollback.
    create_registered_database(database, config)
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


def create_registered_database(
    database: Path, config: RemoteHostConfig, *, clock: datetime | None = None
) -> None:
    """Create only the registered database, without secrets, services or migration."""
    stamp = clock or datetime.now(UTC)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("La hora del alta debe incluir zona horaria")
    create_central_database(database)
    with open_v2_registry(database) as registry:
        registry.register_account(
            config.account_id,
            config.label,
            config.identity,
            created_at=stamp,
        )
        registry.register_source(
            config.live_source_id,
            config.account_id,
            ProducerRole.LIVE,
            created_at=stamp,
        )
        registry.register_source(
            config.activity_source_id,
            config.account_id,
            ProducerRole.ACTIVITY,
            created_at=stamp,
        )
    with open_registry(database) as registry:
        registry.register_source(config.snapshot_source_id, config.account_id, created_at=stamp)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        if (
            db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or db.execute("PRAGMA user_version").fetchone()[0] != CENTRAL_SCHEMA_VERSION
            or db.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise RuntimeError("Falló la verificación de SQLite central")
    with open_v2_registry(database, read_only=True) as registry:
        evidence = registry.account_evidence(config.account_id)
        if evidence.identity != config.identity or {
            (source.source_id, source.role) for source in evidence.sources
        } != {
            (config.live_source_id, ProducerRole.LIVE),
            (config.activity_source_id, ProducerRole.ACTIVITY),
        }:
            raise RuntimeError("La identidad creada no coincide")
