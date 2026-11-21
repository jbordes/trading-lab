#!/usr/bin/env python3
"""Preview or install ONLY daily maintenance on the local SQLite host."""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.maintenance_schedule import (
        MaintenanceSchedule,
        install_schedule,
        validate_target,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--database", default="central.sqlite3")
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--time", default="03:30", help="HH:MM del host, no del broker")
    parser.add_argument(
        "--scheduler", choices=("auto", "windows", "cron", "launchd"), default="auto"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if (
            len(args.time) != 5
            or args.time[2] != ":"
            or not (args.time[:2] + args.time[3:]).isascii()
            or not (args.time[:2] + args.time[3:]).isdigit()
        ):
            raise ValueError("Horario inválido; use HH:MM")
        default = {"win32": "windows", "darwin": "launchd", "linux": "cron"}.get(sys.platform)
        scheduler = default if args.scheduler == "auto" else args.scheduler
        if (
            scheduler is None
            or (scheduler == "windows" and sys.platform != "win32")
            or (scheduler == "launchd" and sys.platform != "darwin")
            or (scheduler == "cron" and sys.platform not in {"linux", "darwin"})
        ):
            raise ValueError("Scheduler no compatible con este sistema")
        plan = MaintenanceSchedule(
            ROOT.resolve(),
            args.data_dir.resolve(strict=True),
            args.database,
            args.account_id,
            int(args.time[:2]),
            int(args.time[3:]),
        )
        validate_target(plan, scheduler)
        print(f"Mantenimiento diario: {args.time} hora local del host; scheduler={scheduler}")
        print(f"Base: {plan.storage / plan.database}; cuenta: {plan.account_id}")
        print("Copia verificada → consolidación → compactación; sin API, MT5 ni tokens.")
        if scheduler == "cron":
            print(plan.cron_block(), end="")
        if not args.apply:
            print("Vista previa: no se instalaron tareas ni se ejecutó mantenimiento.")
            return 0
        print(
            install_schedule(
                plan, scheduler, user_id=getpass.getuser(), home=Path.home(), now=datetime.now()
            )
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
