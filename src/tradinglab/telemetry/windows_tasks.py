"""Declarative Windows Task Scheduler definitions for local telemetry jobs."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path


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
    secrets_file: Path,
    *,
    start_date: date,
) -> tuple[WindowsTask, WindowsTask]:
    python = root / ".venv" / "Scripts" / "python.exe"
    receivers = WindowsTask(
        name="TradingLab Telemetry Receivers",
        description="Receptores locales read-only de TradingLab; no inicia ni modifica MT5.",
        command=python,
        arguments=(
            str(root / "scripts" / "run_telemetry_receivers_job.py"),
            "--storage-root",
            str(storage),
            "--secrets-file",
            str(secrets_file),
        ),
        working_directory=root,
        trigger_xml="<LogonTrigger><Enabled>true</Enabled></LogonTrigger>",
        restart_count=3,
        execution_time_limit="PT0S",
    )
    maintenance = WindowsTask(
        name="TradingLab Telemetry Maintenance",
        description="Copia diaria local, consistente y verificada de telemetría SQLite.",
        command=python,
        arguments=(
            str(root / "scripts" / "run_telemetry_maintenance.py"),
            "--storage-root",
            str(storage),
            "--apply",
        ),
        working_directory=root,
        trigger_xml=(
            f"<CalendarTrigger><StartBoundary>{start_date.isoformat()}T03:30:00</StartBoundary>"
            "<Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval>"
            "</ScheduleByDay></CalendarTrigger>"
        ),
    )
    return receivers, maintenance
