"""Declarative Windows Task Scheduler definitions for local telemetry jobs."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path

from tradinglab.telemetry.central_schema import DATABASE_NAME
from tradinglab.telemetry.contract import IDENTIFIER
from tradinglab.telemetry.remote_host import tailscale_hostname


@dataclass(frozen=True, slots=True)
class WindowsTask:
    name: str
    description: str
    command: Path
    arguments: tuple[str, ...]
    working_directory: Path
    trigger_xml: str
    restart_count: int = 0
    execution_time_limit: str = "PT1H"

    def xml(self, *, user_id: str) -> str:
        if not user_id or any(character in user_id for character in "\r\n<>"):
            raise ValueError("Usuario de Windows inválido")
        restart = ""
        if self.restart_count:
            restart = (
                "<RestartOnFailure><Interval>PT1M</Interval>"
                f"<Count>{self.restart_count}</Count></RestartOnFailure>"
            )
        arguments = subprocess.list2cmdline(list(self.arguments))
        return (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            f"<RegistrationInfo><Description>{escape(self.description)}</Description></RegistrationInfo>"
            f"<Triggers>{self.trigger_xml}</Triggers>"
            "<Principals><Principal id=" + '"Author">'
            f"<UserId>{escape(user_id)}</UserId><LogonType>InteractiveToken</LogonType>"
            "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"
            "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
            "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
            "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
            "<StartWhenAvailable>true</StartWhenAvailable>"
            f"<ExecutionTimeLimit>{self.execution_time_limit}</ExecutionTimeLimit>"
            f"{restart}</Settings>"
            "<Actions Context=" + '"Author"><Exec>'
            f"<Command>{escape(str(self.command))}</Command>"
            f"<Arguments>{escape(arguments)}</Arguments>"
            f"<WorkingDirectory>{escape(str(self.working_directory))}</WorkingDirectory>"
            "</Exec></Actions></Task>"
        )


def task_plan(
    root: Path,
    storage: Path,
    *,
    start_date: date,
    tailscale_host: str | None = None,
    daily_account_id: str | None = None,
    database: str = "central.sqlite3",
) -> tuple[WindowsTask, WindowsTask]:
    if daily_account_id is not None and (
        not isinstance(daily_account_id, str) or not IDENTIFIER.fullmatch(daily_account_id)
    ):
        raise ValueError("Cuenta de mantenimiento diario inválida")
    api_arguments = (
        str(root / "scripts" / "run_central_api_job.py"),
        "--data-dir",
        str(storage),
    )
    if tailscale_host is not None:
        api_arguments += ("--tailscale-host", tailscale_hostname(tailscale_host))
    python = root / ".venv" / "Scripts" / "python.exe"
    receivers = WindowsTask(
        name="TradingLab Central API",
        description="API central de TradingLab sobre una SQLite; no inicia ni modifica MT5.",
        command=python,
        arguments=api_arguments,
        working_directory=root,
        trigger_xml="<LogonTrigger><Enabled>true</Enabled></LogonTrigger>",
        restart_count=3,
        execution_time_limit="PT0S",
    )
    maintenance = maintenance_task(
        root, storage, start_date=start_date, database=database, account_id=daily_account_id
    )
    return receivers, maintenance


def maintenance_task(
    root: Path,
    storage: Path,
    *,
    start_date: date,
    database: str = "central.sqlite3",
    account_id: str | None = None,
    hour: int = 3,
    minute: int = 30,
) -> WindowsTask:
    """Build maintenance independently of API startup; paths contain no secrets."""
    if (
        not DATABASE_NAME.fullmatch(database)
        or (account_id is not None and not IDENTIFIER.fullmatch(account_id))
        or type(hour) is not int
        or not 0 <= hour <= 23
        or type(minute) is not int
        or not 0 <= minute <= 59
    ):
        raise ValueError("Configuración de tarea de mantenimiento inválida")
    return WindowsTask(
        name="TradingLab Telemetry Maintenance",
        description="Copia diaria local, consistente y verificada de telemetría SQLite."
        + (" Incluye consolidación y retención por cuenta." if account_id else ""),
        command=root / ".venv" / "Scripts" / "python.exe",
        arguments=(
            str(root / "scripts" / "run_telemetry_maintenance.py"),
            "--storage-root",
            str(storage),
            "--database",
            database,
        )
        + (("--daily-account-id", account_id) if account_id else ())
        + ("--apply",),
        working_directory=root,
        trigger_xml=(
            f"<CalendarTrigger><StartBoundary>{start_date.isoformat()}T{hour:02}:{minute:02}:00</StartBoundary>"
            "<Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval>"
            "</ScheduleByDay></CalendarTrigger>"
        ),
    )
