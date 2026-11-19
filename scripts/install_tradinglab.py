#!/usr/bin/env python3
"""Prepare a new installation, preview by default; never starts MT5 or services."""

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
    from tradinglab.installation import prepare_installation, read_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--allow-real-account", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = prepare_installation(
            ROOT,
            args.data_dir,
            read_config(args.config),
            apply=args.apply,
            allow_real_account=args.allow_real_account,
        )
        print(json.dumps(result))
    except OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError:
        print(
            "Instalación rechazada: revise configuración, destino, permisos y habilitación real. "
            "Si quedaron archivos parciales, consérvelos para revisión.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
