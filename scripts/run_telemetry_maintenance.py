#!/usr/bin/env python3
"""Create a verified, non-destructive backup of the central SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.backup import BackupPlan
    from tradinglab.telemetry.central_schema import CENTRAL_SCHEMA_VERSION
    from tradinglab.telemetry.operational_job import exclusive_job_lock, write_job_status

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=ROOT / "_storage")
    parser.add_argument("--database", default="central.sqlite3")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        storage = args.storage_root.resolve(strict=True)
        plan = BackupPlan(ROOT, args.database, storage, (CENTRAL_SCHEMA_VERSION,))
        _ = plan.source
        if not args.apply:
            print("Vista previa: se crearía una copia SQLite central verificada.")
            return 0
        status = storage / "operations" / "maintenance-status.json"
        with exclusive_job_lock(storage / "operations" / "maintenance.lock"):
            write_job_status(status, job="telemetry-maintenance", state="running", detail="Inicio")
            result = plan.apply()
            write_job_status(
                status,
                job="telemetry-maintenance",
                state="succeeded",
                detail=f"Copia verificada: {result.size_bytes} bytes",
            )
        print("Mantenimiento terminado: copia central verificada.")
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as exc:
        try:
            if args.apply and args.storage_root.is_dir():
                write_job_status(
                    args.storage_root / "operations" / "maintenance-status.json",
                    job="telemetry-maintenance",
                    state="failed",
                    detail=type(exc).__name__,
                )
        except OSError:
            pass
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
