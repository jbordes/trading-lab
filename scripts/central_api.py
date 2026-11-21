#!/usr/bin/env python3
"""Run the central API on loopback over one existing durable SQLite database."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

KEY_NAMES = (
    "CENTRAL_SNAPSHOT_INGEST",
    "CENTRAL_ACCOUNT_READ",
    "CENTRAL_LIVE_INGEST",
    "CENTRAL_ACTIVITY_INGEST",
    "CENTRAL_TRADING_READ",
)


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    from tradinglab.telemetry.central_api import CentralSettings, create_central_app
    from tradinglab.telemetry.local_secrets import load_local_secrets
    from tradinglab.telemetry.operational_job import exclusive_job_lock

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite central schema 7")
    parser.add_argument("--source-id", required=True, help="Fuente de estado ya provisionada")
    parser.add_argument("--account-id", required=True, help="Cuenta ya provisionada")
    parser.add_argument("--secrets-file", type=Path, help="Archivo local .env.central ignorado")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument(
        "--public-origin",
        action="append",
        default=[],
        help="Origen HTTPS público exacto (esquema, host permitido y puerto); sin comodines",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Nombre DNS Tailscale exacto adicional; no cambia el bind loopback",
    )
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("Puerto inválido")
        if not args.db.is_absolute() or not args.db.is_file():
            raise ValueError("Configure una base central existente con ruta absoluta")
        from tradinglab.telemetry.remote_host import tailscale_hostname

        allowed_hosts = (
            "127.0.0.1",
            "localhost",
            *(tailscale_hostname(x) for x in args.allowed_host),
        )
        environment = dict(os.environ)
        if args.secrets_file is not None:
            environment = load_local_secrets(
                args.secrets_file, allowed_names=KEY_NAMES, environment=environment
            )
        settings = CentralSettings(
            args.db,
            args.source_id,
            args.account_id,
            *(environment.get(name, "") for name in KEY_NAMES),
            allowed_hosts=allowed_hosts,
            public_origins=tuple(args.public_origin),
        )
        with exclusive_job_lock(args.db.with_suffix(".central.lock")):
            app = create_central_app(settings)
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=args.port,
                workers=1,
                limit_concurrency=16,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=10,
                proxy_headers=False,
                access_log=False,
            )
    except ValueError, OSError, RuntimeError:
        print(
            "Error: revise bases, credenciales, puerto y permisos de la API central.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
