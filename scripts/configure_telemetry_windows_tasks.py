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
    from tradinglab.telemetry.windows_tasks import task_plan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=ROOT / "_storage")
    parser.add_argument("--secrets-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        storage = args.storage_root.resolve(strict=True)
        secrets = args.secrets_file.resolve(strict=True)
        python = ROOT / ".venv" / "Scripts" / "python.exe"
        if not storage.is_dir() or not secrets.is_file() or not python.is_file():
            raise ValueError("Falta almacenamiento, .env.local o el Python de .venv")
        tasks = task_plan(ROOT, storage, secrets, start_date=date.today())
        if not args.apply:
            print("Vista previa; no se modificó Task Scheduler:")
            for task in tasks:
                print(f"- {task.name}: {task.description}")
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
