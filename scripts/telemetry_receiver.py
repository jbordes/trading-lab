#!/usr/bin/env python3
"""Run the loopback-only receiver for the MT5 telemetry collector spike."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TOKEN_ENVIRONMENT_VARIABLE = "TRADINGLAB_TELEMETRY_TOKEN"


def port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("El puerto debe estar entre 1 y 65535")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=port, default=8766, help="Puerto local de ingestión.")
    parser.add_argument("--sqlite-db", type=Path, help="Base SQLite existente.")
    parser.add_argument(
        "--storage-root",
        type=Path,
        help="Directorio local autorizado que contiene la base; por defecto _storage/.",
    )
    parser.add_argument("--source-id", help="Fuente única autorizada para esta base y token.")
    parser.add_argument(
        "--max-messages",
        type=int,
        default=500,
        help="Cantidad máxima de mensajes conservados solo en memoria.",
    )
    parser.add_argument(
        "--max-retained-mib",
        type=int,
        default=16,
        help="Presupuesto de contenido serializado retenido (1..64 MiB).",
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=8,
        help="Conexiones atendidas simultáneamente (1..32).",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=5.0,
        help="Plazo máximo de red por conexión en segundos (0.05..30).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    credential = os.environ.get(TOKEN_ENVIRONMENT_VARIABLE, "")
    if len(credential) < 24:
        print(
            f"Error: configure {TOKEN_ENVIRONMENT_VARIABLE} con al menos 24 caracteres.",
            file=sys.stderr,
        )
        return 2

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from tradinglab.telemetry.ingest import TelemetryBuffer, create_telemetry_server
    from tradinglab.telemetry.persistent_receiver import PersistentTelemetryReceiver
    from tradinglab.telemetry.sqlite_store import TelemetryStorageError

    persistent: PersistentTelemetryReceiver | None = None
    try:
        if (args.sqlite_db is None) != (args.source_id is None):
            raise ValueError("--sqlite-db y --source-id deben indicarse juntos")
        if args.sqlite_db is not None:
            storage_root = (args.storage_root or root / "_storage").resolve(strict=True)
            if not storage_root.is_dir():
                raise ValueError("El directorio de almacenamiento no es válido")
            database = args.sqlite_db.resolve(strict=True)
            if not database.is_relative_to(storage_root):
                raise ValueError("La base SQLite debe estar bajo --storage-root")
            persistent = PersistentTelemetryReceiver(database, source_id=args.source_id)
            buffer = persistent
        else:
            buffer = TelemetryBuffer(
                max_messages=args.max_messages,
                max_retained_bytes=args.max_retained_mib * 1024 * 1024,
            )
        server = create_telemetry_server(
            buffer,
            token=credential,
            port=args.port,
            max_connections=args.max_connections,
            request_timeout=args.request_timeout,
        )
    except (ValueError, TelemetryStorageError, OSError) as exc:
        if persistent is not None:
            persistent.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Receptor MT5 del spike: http://127.0.0.1:{server.server_port}")
    print("Ingesta y lectura local autenticadas. Ctrl+C para detener.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nDeteniendo receptor.")
    finally:
        server.server_close()
        if persistent is not None:
            persistent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
