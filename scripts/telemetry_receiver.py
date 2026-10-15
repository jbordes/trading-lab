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
    parser.add_argument(
        "--max-messages",
        type=int,
        default=500,
        help="Cantidad máxima de mensajes conservados solo en memoria.",
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

    try:
        buffer = TelemetryBuffer(max_messages=args.max_messages)
        server = create_telemetry_server(buffer, token=credential, port=args.port)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Receptor MT5 del spike: http://127.0.0.1:{server.server_port}")
    print("Solo acepta POST /v1/telemetry autenticado. Ctrl+C para detener.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nDeteniendo receptor.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
