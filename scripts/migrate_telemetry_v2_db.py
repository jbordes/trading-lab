#!/usr/bin/env python3
"""Preview or apply the guarded telemetry v2 schema 3 to 4 migration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _storage_file(name: str) -> Path:
    candidate = Path(name)
    if candidate.name != name or candidate.suffix != ".sqlite3":
        raise ValueError("Use solo un nombre .sqlite3 dentro de _storage/")
    return ROOT / "_storage" / candidate


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.sqlite_store_v2 import (
        V2StorageError,
        migrate_v2_database_v3_to_v4,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filename", required=True, help="Base existente bajo _storage/.")
    parser.add_argument(
        "--backup-filename",
        required=True,
        help="Copia nueva y verificada bajo _storage/.",
    )
    parser.add_argument("--apply", action="store_true", help="Crear la copia y migrar la base.")
    args = parser.parse_args(argv)
    try:
        database = _storage_file(args.filename)
        backup = _storage_file(args.backup_filename)
        if not database.is_file():
            raise FileNotFoundError(f"La base no existe: {database}")
        if backup.exists():
            raise FileExistsError(f"La copia ya existe: {backup}")
        if not args.apply:
            print("Vista previa: no se modificará ningún archivo.")
            print(f"Base: {database}")
            print(f"Copia previa: {backup}")
            print("Migración: esquema 3 -> 4; agrega ciclos de posición durables.")
            return 0
        projected = migrate_v2_database_v3_to_v4(database, backup)
        print(f"Base migrada y verificada: {database}")
        print(f"Copia previa verificada: {backup}")
        print(f"Reconciliaciones existentes proyectadas: {projected}")
    except (ValueError, FileExistsError, OSError, V2StorageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
