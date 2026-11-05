#!/usr/bin/env python3
"""Launch the prepared API on loopback; optional exact Tailscale HTTPS hostname."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from central_api import main as central_main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.remote_host import read_host_config, tailscale_hostname

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--tailscale-host", type=tailscale_hostname)
    args = parser.parse_args(argv)
    try:
        if not args.data_dir.is_absolute() or args.data_dir.is_symlink():
            raise ValueError("Directorio inválido")
        directory = args.data_dir.resolve(strict=True)
        if directory.is_relative_to(ROOT.resolve()):
            raise ValueError("El directorio operativo debe estar fuera de Git")
        if (directory / "host.json").is_symlink():
            raise ValueError("Configuración enlazada no admitida")
        config = read_host_config(directory / "host.json")
        if any(
            not (directory / name).is_file() or (directory / name).is_symlink()
            for name in (
                "central-v1.sqlite3",
                "central-v2.sqlite3",
                ".env.central",
            )
        ):
            raise ValueError("Preparación incompleta")
    except ValueError, OSError:
        print("Host incompleto o configuración inválida; no se inició la API.", file=sys.stderr)
        return 1
    command = [
        "--v1-db",
        str(directory / "central-v1.sqlite3"),
        "--v2-db",
        str(directory / "central-v2.sqlite3"),
        "--source-id",
        config.v1_source_id,
        "--account-id",
        config.account_id,
        "--secrets-file",
        str(directory / ".env.central"),
        "--port",
        str(config.port),
    ]
    if args.tailscale_host:
        command.extend(("--allowed-host", args.tailscale_host))
    return central_main(command)


if __name__ == "__main__":
    raise SystemExit(main())
