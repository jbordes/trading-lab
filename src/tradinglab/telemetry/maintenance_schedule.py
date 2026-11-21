"""Opt-in host-local maintenance scheduling; no API/MT5/network dependencies."""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import shlex
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from tradinglab.telemetry.central_schema import DATABASE_NAME, validate_central_schema
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.windows_tasks import maintenance_task


@dataclass(frozen=True)
class MaintenanceSchedule:
    root: Path
    storage: Path
    database: str
    account_id: str
    hour: int = 3
    minute: int = 30

    def __post_init__(self) -> None:
        if (
            not self.root.is_absolute()
            or not self.storage.is_absolute()
            or not DATABASE_NAME.fullmatch(self.database)
            or not IDENTIFIER.fullmatch(self.account_id)
            or type(self.hour) is not int
            or not 0 <= self.hour <= 23
            or type(self.minute) is not int
            or not 0 <= self.minute <= 59
            or any(not str(path).isprintable() for path in (self.root, self.storage))
        ):
            raise ValueError("Configuración de mantenimiento inválida")

    @property
    def label(self) -> str:
        # One managed job per DB, regardless of account or time changes.
        digest = hashlib.sha256(str(self.storage / self.database).encode()).hexdigest()[:16]
        return f"org.tradinglab.maintenance.{digest}"

    def arguments(self) -> list[str]:
        return [
            str(self.root / "scripts/run_telemetry_maintenance.py"),
            "--storage-root",
            str(self.storage),
            "--database",
            self.database,
            "--daily-account-id",
            self.account_id,
            "--apply",
        ]

    def python(self, scheduler: str) -> Path:
        return (
            self.root / ".venv" / ("Scripts/python.exe" if scheduler == "windows" else "bin/python")
        )

    def cron_block(self) -> str:
        arguments = [str(self.python("cron")), *self.arguments()]
        # Cron interprets % even inside shell quotes. Reject rather than escape ambiguously.
        if any("%" in argument or "\\" in argument for argument in arguments):
            raise ValueError("Cron no admite estas rutas: contienen % o barra inversa")
        command = shlex.join(arguments)
        return (
            f"# BEGIN {self.label}\n{self.minute} {self.hour} * * * {command}\n# END {self.label}\n"
        )

    def launchd_plist(self) -> bytes:
        return plistlib.dumps(
            {
                "Label": self.label,
                "ProgramArguments": [str(self.python("launchd")), *self.arguments()],
                "WorkingDirectory": str(self.root),
                "StartCalendarInterval": {"Hour": self.hour, "Minute": self.minute},
                "RunAtLoad": False,
                "KeepAlive": False,
            }
        )


def validate_target(plan: MaintenanceSchedule, scheduler: str) -> None:
    """Read-only preflight, including account binding; never opens secret files."""
    if (
        not plan.python(scheduler).is_file()
        or not (plan.root / "scripts/run_telemetry_maintenance.py").is_file()
    ):
        raise ValueError("Prepare el checkout y su .venv antes de programar")
    database = plan.storage / plan.database
    if not database.is_file() or database.is_symlink():
        raise ValueError("La base local debe existir y no ser un enlace")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        validate_central_schema(db)
        if (
            db.execute(
                "SELECT 1 FROM sources WHERE account_id=? AND role='snapshot'", (plan.account_id,)
            ).fetchone()
            is None
        ):
            raise ValueError("La cuenta no tiene fuente de capturas registrada")


def merge_crontab(existing: str, plan: MaintenanceSchedule) -> str:
    """Preserve unrelated entries; detect drift instead of replacing a managed block."""
    block = plan.cron_block()
    if plan.label in existing:
        if existing.count(plan.label) == 2 and block in existing:
            return existing
        raise ValueError("Ya existe una tarea distinta para esta base; revise antes de cambiarla")
    return existing + ("\n" if existing and not existing.endswith("\n") else "") + block


def _command(arguments: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        arguments,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=20,
        shell=False,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def _read_crontab() -> str:
    result = _command(["crontab", "-l"])
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and re.fullmatch(
        r"(?:crontab: )?no crontab for [^\r\n]+\s*", result.stderr.strip()
    ):
        return ""
    raise RuntimeError("No se pudo consultar crontab; no se modificó")


def install_schedule(
    plan: MaintenanceSchedule,
    scheduler: str,
    *,
    user_id: str,
    home: Path,
    now: datetime,
) -> str:
    """Explicit installation only. Never starts a job or overwrites another task."""
    validate_target(plan, scheduler)
    if scheduler == "cron":
        existing = _read_crontab()
        updated = merge_crontab(existing, plan)
        if updated == existing:
            return "La tarea cron ya coincide; sin cambios"
        # No crontab CAS exists: detect intervening edits immediately before publication.
        if _read_crontab() != existing:
            raise RuntimeError("Crontab cambió durante la preparación; no se publicó")
        if _command(["crontab", "-"], input_text=updated).returncode:
            raise RuntimeError("No se pudo instalar la entrada cron")
        return "Mantenimiento registrado en crontab del usuario"
    if scheduler == "launchd":
        directory = home / "Library/LaunchAgents"
        destination = directory / f"{plan.label}.plist"
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Ya existe el plist; no se sobrescribe")
        directory.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(plan.launchd_plist())
        if _command(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)]).returncode:
            raise RuntimeError("No se pudo registrar launchd; plist conservado para revisión")
        return "Mantenimiento registrado como LaunchAgent del usuario"
    if scheduler != "windows":
        raise ValueError("Scheduler desconocido")
    start = now.replace(hour=plan.hour, minute=plan.minute, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)
    task = maintenance_task(
        plan.root,
        plan.storage,
        start_date=start.date(),
        database=plan.database,
        account_id=plan.account_id,
        hour=plan.hour,
        minute=plan.minute,
    )
    if _command(["schtasks.exe", "/Query", "/TN", task.name]).returncode == 0:
        raise FileExistsError("Ya existe la tarea Windows; no se sobrescribe")
    with tempfile.TemporaryDirectory(prefix="tradinglab-maintenance-") as temporary:
        xml = Path(temporary) / "maintenance.xml"
        xml.write_text(task.xml(user_id=user_id), encoding="utf-16")
        if _command(["schtasks.exe", "/Create", "/TN", task.name, "/XML", str(xml)]).returncode:
            raise RuntimeError("No se pudo registrar mantenimiento Windows")
    return "Mantenimiento registrado en Windows; requiere sesión iniciada"
