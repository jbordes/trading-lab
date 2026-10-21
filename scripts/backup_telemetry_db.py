#!/usr/bin/env python3
"""Preview or create one verified local backup of a telemetry SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.backup import BackupPlan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filename", required=True, help="Base existente bajo _storage/.")
    parser.add_argument("--apply", action="store_true", help="Crear una copia verificada.")
    args = parser.parse_args(argv)
    try:
        plan = BackupPlan(ROOT, args.filename)
        source = plan.source
        if not args.apply:
            print(f"Vista previa: se copiaría {source} en _storage/backups/.")
            return 0
        result = plan.apply()
        print(f"Copia verificada: {result.directory}")
        print(f"SHA-256: {result.sha256}; bytes: {result.size_bytes}")
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
