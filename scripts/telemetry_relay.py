#!/usr/bin/env python3
"""Opt-in durable relay: initialize a new outbox, or serve loopback and forward."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from tradinglab.telemetry.local_secrets import load_local_secrets
    from tradinglab.telemetry.operational_job import exclusive_job_lock
    from tradinglab.telemetry.relay import RelayForwarder, RelayIngress
    from tradinglab.telemetry.relay_config import load_relay_producers, relay_token_names
    from tradinglab.telemetry.relay_http import create_relay_server
    from tradinglab.telemetry.relay_queue import (
        RelayQueue,
        RelayStorageError,
        create_relay_database,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queue", required=True, type=Path, help="Ruta absoluta .sqlite3 de outbox"
    )
    parser.add_argument("--init-queue", action="store_true", help="Crear cola nueva y salir")
    parser.add_argument(
        "--retry-stream", help="Revisar rechazados de v1:fuente o v2:fuente y salir"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Rehabilitar rechazados del stream indicado"
    )
    parser.add_argument("--config", type=Path, help="Topología JSON sin secretos")
    parser.add_argument(
        "--secrets-file", type=Path, help="Archivo .env ignorado; variables RELAY_*"
    )
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--max-mib", type=int, default=64)
    parser.add_argument("--max-records", type=int, default=100_000)
    args = parser.parse_args(argv)
    try:
        if not args.queue.is_absolute() or args.queue.suffix != ".sqlite3":
            raise ValueError("Use una ruta absoluta .sqlite3")
        if args.queue.is_symlink():
            raise ValueError("La cola no puede ser un enlace simbólico")
        if args.apply and not args.retry_stream:
            raise ValueError("--apply solo corresponde a --retry-stream")
        if args.retry_stream:
            if args.init_queue:
                raise ValueError("No combine inicialización y reintento")
            with exclusive_job_lock(args.queue.with_suffix(".lock")):
                queue = RelayQueue(args.queue)
                try:
                    count = queue.retry_rejected(args.retry_stream, apply=args.apply)
                    print(f"Rechazados: {count}; aplicación: {args.apply}")
                finally:
                    queue.close()
            return 0
        if args.init_queue:
            create_relay_database(args.queue)
            print("Cola durable creada; ningún receptor fue iniciado.")
            return 0
        if args.config is None:
            raise ValueError("Indique --config")
        environment = dict(os.environ)
        if args.secrets_file is not None:
            # The allowlist comes only from the topology, never from arbitrary env keys.
            names = relay_token_names(args.config)
            if any(not name.startswith("RELAY_") for name in names):
                raise ValueError("El archivo de secretos solo admite nombres RELAY_*")
            environment = load_local_secrets(
                args.secrets_file, allowed_names=names, environment=environment
            )
        producers = load_relay_producers(args.config, environment)
        with exclusive_job_lock(args.queue.with_suffix(".lock")):
            queue = RelayQueue(
                args.queue, max_bytes=args.max_mib * 1024**2, max_records=args.max_records
            )
            try:
                ingress = RelayIngress(queue, producers)
                forwarder = RelayForwarder(ingress)
                server = create_relay_server(ingress, port=args.port)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                print(f"Relay durable: http://127.0.0.1:{server.server_port}; ACK local")
                try:
                    while True:
                        forwarder.run_once()
                        threading.Event().wait(0.25)
                except KeyboardInterrupt:
                    pass
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=6)
            finally:
                queue.close()
    except ValueError, OSError, RuntimeError, sqlite3.Error, RelayStorageError:
        # Config/network errors can contain credentials or URLs: do not echo them.
        print("Error del relay: revise configuración, cola, permisos y puerto.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
