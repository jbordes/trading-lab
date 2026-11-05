#!/usr/bin/env python3
"""Run the prepared central API as one non-interactive supervised job."""

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
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not args.data_dir.is_absolute() or args.data_dir.is_symlink():
            raise ValueError("Use un directorio absoluto sin enlace simbólico")
        storage = args.data_dir.resolve(strict=True)
        if storage.is_relative_to(ROOT.resolve()):
            raise ValueError("El host operativo debe estar fuera del checkout")
        if not storage.is_dir() or not (storage / "host.json").is_file():
            raise ValueError("Host central no preparado")
        operations = storage / "operations"
        status = operations / "central-api-status.json"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_remote_host.py"),
            "--data-dir",
            str(storage),
        ]
        with exclusive_job_lock(operations / "central-api.lock"):
            write_job_status(status, job="central-api", state="running", detail="Inicio")
            return_code = run_logged(
                command,
                cwd=ROOT,
                log_path=operations / "central-api.log",
            )
            write_job_status(
                status,
                job="central-api",
                state="failed" if return_code else "succeeded",
                detail=f"Proceso finalizado con código {return_code}",
            )
        return return_code
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
