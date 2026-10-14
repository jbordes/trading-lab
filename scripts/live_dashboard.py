#!/usr/bin/env python3
"""Run the TradingLab read-only MT5 dashboard on localhost."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


def interval(value: str) -> float:
    parsed = float(value)
    if not 2.0 <= parsed <= 3600.0:
        raise argparse.ArgumentTypeError("El intervalo debe estar entre 2 y 3600 segundos")
    return parsed


def port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("El puerto debe estar entre 1 y 65535")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo", action="store_true", help="Usa datos sintéticos sin conectar MT5."
    )
    parser.add_argument("--interval", type=interval, default=5.0, help="Segundos entre lecturas.")
    parser.add_argument("--port", type=port, default=8765, help="Puerto local.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from tradinglab.dashboard.service import LiveDashboardService
    from tradinglab.dashboard.snapshot import DemoSnapshotSource, Mt5SnapshotSource
    from tradinglab.dashboard.web import create_server

    args = parse_args(argv)
    if args.demo:
        source = DemoSnapshotSource()
    else:
        try:
            mt5 = importlib.import_module("MetaTrader5")
        except ModuleNotFoundError:
            print(
                "Error: MetaTrader5 no está instalado. Use `uv sync --locked --extra mt5` "
                "o ejecute con --demo.",
                file=sys.stderr,
            )
            return 3
        source = Mt5SnapshotSource(mt5)

    service = LiveDashboardService(source, interval_seconds=args.interval)
    server = create_server(service, port=args.port)
    service.start()
    print(f"TradingLab Live (solo lectura): http://127.0.0.1:{server.server_port}")
    print("Presione Ctrl+C para detener.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nDeteniendo dashboard.")
    finally:
        server.server_close()
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
