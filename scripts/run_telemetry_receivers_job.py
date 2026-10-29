#!/usr/bin/env python3
"""Run independent receivers as one non-interactive, scheduler-friendly job."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.operational_job import (
        exclusive_job_lock,
        run_logged,
        write_job_status,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=ROOT / "_storage")
    parser.add_argument("--secrets-file", type=Path, default=ROOT / ".env.local")
    args = parser.parse_args(argv)
    try:
        storage = args.storage_root.resolve(strict=True)
        secrets = args.secrets_file.resolve(strict=True)
        if not storage.is_dir() or not secrets.is_file():
            raise ValueError("Almacenamiento o archivo local de secretos inválido")
        operations = storage / "operations"
        status = operations / "receivers-status.json"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "start_telemetry_v2_component.py"),
            "receivers",
            "--storage-root",
            str(storage),
            "--secrets-file",
            str(secrets),
        ]
        with exclusive_job_lock(operations / "receivers.lock"):
            write_job_status(status, job="telemetry-receivers", state="running", detail="Inicio")
            return_code = run_logged(
                command,
                cwd=ROOT,
                log_path=operations / "receivers.log",
            )
            write_job_status(
                status,
                job="telemetry-receivers",
                state="failed" if return_code else "succeeded",
                detail=f"Proceso finalizado con código {return_code}",
            )
        return return_code
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
