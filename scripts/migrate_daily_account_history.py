#!/usr/bin/env python3
"""Preview the central SQLite 7 -> 8 upgrade; --apply requires a prior backup."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.central_migration import migrate_daily_history

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = migrate_daily_history(args.db, apply=args.apply)
    except OSError, ValueError, sqlite3.Error:
        print("Migración rechazada: revise versión, integridad, permisos y servicios detenidos.")
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
