#!/usr/bin/env python3
"""Prepare a fresh private API host; default is preview, not deployment."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.remote_host import prepare_host, read_host_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="JSON público de identidad")
    parser.add_argument(
        "--data-dir", type=Path, required=True, help="Directorio nuevo fuera de Git"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = prepare_host(ROOT, args.data_dir, read_host_config(args.config), apply=args.apply)
    except ValueError, OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError:
        print(
            "Preparación rechazada: revise configuración, destino nuevo y permisos. "
            "No se borró ni sobrescribió nada; un fallo puede dejar un destino parcial.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2))
    print("No se iniciaron servicios ni se configuró Tailscale. Consulte remote-host-setup.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
