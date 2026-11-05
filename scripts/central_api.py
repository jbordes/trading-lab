#!/usr/bin/env python3
"""Run the opt-in central API on loopback, with two existing durable databases."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

KEY_NAMES = (
    "CENTRAL_V1_INGEST",
    "CENTRAL_V1_READ",
    "CENTRAL_V2_LIVE",
    "CENTRAL_V2_ACTIVITY",
    "CENTRAL_V2_READ",
)


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    from tradinglab.telemetry.central_api import CentralSettings, create_central_app
    from tradinglab.telemetry.local_secrets import load_local_secrets
    from tradinglab.telemetry.operational_job import exclusive_job_lock

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-db", required=True, type=Path)
    parser.add_argument("--v2-db", required=True, type=Path)
    parser.add_argument("--source-id", required=True, help="Fuente v1 ya provisionada")
    parser.add_argument("--account-id", required=True, help="Cuenta v2 ya provisionada")
    parser.add_argument("--secrets-file", type=Path, help="Archivo local .env.central ignorado")
    parser.add_argument("--port", type=int, default=8781)
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("Puerto inválido")
        if any(not path.is_absolute() or not path.is_file() for path in (args.v1_db, args.v2_db)):
            raise ValueError("Configure bases existentes con rutas absolutas")
        if args.v1_db.resolve() == args.v2_db.resolve():
            raise ValueError("Las bases v1 y v2 deben ser distintas")
        environment = dict(os.environ)
        if args.secrets_file is not None:
            environment = load_local_secrets(
                args.secrets_file, allowed_names=KEY_NAMES, environment=environment
            )
        settings = CentralSettings(
            args.v1_db,
            args.v2_db,
            args.source_id,
            args.account_id,
            *(environment.get(name, "") for name in KEY_NAMES),
        )
        with exclusive_job_lock(args.v2_db.with_suffix(".central.lock")):
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
