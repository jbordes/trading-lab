#!/usr/bin/env python3
"""Run an explicitly prepared installation; its architecture must match this checkout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.installation import read_installation
    from tradinglab.installation_backend import run_backend

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = read_installation(args.data_dir)
        if args.dry_run:
            print(
                f"Instalación válida: {config.account_id}; modo={config.account_mode}; "
                f"dashboard=http://127.0.0.1:{config.dashboard_port}/dashboard"
            )
            return 0
        run_backend(ROOT, args.data_dir.resolve(strict=True), config)
    except KeyboardInterrupt:
        print("TradingLab detenido.")
    except OSError, ValueError, RuntimeError:
        print(
            "Error de arranque: revise instalación, permisos, credenciales y puertos.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
