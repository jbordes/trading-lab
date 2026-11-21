#!/usr/bin/env python3
"""Preview or create one fresh, fully registered central SQLite database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.remote_host import create_registered_database, read_host_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = read_host_config(args.config)
        database = args.database
        if (
            not database.is_absolute()
            or database.suffix != ".sqlite3"
            or database.exists()
            or database.is_symlink()
            or not database.parent.is_dir()
        ):
            raise ValueError("Use un archivo .sqlite3 nuevo con ruta absoluta y padre existente")
        if args.apply:
            create_registered_database(database, config)
            print("SQLite central creada y verificada; no se iniciaron servicios.")
        else:
            print("Vista previa válida; no se crearon archivos. Use --apply para crear.")
        return 0
    except ValueError, OSError, RuntimeError:
        print(
            "Error: revise configuración y destino; no se migró ni sobrescribió una base.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
