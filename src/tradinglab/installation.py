"""Shared installation contract for stable and central layouts; explicit side effects."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import sqlite3
import stat
import subprocess
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from tradinglab.telemetry.admission_v2 import ProducerIdentity
from tradinglab.telemetry.contract import IDENTIFIER


@dataclass(frozen=True)
class InstallationConfig:
    account_id: str
    label: str
    login_masked: str
    server: str
    currency: str
    snapshot_source_id: str
    live_source_id: str
    activity_source_id: str
    account_mode: str = "demo"
    snapshot_port: int = 8776
    activity_port: int = 8777
    dashboard_port: int = 8775
    central_port: int = 8782
    broker_utc_offset_minutes: int = 120

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) for value in (self.login_masked, self.server, self.currency)
        ):
            raise ValueError("Metadatos de broker inválidos")
        ProducerIdentity(self.login_masked, self.server, self.currency)
        if any(not value.isprintable() for value in (self.server, self.currency)):
            raise ValueError("Metadatos de broker inválidos")
        for value in (
            self.account_id,
            self.snapshot_source_id,
            self.live_source_id,
            self.activity_source_id,
        ):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError("Identificador inválido")
        if len({self.snapshot_source_id, self.live_source_id, self.activity_source_id}) != 3:
            raise ValueError("Cada fuente debe ser distinta")
        if (
            not isinstance(self.label, str)
            or not 1 <= len(self.label) <= 128
            or not self.label.isprintable()
        ):
            raise ValueError("Etiqueta inválida")
        if self.account_mode not in ("demo", "real"):
            raise ValueError("Modo de cuenta inválido")
        ports = (self.snapshot_port, self.activity_port, self.dashboard_port, self.central_port)
        if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports) or len(set(ports)) != 4:
            raise ValueError("Puertos inválidos o repetidos")
        if (
            type(self.broker_utc_offset_minutes) is not int
            or not -840 <= self.broker_utc_offset_minutes <= 840
        ):
            raise ValueError("Offset del broker inválido")


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Campo duplicado")
        result[name] = value
    return result


def read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("Configuración demasiado grande")
    value = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(value, dict):
        raise ValueError("Configuración inválida")
    return value


def read_config(path: Path) -> InstallationConfig:
    try:
        return InstallationConfig(**read_json(path))
    except TypeError as exc:
        raise ValueError("Campos de configuración inválidos") from exc


def private_directory(directory: Path) -> None:
    directory.mkdir(mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
        return
    result = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    rows = list(csv.reader(io.StringIO(result.stdout)))
    if len(rows) != 1 or len(rows[0]) != 2 or not re.fullmatch(r"S-1-[0-9-]+", rows[0][1]):
        raise ValueError("No se pudo determinar el usuario Windows")
    subprocess.run(
        [
            "icacls.exe",
            str(directory),
            "/inheritance:r",
            "/grant:r",
            f"*{rows[0][1]}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )


def verify_installation_files(directory: Path) -> None:
    """Inspect metadata before opening a restored host's configuration or credentials."""
    if directory.resolve(strict=True) != directory or not directory.is_dir():
        raise ValueError("Ruta de instalación indirecta o inválida: " + str(directory))
    paths = [directory]
    for path in directory.iterdir():
        if path.suffix not in {
            ".json",
            ".sqlite3",
            ".version",
            ".lock",
        } and not path.name.startswith(("central.sqlite3-", "relay.sqlite3-")):
            continue
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue  # Atomic replacement or transient SQLite journal.
        if not stat.S_ISREG(info.st_mode) or path.is_junction() or info.st_nlink != 1:
            raise ValueError("Archivo de instalación indirecto o inválido: " + str(path))
        paths.append(path)
    if os.name != "nt":
        for path in paths:
            info = path.stat()
            mask = 0o077 if path == directory or path.suffix in {".json", ".sqlite3"} else 0o022
            if info.st_uid != os.getuid() or info.st_mode & mask:
                raise ValueError("Permisos de instalación inseguros: " + str(path))
        return
    # Use SIDs and raw descriptors so localized names and null DACLs are unambiguous.
    script = """
$ErrorActionPreference = 'Stop'
$allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18')
foreach ($item in (ConvertFrom-Json $env:TRADINGLAB_ACL_PATHS)) {
    $acl = Get-Acl -LiteralPath $item
    $raw = [Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(),0)
    if ($raw.Owner.Value -notin ($allowed + 'S-1-5-32-544') -or $null -eq $raw.DiscretionaryAcl) { exit 1 }
    foreach ($ace in $raw.DiscretionaryAcl) {
        if ($ace.AceType -eq 'AccessDenied') { continue }
        if ($ace.AceType -ne 'AccessAllowed' -or $ace.SecurityIdentifier.Value -notin $allowed) { exit 1 }
    }
}
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=os.environ | {"TRADINGLAB_ACL_PATHS": json.dumps([str(p) for p in paths])},
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise ValueError("Revise el propietario y los permisos privados de " + str(directory))


def write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def write_tokens(path: Path, names: tuple[str, ...]) -> dict[str, str]:
    values = {name: secrets.token_urlsafe(32) for name in names}
    if len(set(values.values())) != len(values):
        raise RuntimeError("Generación de credenciales repetidas")
    write_private(path, "".join(f"{name}={value}\n" for name, value in values.items()))
    return values


def prepare_installation(
    root: Path,
    destination: Path,
    config: InstallationConfig,
    *,
    apply: bool = False,
    allow_real_account: bool = False,
) -> dict[str, object]:
    from tradinglab.installation_backend import LAYOUT, prepare_backend

    root = root.resolve(strict=True)
    if not destination.is_absolute() or destination.is_symlink():
        raise ValueError("Use un destino absoluto nuevo sin enlace")
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(root) or not destination.parent.is_dir():
        raise ValueError("El destino debe ser nuevo, fuera del checkout y con padre existente")
    if config.account_mode == "real" and not allow_real_account:
        raise ValueError("Cuenta real: requiere --allow-real-account explícito")
    result = {
        "layout": LAYOUT,
        "destination": str(destination),
        "account_mode": config.account_mode,
        "applied": apply,
    }
    if not apply:
        return result
    private_directory(destination)
    # On failure retain a partial directory, without ready marker. Never erase user data.
    prepare_backend(destination, config)
    for database in destination.glob("*.sqlite3"):
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            if (
                db.execute("PRAGMA quick_check").fetchall() != [("ok",)]
                or db.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("Base creada sin integridad")
    write_private(
        destination / "installation.json",
        json.dumps({"format": 1, "layout": LAYOUT, "config": asdict(config)}, indent=2) + "\n",
    )
    return result


def read_installation(directory: Path) -> InstallationConfig:
    from tradinglab.installation_backend import LAYOUT

    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("Directorio de instalación inválido")
    data = read_json(directory / "installation.json")
    if (
        set(data) != {"format", "layout", "config"}
        or data["format"] != 1
        or data["layout"] != LAYOUT
    ):
        raise ValueError("La instalación pertenece a otra arquitectura o está incompleta")
    try:
        return InstallationConfig(**data["config"])
    except TypeError as exc:
        raise ValueError("Configuración de instalación inválida") from exc
