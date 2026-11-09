#!/usr/bin/env python3
"""Preview or register the two local Windows telemetry tasks."""

from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.remote_host import tailscale_hostname
    from tradinglab.telemetry.windows_tasks import task_plan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database", default="central.sqlite3")
    parser.add_argument(
        "--daily-account-id", help="Incluye consolidación/retención en la tarea diaria"
    )
    parser.add_argument(
        "--tailscale-host",
        type=tailscale_hostname,
        help="FQDN público exacto de Tailscale; opcional",
    )
    args = parser.parse_args(argv)
    try:
        storage = args.data_dir.resolve(strict=True)
        python = ROOT / ".venv" / "Scripts" / "python.exe"
        if (
            not storage.is_dir()
            or not (storage / "host.json").is_file()
            or not (storage / ".env.central").is_file()
            or not python.is_file()
        ):
            raise ValueError("Falta preparar el host central o el Python de .venv")
        tasks = task_plan(
            ROOT,
            storage,
            start_date=date.today(),
            tailscale_host=args.tailscale_host,
            daily_account_id=args.daily_account_id,
            database=args.database,
        )
        if not args.apply:
            print("Vista previa; no se modificó Task Scheduler:")
            for task in tasks:
                print(f"- {task.name}: {task.description}")
            if args.tailscale_host:
                print(
                    f"Host público: {args.tailscale_host}; origen HTTPS: https://{args.tailscale_host}"
                )
            else:
                print("Sin host público adicional: acceso solo por loopback.")
            print("Use --apply únicamente en una ventana operativa autorizada.")
            return 0
        if sys.platform != "win32":
            raise RuntimeError("La instalación solo está disponible en Windows")
        user_id = getpass.getuser()
        for task in tasks:
            existing = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", task.name],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
            if existing.returncode == 0:
                raise RuntimeError(f"La tarea ya existe y no será sobrescrita: {task.name}")
        with tempfile.TemporaryDirectory(prefix="tradinglab-tasks-") as temporary:
            for index, task in enumerate(tasks):
                xml_path = Path(temporary) / f"task-{index}.xml"
                xml_path.write_text(task.xml(user_id=user_id), encoding="utf-16")
                result = subprocess.run(
                    ["schtasks.exe", "/Create", "/TN", task.name, "/XML", str(xml_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    shell=False,
                )
                if result.returncode:
                    raise RuntimeError(
                        f"No se pudo registrar {task.name}; no se sobrescribieron tareas"
                    )
                print(f"Tarea registrada: {task.name}")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
