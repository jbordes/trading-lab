#!/usr/bin/env python3
"""Run the isolated loopback receiver for provisioned telemetry v2 pilot sources."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def live_authorization_environment() -> str:
    return "TRADINGLAB_TELEMETRY_LIVE_TOKEN"


def activity_authorization_environment() -> str:
    return "TRADINGLAB_TELEMETRY_ACTIVITY_TOKEN"


def port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("El puerto debe estar entre 1 y 65535")
    return parsed


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.ingest_v2 import create_v2_telemetry_server
    from tradinglab.telemetry.persistent_receiver_v2 import PersistentV2TelemetryReceiver
    from tradinglab.telemetry.sqlite_store_v2 import V2StorageError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=port, default=8777, help="Puerto local de ingesta v2.")
    parser.add_argument("--sqlite-db", type=Path, required=True, help="Base v2 bajo _storage/.")
    parser.add_argument("--account-id", required=True, help="Cuenta interna provisionada.")
    parser.add_argument("--max-connections", type=int, default=8)
    parser.add_argument("--request-timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    live_authorization = os.environ.get(live_authorization_environment(), "")
    activity_authorization = os.environ.get(activity_authorization_environment(), "")
    receiver: PersistentV2TelemetryReceiver | None = None
    try:
        storage_root = (ROOT / "_storage").resolve()
        database = args.sqlite_db.resolve(strict=True)
        if not database.is_relative_to(storage_root):
            raise ValueError("La base SQLite debe estar bajo _storage/")
        receiver = PersistentV2TelemetryReceiver(
            database,
            account_id=args.account_id,
            live_authorization=live_authorization,
            activity_authorization=activity_authorization,
        )
        server = create_v2_telemetry_server(
            receiver,
            port=args.port,
            max_connections=args.max_connections,
            request_timeout=args.request_timeout,
        )
    except (ValueError, V2StorageError, OSError) as exc:
        if receiver is not None:
            receiver.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Receptor MT5 v2 piloto: http://127.0.0.1:{server.server_port}/v2/telemetry")
    print("Credenciales live/activity separadas, solo en memoria. Ctrl+C para detener.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nDeteniendo receptor v2.")
    finally:
        server.server_close()
        receiver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
